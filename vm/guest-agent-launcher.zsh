#!/bin/zsh
# Pure guest RPC supervision. Native AppKit UI owns permission requests.
set -eu
umask 077

# These helpers can be sourced for lifecycle tests; sourcing never starts RPC.
baguette_lifecycle() {
  "$task_python" - "$@" <<'PY'
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

def inspect(pid, executable, command):
    try:
        pid = int(pid)
        if pid <= 1:
            return None
        library = ctypes.CDLL('/usr/lib/libproc.dylib')
        library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        library.proc_pidpath.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(4096)
        if library.proc_pidpath(pid, buffer, len(buffer)) <= 0:
            return None
        actual = os.path.realpath(os.fsdecode(buffer.value))
        if actual != os.path.realpath(executable):
            return None
        line = subprocess.check_output(
            ['/bin/ps', '-ww', '-p', str(pid), '-o', 'uid=', '-o', 'ppid=',
             '-o', 'lstart=', '-o', 'command='], text=True, stderr=subprocess.DEVNULL).strip()
        fields = line.split(None, 7)
        if len(fields) != 8 or int(fields[0]) != os.getuid() or fields[7] != command:
            return None
        return {'pid': pid, 'uid': int(fields[0]), 'ppid': int(fields[1]),
                'executable': actual, 'started': ' '.join(fields[2:7]), 'command': fields[7]}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None

def current(record):
    if record.get('uid') != os.getuid():
        return None
    found = inspect(record.get('pid'), record.get('executable', ''), record.get('command', ''))
    return found if found == record else None

def atomic(path, text):
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

action = sys.argv[1]
if action == 'inspect':
    record = inspect(sys.argv[2], sys.argv[3], sys.argv[4])
    if record is None:
        raise SystemExit(1)
    print(json.dumps(record))
elif action == 'stop':
    record, timeout = json.loads(sys.argv[2]), float(sys.argv[3])
    if not 0.1 <= timeout <= 15:
        raise SystemExit(1)
    if current(record) is None:
        print('Recorded child is gone or identity changed; no signal sent.')
        raise SystemExit(0)
    try:
        os.kill(record['pid'], signal.SIGTERM)
    except ProcessLookupError:
        raise SystemExit(0)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if current(record) is None:
            raise SystemExit(0)
        time.sleep(.1)
    if current(record) is not None:
        try:
            os.kill(record['pid'], signal.SIGKILL)
        except ProcessLookupError:
            raise SystemExit(0)
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if current(record) is None:
            raise SystemExit(0)
        time.sleep(.05)
    print('Owned child did not stop; retaining its metadata for recovery.')
    raise SystemExit(1)
elif action == 'publish':
    root, generation = Path(sys.argv[2]), sys.argv[3]
    launcher, agent = json.loads(sys.argv[4]), json.loads(sys.argv[5])
    owner = {'generation': generation, 'launcher': launcher, 'agent': agent,
             'state': 'running' if agent else 'starting'}
    atomic(root / 'guest-agent-owner.json', json.dumps(owner) + '\n')
    atomic(root / 'guest-agent-launcher.pid', str(launcher['pid']) + '\n')
    if agent:
        atomic(root / 'guest-agent.pid', str(agent['pid']) + '\n')
elif action == 'cleanup':
    root, generation = Path(sys.argv[2]), sys.argv[3]
    launcher_pid, child_pid = sys.argv[4], sys.argv[5]
    owner_path = root / 'guest-agent-owner.json'
    try:
        owner = json.loads(owner_path.read_text())
    except (OSError, ValueError):
        raise SystemExit(0)
    if owner.get('generation') != generation or str(owner.get('launcher', {}).get('pid')) != launcher_pid:
        raise SystemExit(0)
    for name, pid in [('guest-agent-launcher.pid', launcher_pid), ('guest-agent.pid', child_pid)]:
        path = root / name
        try:
            if pid and path.read_text().strip() == pid:
                path.unlink()
        except OSError:
            pass
    owner_path.unlink(missing_ok=True)
else:
    raise SystemExit(2)
PY
}

baguette_acquire_lock() {
  zmodload zsh/system
  # Persistent inode: never remove or redirect to this file after locking it.
  : >> "$1"
  zsystem flock -t 0 -f task_lock_fd "$1"
}

baguette_cleanup() {
  [[ "${task_cleaning:-0}" == 0 ]] || return 0
  task_cleaning=1
  trap '' INT TERM
  local task_stopped=1
  if [[ -n "${task_child_identity:-}" ]]; then
    if ! baguette_lifecycle stop "$task_child_identity" 5; then task_stopped=0; fi
    if [[ "$task_stopped" == 1 ]]; then
      wait "$task_child_pid" 2>/dev/null || true
    fi
  elif [[ -n "${task_child_pid:-}" ]] && kill -0 "$task_child_pid" 2>/dev/null; then
    print "Unverified child is still live; preserving recovery metadata without signalling it."
    task_stopped=0
  fi
  if [[ "$task_stopped" == 1 ]]; then
    baguette_lifecycle cleanup "$task_runtime" "$task_generation" "$$" "$task_child_pid" || true
  fi
  if [[ -n "${task_lock_fd:-}" ]]; then zsystem flock -u "$task_lock_fd" || true; fi
}

baguette_main() {
  local task_model="$(/usr/sbin/sysctl -n hw.model)"
  if [[ "$task_model" != VirtualMac* || "$EUID" == 0 ]]; then
    print -u2 "Refusing guest RPC supervision outside a logged-in virtual Mac user."
    return 1
  fi
  typeset -g task_guest_dir="$HOME/baguette"
  typeset -g task_runtime="$task_guest_dir/runtime"
  typeset -g task_python="$task_guest_dir/.venv/bin/python"
  cd "$task_guest_dir"
  if [[ ! -f "$task_runtime/guest-attestation.json" || ! -x "$task_python" || ! -x bin/tart-guest-agent ]]; then
    print -u2 "Run the guest installer first."
    return 1
  fi
  mkdir -p "$task_runtime"
  exec >> "$task_runtime/guest-agent.log" 2>&1
  unset DEEPSEEK_API_KEY DEEPSEEK_BASE_URL COMPANION_ADMIN_TOKEN 2>/dev/null || true
  typeset -g task_lock_fd=""
  if ! baguette_acquire_lock "$task_runtime/guest-agent.supervisor.lock"; then
    print "Another supervisor holds the kernel lock; no duplicate started."
    return 0
  fi
  local task_agent="$task_guest_dir/bin/tart-guest-agent"
  local task_script="$task_guest_dir/guest-agent-launcher.zsh"
  local task_existing_pid=""
  # Legacy mkdir-lock versions are checked by exact live identity, never raw PID.
  if [[ -f "$task_runtime/guest-agent.pid" ]]; then
    task_existing_pid="$(<"$task_runtime/guest-agent.pid")"
    if baguette_lifecycle inspect "$task_existing_pid" "$task_agent" "$task_agent --run-rpc" >/dev/null; then
      print "Verified own RPC agent already runs; no duplicate started."
      return 0
    fi
  fi
  if [[ -f "$task_runtime/guest-agent-launcher.pid" ]]; then
    task_existing_pid="$(<"$task_runtime/guest-agent-launcher.pid")"
    if [[ "$task_existing_pid" != "$$" ]] && baguette_lifecycle inspect "$task_existing_pid" /bin/zsh "/bin/zsh $task_script" >/dev/null; then
      print "Verified own legacy supervisor is still running; no duplicate started."
      return 0
    fi
  fi
  typeset -g task_generation="$("$task_python" -c 'import secrets; print(secrets.token_hex(16))')"
  typeset -g task_launcher_identity="$(baguette_lifecycle inspect "$$" /bin/zsh "/bin/zsh $task_script")"
  typeset -g task_child_pid=""
  typeset -g task_child_identity=""
  typeset -g task_cleaning=0
  trap baguette_cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  baguette_lifecycle publish "$task_runtime" "$task_generation" "$task_launcher_identity" null
  # RPC starts without any permission requests, so denied TCC cannot block repair.
  "$task_agent" --run-rpc &
  task_child_pid="$!"
  print -r -- "$task_child_pid" > "$task_runtime/guest-agent.pid"
  local task_attempt
  for task_attempt in {1..20}; do
    if task_child_identity="$(baguette_lifecycle inspect "$task_child_pid" "$task_agent" "$task_agent --run-rpc")"; then break; fi
    sleep .05
  done
  if [[ -z "$task_child_identity" ]]; then
    print "RPC child did not establish the expected executable/UID/command identity."
    return 1
  fi
  baguette_lifecycle publish "$task_runtime" "$task_generation" "$task_launcher_identity" "$task_child_identity"
  wait "$task_child_pid"
}

if [[ "$ZSH_EVAL_CONTEXT" == toplevel ]]; then
  baguette_main "$@"
fi
