#!/usr/bin/python3

import asyncio
import subprocess
import os
import time
import RPi.GPIO as GPIO

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)
GPIO.setup(13, GPIO.OUT)
GPIO.output(13, GPIO.HIGH)

def shutdown(self):
    GPIO.output(13, GPIO.HIGH)
    time.sleep(0.1)

def power(self):
    GPIO.output(13, GPIO.LOW)
    time.sleep(0.1)

def powercycle(self):
    self.shutdown()
    self.power()

async def _run_command(self, command):
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL)
    stdout, _ = await proc.communicate()
    return stdout

def program(self, hexfile='coin.hex'):
    # command = 'python3 test_programming.py program'
    command = 'openocd -c \"gdb_port disabled\" -c \"tcl_port disabled\" -c \"telnet_port disabled\" -f board.ocd -c \"program {} verify exit\"'
    self.powercycle()
    stdout = asyncio.run(self._run_command(command)).decode('utf8')
    self.shutdown()
    programmed = False
    verified = False

    for line in stdout.split('\n'):
        if '** Programming Finished **' in line:
            programmed = True
        elif '** Verified OK **' in line:
            verified = True

    #os.write(self.status_pipe,"Programmed: {} Verified: {}".format(programmed, verified).encode('utf8'))
    return programmed and verified

def check(self):
    # command = 'python3 test_programming.py check_unlocked'
    command = 'openocd -c \"gdb_port disabled\" -c \"tcl_port disabled\" -c \"telnet_port disabled\" -f board.ocd -f check_approtect.ocd'
    self.powercycle()
    stdout = asyncio.run(self._run_command(command)).decode('utf8')
    self.shutdown()
    chip_found = False
    locked = True

    for line in stdout.split('\n'):
        if 'nRF528' in line:
            chip_found = True
        if 'nRF52 device has no active AP Protection. :)' in line:
            locked = False
        if 'nRF52 device has active AP Protection. :/' in line:
            locked = True
            chip_found = True
    return chip_found, locked

def lock(self):
    self.powercycle()
    command = 'openocd -c \"gdb_port disabled\" -c \"tcl_port disabled\" -c \"telnet_port disabled\" -f board.ocd -f set_approtect.ocd'
    os.system(command)
    self.shutdown()

def unlock(self):
        self.powercycle()
        command = 'openocd -c \"gdb_port disabled\" -c \"tcl_port disabled\" -c \"telnet_port disabled\" -f board.ocd -f lift_approtect.ocd'
        os.system(command)
        self.shutdown()


def _test_oocdmgr():
    chip_found, locked = check()
    if chip_found and locked:
        print('found locked coin')
    elif chip_found and not locked:
        print('found unlocked coin')
    else:
        print('couldn\'t find coin')
    '''
    if program():
        print('programming succeeded')
    else:
        print('programming failed')
    '''

if __name__ == "__main__":
    _test_oocdmgr()
