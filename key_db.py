#!/usr/bin/python3

import re
import os
import secrets


class KeykeeperDB:
    def __init__(self):
        self.coins = {}
        self.identity = []
        self.load()

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
