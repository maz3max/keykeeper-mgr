#!/usr/bin/python3

import re
import os
import secrets


# generate human-readable colon-separated BLE address string
def addr_to_str(addr):
    hex_arr = ["%02X" % b for b in addr[::-1]]
    return ":".join(hex_arr)


class KeykeeperDB:
    def __init__(self):
        self.coins = {}
        self.identity = []
        self.load()

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

    def load(self, coins="coins.txt", central="central.txt"):
        coin_list = []
        identity = None
        with open(coins, "r") as f:
            for line in f:
                m = re.match(r"(.{17})\s+(.{32})\s+(.{32})\s+(.{64})", line)
                if m:
                    self.coins[m.group(1)] = m.groups()[1:]
        with open(central, "r") as f:
            line = f.readline()
            m = re.match(r"(.{17})\s+(.{32})", line)
            if m:
                self.identity = m.groups()
