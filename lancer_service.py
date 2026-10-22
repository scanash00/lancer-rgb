#!/usr/bin/env python3
"""Privileged static-color helper; stores only successfully applied settings."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('lancer_protocol', ROOT / 'lancer_rgb.py')
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)
STATE = Path('/var/lib/lancer-rgb/settings.json')

def validate(state):
    if not isinstance(state, dict) or set(state) - {'0x71', '0x73'}:
        raise ValueError('Invalid saved controller addresses')
    for value in state.values():
        if not isinstance(value, dict) or set(value) != {'color', 'brightness'}:
            raise ValueError('Invalid saved settings')
        protocol.rgb(value['color'])
        if type(value['brightness']) is not int or not 0 <= value['brightness'] <= 100:
            raise ValueError('Invalid saved brightness')
    return state

def load():
    return validate(json.loads(STATE.read_text())) if STATE.exists() else {}

def save(state):
    validate(state)
    STATE.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.settings-', dir=STATE.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644)
        os.replace(name, STATE)
        directory=os.open(STATE.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)

def bus(wait=False):
    deadline=time.monotonic() + (15 if wait else 0)
    while True:
        candidates=[x['bus'] for x in protocol.inventory() if x['name'].startswith('SMBus I801 adapter')]
        if len(candidates)==1:
            protocol.check_host(candidates[0]); return candidates[0]
        if len(candidates)>1 or time.monotonic() >= deadline:
            raise RuntimeError('Expected exactly one I801 adapter; no writes attempted')
        time.sleep(0.5)  # Wait only for sysfs enumeration, never retry a bus write.

def update(color, brightness, address, persist=True):
    state=load()
    addresses=protocol.ADDRESSES if address=='both' else (int(address,16),)
    protocol.apply(bus(), protocol.plan(protocol.rgb(color), brightness, addresses))
    for item in addresses:
        state[hex(item)]={'color':color.upper(), 'brightness':brightness}
    if persist:
        save(state)

def restore():
    state=load()
    if not state:
        print('No saved colors; nothing to restore.'); return
    operations=[]
    for address, value in sorted(state.items()):
        operations.extend(protocol.plan(protocol.rgb(value['color']),value['brightness'],(int(address,16),)))
    protocol.apply(bus(wait=True), operations)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['restore','set','preview','read'])
    parser.add_argument('--color')
    parser.add_argument('--brightness',type=int,default=50)
    parser.add_argument('--address',choices=['both','0x71','0x73'],default='both')
    args=parser.parse_args()
    if os.geteuid()!=0: parser.error('Administrator authentication is required')
    if args.action in ('set','preview'):
        if args.color is None: parser.error('--color is required')
        protocol.rgb(args.color)
        if not 0<=args.brightness<=100: parser.error('Brightness must be 0..100')
    with open('/run/lock/lancer-rgb.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action=='restore': restore()
        elif args.action=='read': print(json.dumps(protocol.read_current(bus())))
        else: update(args.color,args.brightness,args.address,persist=args.action=='set')

if __name__=='__main__':
    try: main()
    except Exception as exc:
        import sys
        print(f'Lancer RGB: {exc}',file=sys.stderr); sys.exit(1)
