#!/usr/bin/python3

import json
import base64
import os
import secrets
from simplecrypt import encrypt, decrypt


# generate human-readable colon-separated BLE address string
def addr_to_str(addr):
    hex_arr = ["%02X" % b for b in addr[::-1]]
    return ":".join(hex_arr)


class KeykeeperDB:
    def __init__(self, filename, passw=''):
        self.n = filename
        self.p = passw
        if os.path.exists(filename):
            with open(filename, "r") as f:
                json_db = json.load(f)
            if list(json_db.keys()) == ['encrypted']:
                json_db = json.loads(
                    decrypt(passw, base64.b64decode(json_db['encrypted'])))
            assert list(json_db.keys()) == [
                'identity', 'coins', 'names'], "invalid db file!"
            self.identity = json_db['identity']
            assert len(self.identity) == 2, "invalid db file!"
            self.coins = json_db['coins']
            self.names = json_db['names']
            assert len(self.coins) == len(self.names), "invalid db file!"
        else:
            self.coins = {}
            self.names = {}
            self.generate_identity()

    def generate_identity(self):
        central_addr = bytearray(secrets.token_bytes(6))
        central_addr[5] |= 0xc0
        central_irk = secrets.token_bytes(16)
        self.identity = [addr_to_str(central_addr), central_irk.hex().upper()]

    def generate_coin(self, name):
        assert name not in self.names.keys()
        addr = bytearray(secrets.token_bytes(6))
        addr[5] |= 0xc0
        addr = addr_to_str(addr)
        while addr in self.coins.keys():
            addr = bytearray(secrets.token_bytes(6))
            addr[5] |= 0xc0
            addr = addr_to_str(addr)
        irk = secrets.token_bytes(16).hex().upper()
        ltk = secrets.token_bytes(16).hex().upper()
        spacekey = secrets.token_bytes(32).hex().upper()
        self.coins[addr] = [irk, ltk, spacekey]
        self.names[name] = addr

    def save(self):
        json_db = json.dumps({
            'identity': self.identity,
            'coins': self.coins,
            'names': self.names,
        })
        if len(self.p) > 0:
            e = str(base64.b64encode(encrypt(self.p, json_db)), 'ASCII')
            json_db = json.dumps({
                'encrypted': e,
            })
        with open(self.n, 'w') as f:
            f.write(json_db)


if __name__ == '__main__':
    db = KeykeeperDB('new_db.json', '')
    db.generate_coin('Paul')
    db.generate_coin('Katja')
    print("identity:", db.identity)
    print("coins:", db.coins)
    print("names:", db.names)
    db.save()
