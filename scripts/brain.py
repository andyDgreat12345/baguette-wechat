"""Own-process AstrBot/relay service controls and persona API initialization."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE/'scripts'));sys.path.insert(0,str(BASE/'app'))
from baguette import http
from launch_controller import relay_command
R=BASE/'runtime';B=R/'brain';I=B/'instance'

def pids(port):
 r=subprocess.run(['/usr/sbin/lsof','-nP','-tiTCP:'+str(port),'-sTCP:LISTEN'],capture_output=True,text=True);return {int(x) for x in r.stdout.split()}

def start():
 env=dict(os.environ,PYTHONPATH=str(BASE/'app'),ASTRBOT_ROOT=str(I),NO_PROXY='127.0.0.1,localhost',no_proxy='127.0.0.1,localhost')
 for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):env.pop(k,None)
 commands={'relay':(18764,relay_command(),BASE),'astrbot':(6186,[BASE/'.venv/bin/astrbot','run','-p','6186'],I)}
 for name,(port,cmd,cwd) in commands.items():
  pidfile=B/(name+'.pid');active=pids(port)
  if active:
   if not pidfile.exists() or int(pidfile.read_text()) not in active:raise RuntimeError(f'Port {port} belongs to another process; will not replace it')
   continue
  with (B/(name+'.log')).open('a') as log:p=subprocess.Popen(list(map(str,cmd)),cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  pidfile.write_text(str(p.pid))
  for _ in range(150):
   if p.poll() is not None:raise RuntimeError(name+' exited; inspect its private log')
   if p.pid in pids(port):break
   time.sleep(.2)
  else:raise RuntimeError(name+' did not start')
 print('Private brain listening on 127.0.0.1:6186. Ollama must be running separately.')

def stop():
 for name,port in [('astrbot',6186),('relay',18764)]:
  f=B/(name+'.pid')
  if not f.exists():continue
  pid=int(f.read_text())
  if pid not in pids(port):continue
  cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
  expected=str(BASE/'.venv/bin/astrbot') if name=='astrbot' else str(BASE/'app/credential_relay.py')
  if expected not in cmd:raise RuntimeError('PID identity changed; refusing to stop')
  os.kill(pid,signal.SIGTERM)
 print('Stopped owned brain services; Ollama and WeChat unchanged.')

def persona():
 auth=json.loads((B/'auth.json').read_text());login=http('/api/auth/login',auth,port=6186)
 if login.get('status')!='ok':raise RuntimeError('Authentication failed; credentials not printed')
 token=login['data']['token'];pid='baguette_qq_wechat'
 prompt=(BASE/'resources/persona/dafeiyu-original.md').read_text()+'\n\n'+(BASE/'resources/persona/wechat-overlay.zh-CN.txt').read_text()
 payload={'persona_id':pid,'system_prompt':prompt,'begin_dialogs':[],'tools':['memorize_long_term_memory','recall_long_term_memory','select_wechat_sticker'],'skills':[]}
 # Read before write; never overwrite an existing configured persona implicitly.
 values=http('/api/v1/personas',port=6186,token=token)
 data=values.get('data',[]);items=data if isinstance(data,list) else data.get('personas',[])
 if any(p.get('persona_id')==pid for p in items):print('Persona already exists; update deliberately via dashboard API.');return
 result=http('/api/v1/personas',payload,port=6186,token=token)
 if result.get('status')!='ok':raise RuntimeError('Persona API did not confirm creation')
 print('Persona created through AstrBot API; original memory tool scope preserved.')

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('action',choices=['start','stop','install-persona']);args=a.parse_args();os.umask(0o077)
 {'start':start,'stop':stop,'install-persona':persona}[args.action]()
if __name__=='__main__':main()
