#!/usr/bin/env python3
"""Experimental CLI for the captured XPG Lancer Blade pair. Dry-run by default.
No detection probes, SPD access, address assignment, or firmware persistence.
Only the already initialized static-color sequence has been observed.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import sys
import time

ADDRESSES = (0x71, 0x73)
BOARD = 'B760 DS3H WIFI6E GEN5'
I2C_SLAVE, I2C_FUNCS, I2C_SMBUS = 0x0703, 0x0705, 0x0720
REQUIRED_FUNCS = 0x00100000 | 0x00400000  # WRITE_BYTE_DATA | WRITE_WORD_DATA

class Data(ctypes.Union):
    _fields_ = [('byte', ctypes.c_uint8), ('word', ctypes.c_uint16),
                ('block', ctypes.c_uint8 * 34)]

class Request(ctypes.Structure):
    _fields_ = [('read_write', ctypes.c_uint8), ('command', ctypes.c_uint8),
                ('size', ctypes.c_uint32), ('data', ctypes.POINTER(Data))]

def rgb(text):
    text = text.removeprefix('#')
    if not re.fullmatch(r'[0-9a-fA-F]{6}', text):
        raise argparse.ArgumentTypeError('Use six hex digits, e.g. FF0000')
    return tuple(int(text[i:i+2], 16) for i in (0, 2, 4))

def plan(color, brightness=50, addresses=ADDRESSES):
    # Match JavaScript Math.round for nonnegative values, without bankers rounding.
    r,g,b = ((x * brightness + 50) // 100 for x in color)
    operations=[]
    for address in addresses:
        for register, values in ((0x8160, [r,b,g]*8),
                                 (0x8020, [0,1,0,0]),
                                 (0x8029, [9]), (0x802f, [1])):
            # CTI word API takes register order; Linux SMBus sends low byte first.
            swapped = ((register & 255) << 8) | (register >> 8)
            operations.append(dict(address=address, kind='word', command=0,
                                   value=swapped, register=register))
            operations.extend(dict(address=address, kind='byte', command=1,
                                   value=value) for value in values)
    return operations

def inventory():
    return [dict(bus=int(p.parent.name.split('-')[-1]), name=p.read_text().strip())
            for p in sorted(Path('/sys/class/i2c-dev').glob('i2c-*/name'))]

def check_host(bus):
    if sys.platform != 'linux':
        raise RuntimeError('Hardware access is Linux-only; dry-run works here.')
    board=Path('/sys/class/dmi/id/board_name').read_text().strip()
    if board != BOARD:
        raise RuntimeError('Board does not match captured setup: '+board)
    name=Path(f'/sys/class/i2c-dev/i2c-{bus}/name').read_text().strip()
    if not name.startswith('SMBus I801 adapter'):
        raise RuntimeError('Selected bus is not an Intel I801 adapter: '+name)

def apply(bus, operations):
    check_host(bus)
    import fcntl
    libc=ctypes.CDLL(None, use_errno=True)
    ioctl=libc.ioctl
    ioctl.restype=ctypes.c_int
    ioctl.argtypes=[ctypes.c_int,ctypes.c_ulong] # variadic third argument
    def checked(fd, request, argument):
        if ioctl(fd, request, argument) < 0:
            code=ctypes.get_errno()
            raise OSError(code, os.strerror(code))
    fd=os.open(f'/dev/i2c-{bus}', os.O_RDWR | os.O_CLOEXEC)
    completed=0
    try:
        # Advisory lock coordinates instances of this CLI only.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        funcs=ctypes.c_ulong()
        checked(fd, I2C_FUNCS, ctypes.byref(funcs))
        if funcs.value & REQUIRED_FUNCS != REQUIRED_FUNCS:
            raise RuntimeError('Adapter lacks required SMBus write operations.')
        # Preflight ownership for BOTH addresses before any data transaction.
        for address in sorted({op['address'] for op in operations}):
            checked(fd, I2C_SLAVE, ctypes.c_ulong(address))
        selected=None
        for op in operations:
            if selected != op['address']:
                checked(fd, I2C_SLAVE, ctypes.c_ulong(op['address']))
                selected=op['address']
            data=Data()
            if op['kind']=='word':data.word=op['value'];size=3
            else:data.byte=op['value'];size=2
            req=Request(0,op['command'],size,ctypes.pointer(data))
            checked(fd,I2C_SMBUS,ctypes.byref(req))
            completed+=1
            time.sleep(0.001)
    except Exception as exc:
        raise RuntimeError(f'Stopped after {completed} writes; no retry or rollback: {exc}') from exc
    finally:
        os.close(fd)
    print(f'Completed {completed} writes. Confirm the physical colors.')

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list-buses',action='store_true',help='Read sysfs names only; no bus scan')
    parser.add_argument('--bus',type=int,help='Current I801 bus number; never assumed to be 6')
    parser.add_argument('--color',type=rgb,help='Static RRGGBB; 000000 means LEDs off')
    parser.add_argument('--brightness',type=int,default=50,help='0..100 percent; captured tests used 50')
    parser.add_argument('--address',choices=['both','0x71','0x73'],default='both',help='Physical slot mapping is unconfirmed')
    parser.add_argument('--apply',action='store_true',help='Write the displayed experimental sequence')
    args=parser.parse_args(argv)
    if args.list_buses:
        if args.apply or args.color:parser.error('--list-buses cannot change colors')
        print(json.dumps(inventory(),indent=2));return 0
    if args.color is None:parser.error('--color is required')
    if not 0 <= args.brightness <= 100:parser.error('--brightness must be 0..100')
    if args.bus is not None and args.bus < 0:parser.error('--bus must be nonnegative')
    addresses=ADDRESSES if args.address=='both' else (int(args.address,16),)
    operations=plan(args.color,args.brightness,addresses)
    print(json.dumps({'experimental':True,'apply':args.apply,'bus':args.bus,
                     'operations':operations},indent=2),flush=True)
    if args.apply:
        if args.bus is None:parser.error('--apply requires an explicit --bus')
        apply(args.bus,operations)
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,RuntimeError) as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)


def decode_snapshot(read_register):
    """Read only the captured static buffer and its two mode bytes."""
    result = {}
    for address in ADDRESSES:
        direct = read_register(address, 0x8020)
        mode = read_register(address, 0x8021)
        raw = [read_register(address, 0x8160 + i) for i in range(24)]
        colors = ['%02X%02X%02X' % (raw[i], raw[i+2], raw[i+1]) for i in range(0, 24, 3)]
        result[hex(address)] = dict(colors=colors, mode=mode, direct=direct,
                                   static=(direct == 0 and mode == 1))
    return result


def read_current(bus):
    """ENE pointer selection followed by byte reads; no RGB data writes."""
    import fcntl
    check_host(bus)
    ioctl = ctypes.CDLL(None, use_errno=True).ioctl
    ioctl.restype = ctypes.c_int
    ioctl.argtypes = [ctypes.c_int, ctypes.c_ulong]
    def checked(fd, request, argument):
        if ioctl(fd, request, argument) < 0:
            code=ctypes.get_errno()
            raise OSError(code, os.strerror(code))
    fd=os.open(f'/dev/i2c-{bus}', os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        funcs=ctypes.c_ulong()
        checked(fd, I2C_FUNCS, ctypes.byref(funcs))
        required=0x00400000 | 0x00080000  # WRITE_WORD_DATA | READ_BYTE_DATA
        if funcs.value & required != required:
            raise RuntimeError('Adapter lacks required register-read operations')
        for address in ADDRESSES:
            checked(fd,I2C_SLAVE,ctypes.c_ulong(address))
        def read_register(address, register):
            checked(fd,I2C_SLAVE,ctypes.c_ulong(address))
            data=Data(); data.word=((register & 255)<<8) | (register>>8)
            req=Request(0,0,3,ctypes.pointer(data))
            checked(fd,I2C_SMBUS,ctypes.byref(req))
            req=Request(1,0x81,2,ctypes.pointer(data))
            checked(fd,I2C_SMBUS,ctypes.byref(req))
            return data.byte
        return decode_snapshot(read_register)
    finally:
        os.close(fd)
