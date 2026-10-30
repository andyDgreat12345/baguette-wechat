"""Keep the owned host listener alive; preserve the controller's run/pause intent."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import time
BASE=Path(__file__).resolve().parents[1]
RUNTIME=BASE/'runtime'

def listeners():
    r=subprocess.run(['/usr/sbin/lsof','-nP','-tiTCP:8766','-sTCP:LISTEN'],capture_output=True,text=True)
    return [int(v) for v in r.stdout.split()]

def owned(pid):
    r=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
    return str(BASE/'app/companion.py') in r.stdout or str(BASE/'app/launch_controller.py') in r.stdout

def main():
    import fcntl
    lock=(RUNTIME/'controller-supervisor.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    (RUNTIME/'supervisor.pid').write_text(str(os.getpid()))
    while True:
        current=listeners()
        if current and not all(owned(p) for p in current):
            print('Port 8766 belongs to another application; supervisor stopped',flush=True);return
        if not current:
            with (RUNTIME/'controller.log').open('a') as log:
                child=subprocess.Popen([sys.executable,str(BASE/'app/launch_controller.py')],cwd=BASE,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            (RUNTIME/'controller.pid').write_text(str(child.pid))
            print('Restarted owned controller '+str(child.pid),flush=True)
            time.sleep(4)
        time.sleep(3)
if __name__=='__main__':main()
