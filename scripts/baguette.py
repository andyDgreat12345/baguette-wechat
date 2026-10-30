#!/usr/bin/env python3
"""Local installer/control entry point. No secrets are printed."""
import argparse
import json
import os
import platform
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import urllib.request

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'app'))
from baguette_config import load_config
RUNTIME=BASE/'runtime'

def write_private(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(path.parent,0o700)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)

def run(args,dry=False,**kwargs):
    print(('PLAN ' if dry else 'RUN ')+shlex.join(map(str,args)),flush=True)
    if not dry:return subprocess.run(list(map(str,args)),check=True,**kwargs)

def init(args):
    if args.dry_run:
        print('PLAN create ignored runtime examples; no identity verification flags enabled');return
    RUNTIME.mkdir(exist_ok=True,mode=0o700);RUNTIME.chmod(0o700)
    for name in ('installation','controller-profile','settings'):
        target=RUNTIME/(name+'.json')
        if not target.exists():
            value=json.loads((BASE/'config'/(name+'.example.json')).read_text())
            if name=='settings':value['persona']=(BASE/'app/persona.txt').read_text()
            write_private(target,value)
    key=RUNTIME/'credentials.env'
    if not key.exists():shutil.copyfile(BASE/'config/credentials.example.env',key);key.chmod(0o600)
    print('Created examples in runtime/. Edit installation.json and credentials.env locally.')

def doctor(args):
    checks={'apple_silicon_macos':platform.system()=='Darwin' and platform.machine()=='arm64',
            'python_3_13_recommended':sys.version_info[:2]==(3,13),
            'git':bool(shutil.which('git')),'uv':bool(shutil.which('uv')),
            'tart':bool(shutil.which(load_config()['tart_binary'])),
            'ollama':bool(shutil.which('ollama')),'initialized':(RUNTIME/'installation.json').exists()}
    used=[]
    for port in (6186,8766,18764):
        with socket.socket() as s:
            s.settimeout(.2)
            if s.connect_ex(('127.0.0.1',port))==0:used.append(port)
    print(json.dumps({'checks':checks,'occupied_ports_do_not_kill':used,'coverage':'prerequisites only; not a live acceptance test'},indent=2))
    return 0 if all(checks.values()) else 1

def fetch(args):
    lock=json.loads((BASE/'UPSTREAMS.lock.json').read_text())
    for name,item in lock.items():
        dest=RUNTIME/'upstream'/name
        if not dest.exists():
            run(['git','clone','--filter=blob:none','--no-checkout',item['repository'],dest],args.dry_run)
        elif not args.dry_run:
            dirty=subprocess.check_output(['git','-C',str(dest),'status','--porcelain'],text=True)
            if dirty:raise RuntimeError('Upstream checkout has local edits: '+name)
        run(['git','-C',dest,'fetch','origin',item['commit']],args.dry_run)
        run(['git','-C',dest,'checkout','--detach',item['commit']],args.dry_run)
        if not args.dry_run:
            actual=subprocess.check_output(['git','-C',str(dest),'rev-parse','HEAD'],text=True).strip()
            if actual!=item['commit']:raise RuntimeError('Upstream revision mismatch: '+name)

def host_setup(args):
    if not shutil.which('uv') and not args.dry_run:raise RuntimeError('Install uv first; see INSTALL guide')
    run(['uv','venv','--python','3.13',BASE/'.venv'],args.dry_run)
    run(['uv','pip','install','--python',BASE/'.venv/bin/python','-r',BASE/'requirements.txt','-r',BASE/'requirements-brain.txt'],args.dry_run)
    for name in ('livingmemory','stealer'):
        req=RUNTIME/'upstream'/name/'requirements.txt'
        if not req.exists() and not args.dry_run:raise RuntimeError('Run fetch-upstreams before host-setup')
        run(['uv','pip','install','--python',BASE/'.venv/bin/python','-r',req],args.dry_run)
    # Install the exact pinned framework source, rather than silently following HEAD.
    run(['uv','pip','install','--python',BASE/'.venv/bin/python','--reinstall-package','astrbot',RUNTIME/'upstream/astrbot'],args.dry_run)

def vm_create(args):
    cfg=load_config();t=cfg['tart_binary'];name=cfg['vm_name']
    run([t,'clone',args.image,name],args.dry_run)
    run([t,'set',name,'--cpu','4','--memory','8192','--display','1280x800','--no-display-refit'],args.dry_run)
    print('Start separately: '+shlex.join([t,'run',name,'--no-clipboard','--no-audio','--no-usb-accessories']))

def guest_bundle(args):
    if args.dry_run:print('PLAN build runtime/guest-bundle.tar.gz from source + nonsecret identity config only');return
    stage=RUNTIME/'guest-bundle'
    if stage.exists():raise RuntimeError('Bundle staging already exists; choose a fresh runtime or move it aside')
    stage.mkdir(parents=True)
    for directory in ('app','vm'):
        shutil.copytree(BASE/directory,stage/directory,ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(BASE/'requirements.txt',stage/'requirements.txt')
    (stage/'runtime').mkdir()
    cfg=load_config();safe={k:cfg[k] for k in ('bot_id','owner_id','owner_chat','group_chats','vm_name')}
    write_private(stage/'runtime/installation.json',safe)
    (stage/'scripts').mkdir()
    for name in ('bind_guest.py','calibrate_stickers.py'):
        shutil.copyfile(BASE/'scripts'/name,stage/'scripts'/name)
    shutil.copyfile(BASE/'scripts/setup-guest.zsh',stage/'setup-guest.zsh')
    with tarfile.open(RUNTIME/'guest-bundle.tar.gz','w:gz') as archive:archive.add(stage,arcname='baguette')
    print('Built runtime/guest-bundle.tar.gz. Transfer only this bundle to the guest; it contains no API credential.')

def http(path,body=None,port=8766,token=None,method=None):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers=headers,method=method)
    with opener.open(req,timeout=180) as r:return json.load(r)

def controller(args):
    if args.action=='status':
        value=http('/api/status');print(json.dumps({k:value.get(k) for k in ('state','enabled','deepseek','last_error','blockers')},ensure_ascii=False,indent=2));return
    if args.action in {'pause','enable','check-model'}:
        route={'pause':'pause','enable':'start','check-model':'check-model'}[args.action]
        if args.dry_run:print('PLAN POST /api/'+route);return
        value=http('/api/'+route,{'catch_up':args.catch_up} if args.action=='enable' else {})
        print(json.dumps({k:value.get(k) for k in ('state','enabled','deepseek','last_error','blockers')},ensure_ascii=False,indent=2));return
    if args.action=='start':run([BASE/'.venv/bin/python',BASE/'app/launch_controller.py'],args.dry_run)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true',help='Plan mutations without performing them')
    sub=parser.add_subparsers(dest='action',required=True)
    for name in ('init','doctor','fetch-upstreams','host-setup','guest-bundle','start','pause','enable','status','check-model'):sub.add_parser(name)
    vm=sub.add_parser('vm-create');vm.add_argument('--image',default='ghcr.io/cirruslabs/macos-tahoe-base:latest')
    sub.choices['enable'].add_argument('--catch-up',action='store_true',help='Use only after reviewing an existing baseline')
    a=parser.parse_args();os.umask(0o077)
    try:
        handlers={'init':init,'doctor':doctor,'fetch-upstreams':fetch,'host-setup':host_setup,'vm-create':vm_create,'guest-bundle':guest_bundle}
        return (handlers.get(a.action,controller)(a) or 0)
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError) as e:
        print('ERROR '+str(e),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
