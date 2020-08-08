#!/usr/bin/python3
import re
import aioserial
import asyncio
import multiprocessing
import serial.serialutil
import os
import sys
import time
from key_db import KeykeeperDB
from enum import IntEnum


class StatusType(IntEnum):
    IDENTITY = 0
    DEVICE_FOUND = 1
    BATTERY_LEVEL = 2
    CONNECTED = 3
    AUTHENTICATED = 4
    DISCONNECTED = 5


class Coin:
    def __init__(self):
        self.battery_level = 0
        self.address = "00:00:00:00:00:00"


class KeykeeperSerialMgr:
    def __init__(self, db):
        self.config_mode = True
        self.db = db

    # read line and remove color codes
    async def _serial_fetch_line(self):
        line = (await self.central_serial.readline_async()).decode(errors='ignore')
        plain_line = re.sub(r'''
            \x1B    # ESC
            [@-_]   # 7-bit C1 Fe
            [0-?]*  # Parameter bytes
            [ -/]*  # Intermediate bytes
            [@-~]   # Final byte
        ''', '', line, flags=re.VERBOSE)
        return plain_line

    # parse status messages
    def _parse_status(self, l):
        regs = {
            StatusType.IDENTITY: r"<inf> bt_hci_core: Identity: (.{17}) \((.*)\)",
            StatusType.DEVICE_FOUND: r"<inf> app: Device found: \[(.{17})\] \(RSSI (-?\d+)\) \(TYPE (\d)\) \(BONDED (\d)\)",
            StatusType.BATTERY_LEVEL: r"<inf> app: Battery Level: (\d{1,3})%",
            StatusType.CONNECTED: r"<inf> app: Connected: \[(.{17})\]",
            StatusType.AUTHENTICATED: r"<inf> app: KEY AUTHENTICATED. OPEN DOOR PLEASE.",
            StatusType.DISCONNECTED: r"<inf> app: Disconnected: \[(.{17})\] \(reason (\d+)\)",
        }
        for k in regs:
            m = re.search(pattern=regs[k], string=l)
            if m:
                return k, m.groups()
        return None, None

    # read registered bonds
    async def _request_bonds(self):
        bonds = []
        self.central_serial.write(b'stats bonds\r\n')
        line = None
        while not (line and line.endswith('stats bonds\r\n')):
            line = await self._serial_fetch_line()
            print(line, end='', flush=True)
        while line != 'done\r\n':
            line = await self._serial_fetch_line()
            bond = re.match(r"\[(.{17})\] keys: 34, flags: 17\r\n", line)
            if bond:
                bonds.append(bond.groups())
        return bonds

    # read registered spacekeys (only first byte)
    async def _request_spacekeys(self):
        spacekeys = []
        self.central_serial.write(b'stats spacekey\r\n')
        line = None
        while not (line and line.endswith('stats spacekey\r\n')):
            line = await self._serial_fetch_line()
            print(line, end='', flush=True)
        while line != 'done\r\n':
            line = await self._serial_fetch_line()
            spacekey = re.match(r"\[(.{17})\] : ([A-F0-9]{2})\.\.\.\r\n", line)
            if spacekey:
                spacekeys.append(spacekey.groups())
        return spacekeys

    # read settings
    async def _read_settings(self):
        self.central_serial.write(b'settings load\r\n')
        line = None
        k = None
        while k != StatusType.IDENTITY:
            line = await self._serial_fetch_line()
            print(line, end='', flush=True)
            k, v = self._parse_status(line)
            if 'bt_hci_core: Read Static Addresses command not available' in line:
                break
            if k == StatusType.IDENTITY:
                self.identity = v[0].upper()

    async def _wait_until_done(self):
        line = None
        while line != 'done\r\n':
            line = await self._serial_fetch_line()
            print(line, end='', flush=True)

    # main state machine routine

    async def _manage_serial(self):
        # clear old state
        self.identity = None
        self.bonds = None
        self.spacekeys = None

        if self.config_mode:
            # just load settings, don't start scanning
            await self._read_settings()
            # read coin data from device
            self.bonds = await self._request_bonds()
            self.spacekeys = await self._request_spacekeys()
            print(self.identity, self.bonds, self.spacekeys)
            # TODO: check if configured correctly
            if self.identity != self.db.identity[0]:
                if self.identity:
                    self.central_serial.write(b'settings clear\r\n')
                    await self._wait_until_done()
                else:
                    self.central_serial.write('central_setup {} {}\r\n'.format(
                        *self.db.identity).encode('ASCII'))
                    await self._wait_until_done()
            if len(self.bonds) != len(self.spacekeys):
                self.central_serial.write(b'settings clear\r\n')
            is_present = {c: False for c in self.db.coins.keys()}
            for bond, skey in zip(self.bonds, self.spacekeys):
                if bond[0] != skey[0]:
                    self.central_serial.write(b'settings clear\r\n')
                    await self._wait_until_done()
                if bond[0] not in self.db.coins or skey[1] != self.db.coins[bond[0]][2][:2]:
                    self.central_serial.write(
                        'coin del {}\r\n'.format(bond[0]).encode('ASCII'))
                    await self._wait_until_done()
                else:
                    is_present[bond[0]] = True
            for addr, present in is_present.items():
                if not present:
                    self.central_serial.write('coin add {} {} {} {}\r\n'.format(
                        addr, *self.db.coins[addr]).encode('ASCII'))
                    await self._wait_until_done()
            self.config_mode = False
            self.central_serial.write(b'reboot\r\n')
            await self._wait_until_done()
        else:
            # start BLE stack
            self.central_serial.write(b'ble_start\r\n')

        # main event loop
        while True:
            line = await self._serial_fetch_line()
            print(line, end='', flush=True)
            k, v = self._parse_status(line)
            if k == StatusType.IDENTITY:
                self.identity = v[0].upper()
            if k == StatusType.AUTHENTICATED:
                pass
                # TODO: confirm_authentication(coin_address, battery_level)
            elif k == StatusType.BATTERY_LEVEL:
                self.current_coin.battery_level = v[0]
            elif k == StatusType.CONNECTED:
                self.current_coin.address = v[0].upper()
            elif k == StatusType.DISCONNECTED:
                self.current_coin = Coin

    # main loop with reconnecting
    async def run(self):
        self.current_coin = Coin

        first_start = True
        while True:
            try:
                self.central_serial = aioserial.AioSerial(
                    port=os.path.realpath('/dev/serial/by-id/usb-ZEPHYR_N39_BLE_KEYKEEPER_0.01-if00'))
                self.central_serial.write(b'\r\n\r\n')
                if first_start:
                    self.central_serial.write(b'reboot\r\n')
                    first_start = False
                else:
                    await self._manage_serial()
            except serial.serialutil.SerialException:
                print("LOST CONNECTION. RECONNECTING...", file=sys.stderr)
                await asyncio.sleep(1)


def test_serialmgr():
    db = KeykeeperDB(
        identity=("EF:EF:5A:CB:C2:B6", "6739A4CA7285A253F148F214278EA4C5"),
        coins={
            "EC:EB:CE:D9:FE:14": ("F90016C74FBF43C71C395FD10E2DDC35", "62CDFD007F7A50F642A6C51FE9E0D379", "B2EE49E82DC02579171A238334927A76E162476BC0454B089C13695951AC5BB8"),
            "DA:51:85:04:E5:47": ("3E897CAA5514FA893875BF0B405EDBF0", "39052E84ACDA4A4974CD0A2591809FB7", "F2530598798FCE3EC3A508F22F4BC168B7E134A543F3E54EF41E686A3410288B"),
            "F5:49:13:82:8F:00": ("CB6EB7599D5E68B00547BB4E1BD6D7E1", "73D69DCD715DD1683608BFC535FFFF95", "14FE12588580B11712FF89F62FC1F40BC37C842722BF70C92101AF9DCE006C64"),
            "D9:C2:30:6B:7B:18": ("E0556B6E4CA9CC4995E5E2BDE6F0F03D", "9251618F31025962656A9CCB4287A230", "55133A50A013B2835E860930645CE485FA59F103F3FD793E1B70904834445B68"),
            "ED:1A:73:B8:A8:BA": ("03FE8CAB5B3BD814A43C4169A11C76D7", "62F04BD5C7D9EBB5C1E9761B89BEB61E", "D8F17B0F744D55851CED8AE6EE07C9DFA269ECABE82918B0DB0922E558A31ABE"),
            "F0:1D:05:94:07:3C": ("206B3E94420131CB3E41FBE2134EFFCD", "42AB466B92F846ABF53EFF6C9CFFC6BA", "78721CF7BB130C964F50B88439014E864C2FB18A5B91EB49CEEB5A23526513BA"),
            "ED:1C:55:01:70:2C": ("2BD73ED11B26D762C6611E22E9DF1C78", "7588A7D49FDD83754CC94E38476C7196", "CB4A2CE1D405E094BADF840DE9222E7CE2C0223952E8EA5BC07D818BD781B178"),
            "EE:7A:F6:16:32:2B": ("77873DDCC3E29C71C8CCA02B38859C28", "B82A85994E24AF79901E62887B6B1419", "C875CBA8F6F7DC91BFC54EC3067CD3586172223A4B584692BB7BDFC4E988930A"),
            "EE:7C:CC:19:53:37": ("19F01B71C6BAB648E514BA38BE781D1E", "953E5826169B3869345B1871CC69C2A6", "ACCD276DBDF5B7718027608220CC5644C1838EA65124641FD82C2B5AAE535A43"),
            "C8:CE:86:AB:EB:A5": ("2856D62EBA143C9CA46950713C7EF737", "78B8263E1E05092E7699C980C0550244", "66A0F362C3E9824EBB07BB07624ADFB7B1313E54D2BDD882130A6F25618EED83"),
            "C0:BE:E9:82:AF:71": ("E49691E078BEF32882563AA8A8A22E0D", "BDCF0E007BB7FC7A9E1F12DD022479A5", "50CA906BB7DD52E3D2D85D04ACFEC9A5B7FB09FE01995E8507BBC8C1BED59898"),
            "EA:ED:58:B9:71:B5": ("E54AAF0B5FFF63BFDE9FEEBD694B771D", "D0FA9FF52FC9E5D4D863AA14CB131149", "CF6A26CB733108C6B9E5BADD0C194135F8A48AD112628D147919D782223AF5A6"),
            "C0:F6:FB:AB:AE:90": ("A90B9977C1DCC284193E213A4A11746E", "8703940F0F8C1DC95D8BB3DE112013B1", "043C00B90F7E100D133C9D3DB3E4DEA0A844F12F2134B7281E6E78EBFDE4A11D"),
            "DC:C4:E2:B9:64:B9": ("01658EE720AFCF1DF4E2A84CBA642D9F", "5B97E7B6BA0C82B9DBDE1238933133CD", "836D5772F27FD25FEBE0C77993C10F52829738BE00A9903BC26748A755AB9A46"),
            "C1:E9:4A:8B:49:CD": ("28E567A555CC24075B95AC498713AE2B", "A1F595BB9B0EB1B5D30125D4A69CB0ED", "ED2537E6E922F4E926F12AB0EE5632583BBE4F9B32A7525924B7C337A1D60ECE"),
            "D5:A3:FB:DB:C8:63": ("3E49361FB6810578D290A8BBC4E18581", "E39A5345405DB4D975AA98EAFEC49A6F", "3FAACDFE0DC4D83179C0023C463068F3BB146842C8D4A94A442C02F85077EC99"),
            "D2:BF:90:B4:AB:FE": ("04F9EA12D9EC20D1E5AA292A1343A16D", "2A1600D33FD1582C6CEED0422E8D37A5", "40D647A32106D61521F9C11D5377AF9D769DCE4C20230E4B07B69D50816F19A7"),
            "E5:81:CD:C3:5E:4E": ("691EACF4C3B748F5B8A5D17886AF4FA5", "E664E3901400AD55D2AAEA916510A882", "BBD9F4A31A30083B4395146734E986D6936A810C74882B4631BF07C9F77323F4"),
            "F5:8A:02:33:7B:F1": ("275515F475A8AECAF85BCBC7B1DFF8EA", "D66D69BDE34E446BF49A5CC06C7735C1", "3853E678026AD6B79C45439D5877E4A3700B7E3182E04B2070007B1EF33D550F"),
            "C3:46:5C:E0:A7:4F": ("780DDCD48C4EC780CA7B3C16FDEAA054", "8E81D9057A0906406729370540FAC7B9", "5917C8DAE255979E029D37D115E6945A856CEB305A269542FB77A0D1AB0687FC"),
            "CD:85:6C:17:BD:F8": ("4CC6C5A9A34C164896B7B694C13816E7", "69785B8D65289F16BD58DC1C55D72DE9", "BC00A6158F17308D03F2B8FB1277CB7A8C083DB28971CE30A4B6EFD874E408C7"),
            "EE:AC:D4:34:30:97": ("8C8F69E639666CC92834D80A678253B8", "5A3AD9876B2B4F4E7332966F82EA45B1", "89A7119639F693CF274E96F5BCDB6D6C6054E74828678BD1B9BFA6EA093E3CCB"),
            "FF:69:71:B9:33:54": ("7C233950A01FE0371A345C32D0E78AAA", "ECD0E4CB0934F191596F8D2A6238736B", "FB782042AE4D86555343CFE5DA807A08697519F9474716075840865E384C16E6"),
            "EF:2D:9D:AB:BA:DF": ("DC0E6DF576C030AE4E0B925008728AD0", "D40C5BD7AD2BB957FE199772BCB8027A", "36247711792E474252E32A141FC3B2B1EFDF4B424813DA4268A5C706091DF9DF"),
            "E1:68:E7:20:68:F1": ("42778ABE85190A576CBF3A133026DF68", "CD9EF02683EE88A688664C3743E1D043", "D7C9C3758A2058B3CA788FE4AAC544D106967785573E69450E815C34F47F571E"),
            "D7:BF:6D:42:93:3B": ("1CC4EC8F1C732C9B94904D68925C347C", "674D442045DA78F2633469664C279799", "501A418F3E97C156EBD82BE625C358FA0C1AAB61592A9B50BFA10BB031FE42FA"),
            "F6:E6:7B:74:5F:81": ("8119600F92E0C8828C67B707E0C02BC0", "55198373B9C24957B49098888AC804D1", "C3EEB037227662D2850E714DFDEBCF83CB204C05FB845652A5C633C87C3BCBB7"),
            "DF:32:3B:C8:4B:0F": ("5A1C6649A58530FDA6F75257C87121B2", "D8F88677A2ABD7DC39CDC0D932C151F8", "747B720D481FC313BA50E455E6A7596FE2679982E99A107F7EE1D360F51D908A"),
            "CF:BB:E2:3C:CD:17": ("66A71D75E64223117F40A54E19D1E621", "31786141B4D4DA05230682672EC8A882", "DA8D9BEB12C86B392D832ADD1A10789C31B82544AC6A307E3812259D8D510AA0"),
            "F2:38:48:52:AB:D8": ("D7CF5FCA19C682CF3CD9BB260C8847B8", "3DEB217604530219156BF7EA93047206", "F314B2C402EED66B35F4EEECE0CC19D859640224F5F7E164BA63BF939044424F"),
            "F7:D4:45:B2:78:D5": ("39C24BA0DFA38969B922C3E94D37A193", "63E6CF08F67AF317D462E2341798DA11", "45479A737C081E0F433B517BC381097948E97987FEC86AA2A5997292BDEA602A"),
            "E1:D0:FB:B3:CE:55": ("D45E627078E0886A7F476F9792ABE947", "DD673082D040D45B51D86B21D45925FB", "7803044CB9F05E9D6EB4B33E2DFCE982BFAA32D027DDDCCAB7643DAF3D413F60"),
            "F5:9A:C0:95:A7:A7": ("3C4C7D3DE75FC6D1E4FB0FDB11F59CFB", "F4D1E32CD56BA54F0E72E59E237533B7", "837312A34F564A7CD5F8117048416C0BE0E9615D5DC4BC4E53E57A2EB1185DE9"),
            "FF:53:68:99:DB:B4": ("BA7DBCE156D0606AA469803BE5171646", "3989CFF3E0A943F3722AA6FA78F087B4", "3333B13E8BBB1709D1F77A574801C5034B29202886F04788BD5F4F796E408CF7"),
            "DE:D2:78:4D:85:7D": ("F97700ED0D01D34D8D866B9B1EA52E17", "EB2FDF4C6823AEFA47A1549BF63AF586", "4B4310F99E8823FB7989AC1D7CE3F226163AAAD671AED22F9EEDEB3B216FE45C"),
            "F0:94:52:0E:08:91": ("561971BC9E89B9A1DC5117800DB11F87", "88CCCDC792F220BF441408C6C8C694ED", "E639EFA6BDA6EAFDE878B178272B1D295DA86EEA86069FCC46E8AD42F6410032"),
            "F5:08:DC:29:5A:78": ("D216EA641A12F3B5DFF1F278658D5276", "E5D68D1493580660577E659678483BBD", "F2A2FB2E9E4350878F20BF7E609B761A818425C225FF2E5C2B1846DB774EE23B"),
            "D2:84:A6:7F:13:47": ("98D38446D59E5C9197E4E9F8BEBE2735", "DE39D80FE717D197839135A9E6503B10", "D67D65AF6ACC2E3293B1F56F39E9BE68CAA66D0F5C12F98D57234FC98B050AF9"),
            "FE:D2:76:5B:04:CA": ("83BE07E2D9D873B7A50E15B2582D3791", "D247543FF81C65604CBBC0A63FD99FE2", "1B8E6BDD9531348E6238C0E3B81103B3C0FF8CF770FA0788567278057C84EF18"),
            "DD:AC:7B:44:04:BF": ("BC1B1CCA89D08AD3C7A5F31CD9C6F82F", "777357CB7DE2C2ADCDB3C202A5F80A41", "080928C5A3FB40C8B91F076157D3CB4D4251930C178A740CB385E787C1335F1E"),
            "F3:51:AC:16:4F:7E": ("87FB6BEE6F57845CFC09FA215DEFB6A1", "AA246B394D4FC2A2C232046D54B349DA", "8DD92A5E3B95B255DFC78605C6AB95FBA8012B9FB0B91F3D1BBA4CD4F424FA5D"),
            "CC:C6:63:F6:9B:E2": ("6C6B3BCB591D396958E706B2932A3906", "C2CFA69BA2143455AD5A1CF53E0AB60D", "04B243A68E3F157A5110883D64731274D4CF07EF48A82C1BE794AF2C55424E8A"),
            "CF:66:F1:96:76:D6": ("C85D402AEDDB0E639C50D30051A29C4C", "DBC1A03C400DF4B990ABBB3C9CE2208E", "62280CA2F8F7BD4D5F7D3500C1CCAD795C0DAAC94BA86EBCE102373179CE649F"),
            "EE:03:6A:8A:1B:B1": ("145C448AE37969180D0EB84E5AC85356", "F74ECC1CF374B1F19DE2BB84E15316CA", "A6DCE332F9844C9FE2B0AFD3EA1608FE9922E158BD5DD67E8CA94DF3C155A7A0"),
            "C6:74:24:DF:A9:60": ("076E4C6A4F74ED42DB3687E18C106FDC", "D23A9D297664B4B9289678C56CF10E5E", "28C55612410EE076EBB95E851ADB239B1920BB1B7DFEEB7391EA36E58B390259"),
            "DD:80:8E:30:D9:0B": ("12386AE5DCEE1D58F0BA092BA3A8A723", "02BC999D30AD45ABF0E9ED0E4E3FDB61", "3F92F71C70CA9FC10C091C4AD039AE1F1A0FC44E794552F296D82D37D2FDAF2F"),
            "C1:06:E9:3C:23:F3": ("1C4D2FF8875D76E149304D5E23535C9A", "2E4D7514311523118929FD4CA37D74D2", "DC778BEE9862E8A5E8DA3A7E7D0F24E809E9A2F4E7592D31578E619726DBF0E5"),
            "F2:57:F2:23:B4:CC": ("6847880FFC2CC9EDF60B64A7CE965AA3", "A53B1C6F553B3003F077B15D14B88C4E", "CE44F8BF721B72365733E0E5F54CBF16D3BF3DB1CB047575089D18DB8F541E4E"),
            "D7:7F:B2:3A:CF:21": ("A2AE307B0CCF8A7F640DB4B75A5DAC62", "128AE7E4F5C9E94281F224FDF50FEF40", "47AE67D71F636BB7CE646867C1D87D92D6B34F681516027CAB7B8107347AA5F7"),
            "D3:F3:3C:C5:5C:04": ("223F499DD308DC561F64ED2CB0C979E7", "485EAFD37D3A9D56CFF4AE7E22DF577E", "BEF825961DFAF2CDE616DD5CC66444614383C1AD18D64F06D3C746D33A2310C7"),
        })
    k = KeykeeperSerialMgr(db)
    asyncio.run(asyncio.wait([k.run()]))


if __name__ == "__main__":
    p = multiprocessing.Process(target=test_serialmgr)
    p.start()
