#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install root-owned helper files and a system-wide application launcher."""
import argparse
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent

def install(source,directory,mode=0o644):
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/source.name
    shutil.copyfile(source,target)
    os.chmod(target,mode); os.chown(target,0,0)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--user',help='Local account allowed to control RGB without a password')
    args=parser.parse_args()
    if os.geteuid()!=0: parser.error('Run with sudo python3 install.py')
    user=args.user or os.environ.get('SUDO_USER')
    if not user and os.environ.get('PKEXEC_UID'):
        user=pwd.getpwuid(int(os.environ['PKEXEC_UID'])).pw_name
    if not user or pwd.getpwnam(user).pw_uid==0: parser.error('Specify a non-root local account with --user')
    app=Path('/usr/local/share/lancer-rgb'); helper=Path('/usr/local/lib/lancer-rgb')
    for name in ('lancer_rgb.py','lancer_service.py'): install(ROOT/name,helper)
    for name in ('lancer_gtk.py','lancer_rgb.py','color_widgets.py','style.css','README.md','LICENSE'):
        install(ROOT/name,app)
    install(ROOT/'lancer-rgb-control',Path('/usr/local/bin'),0o755)
    install(ROOT/'lancer-rgb.service',Path('/etc/systemd/system'))
    install(ROOT/'local.lancer.rgb.policy',Path('/usr/share/polkit-1/actions'))
    install(ROOT/'icons/hicolor/scalable/apps/local.lancer.RGB.svg',Path('/usr/local/share/icons/hicolor/scalable/apps'))
    install(ROOT/'local.lancer.RGB.desktop',Path('/usr/local/share/applications'))
    policy='''polkit.addRule(function(action, subject) {
    if (action.id === "local.lancer.rgb.control" &&
        subject.user === USER && subject.local && subject.active) {
        return polkit.Result.YES;
    }
});
'''.replace('USER',json.dumps(user))
    rules=Path('/etc/polkit-1/rules.d/49-lancer-rgb.rules')
    rules.write_text(policy); rules.chmod(0o644)
    modules=Path('/etc/modules-load.d/lancer-rgb.conf'); modules.write_text('i2c-dev\n'); modules.chmod(0o644)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','lancer-rgb.service'],check=True)
    print('Installed. Open Lancer RGB and save a color to enable restoration on subsequent boots.')

if __name__=='__main__': main()
