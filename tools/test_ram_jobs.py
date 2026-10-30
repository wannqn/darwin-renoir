#!/usr/bin/env python3
"""Exercise real job generation against RAM root/cryptex availability and service admission."""
from pathlib import Path
import tempfile, subprocess, plistlib, os, sys
SCRIPT=Path(__file__).resolve().parents[1]/'userland/mkjobs.py'
with tempfile.TemporaryDirectory() as tmp:
    base=Path(tmp);root=base/'rootfs';dest=base/'jobs'
    jobs=root/'System/Library/LaunchDaemons';jobs.mkdir(parents=True)
    def job(label,program,present=True,cryptex=None):
        if present:
            f=(base/cryptex/program.split('/System/Cryptexes/'+('App' if cryptex=='cryptex-app' else 'OS')+'/')[-1]) if cryptex else root/program.lstrip('/')
            f.parent.mkdir(parents=True,exist_ok=True);f.touch()
        with (jobs/(label+'.plist')).open('wb') as f:
            plistlib.dump({'Label':label,'Program':program,'MachServices':{label:True},'KeepAlive':True,'RunAtLoad':True},f)
    job('com.apple.apsd','/usr/libexec/apsd')
    job('com.apple.cloudd','/usr/libexec/cloudd')
    job('com.apple.appstored','/usr/libexec/appstored')
    job('com.apple.mobileactivationd','/usr/libexec/mobileactivationd')
    job('com.apple.CommCenter','/usr/libexec/CommCenter')
    job('com.test.safari','/System/Cryptexes/App/usr/libexec/web-helper',cryptex='cryptex-app')
    job('com.test.os','/System/Cryptexes/OS/usr/libexec/os-helper',cryptex='cryptex')
    job('com.test.absent','/usr/libexec/not-in-image',False)
    job('com.test.absent-cryptex','/System/Cryptexes/App/usr/libexec/not-extracted',False)
    env=os.environ.copy();env.pop('ALLOW',None)
    subprocess.run([sys.executable,str(SCRIPT),'--rest',str(root),str(dest)],env=env,check=True,stdout=subprocess.DEVNULL)
    for label in ['com.apple.apsd','com.apple.cloudd','com.apple.appstored','com.apple.mobileactivationd','com.test.safari','com.test.os']:
        with (dest/(label+'.plist')).open('rb') as f:d=plistlib.load(f)
        assert d['MachServices'][label] and 'RunAtLoad' not in d and 'KeepAlive' not in d,label
    for label in ['com.apple.CommCenter','com.test.absent','com.test.absent-cryptex']:
        assert not (dest/(label+'.plist')).exists(),label
print('RAM jobs: present root and both cryptex services admitted on demand; absent binaries and modem excluded')
