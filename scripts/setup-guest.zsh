#!/bin/zsh
set -euo pipefail
# Run only inside the dedicated, logged-in virtual Mac.
[[ "$(/usr/sbin/sysctl -n hw.model)" == VirtualMac* && "$EUID" != 0 ]] || { print -u2 'Run inside the logged-in VM as a normal user.'; exit 1; }
command -v uv >/dev/null || { print -u2 'Install uv inside this VM first; see the guide.'; exit 1; }
[[ "$PWD" == "$HOME/baguette" ]] || { print -u2 'Extract the bundle to ~/baguette and cd there first.'; exit 1; }
umask 077
mkdir -p runtime bin
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python - <<'PY'
from pathlib import Path
import json,platform
p=Path('runtime/guest-attestation.json');p.write_text(json.dumps({'isolated_guest':True,'platform':platform.platform()}));p.chmod(0o600)
PY
archive=runtime/tart-guest-agent-v0.15.0.tar.gz
curl --fail --location --proto '=https' --tlsv1.2 'https://github.com/openai/tart-guest-agent/releases/download/v0.15.0/tart-guest-agent-darwin-all.tar.gz' -o "$archive"
print 'eb47f402f18e742a8ea96344115ca776179f9c4c67494bc0c46a10a68db280b7  '$archive | shasum -a 256 -c -
mkdir -p runtime/agent-unpack
tar -xzf "$archive" -C runtime/agent-unpack
agent_path="$(find runtime/agent-unpack -type f -name tart-guest-agent | head -1)"
[[ -n "$agent_path" ]] || { print -u2 'Guest-agent archive layout changed.'; exit 1; }
cp "$agent_path" bin/tart-guest-agent
print '8bbbffe09d207164cbabc06a2b2f5085e041290e75247d28db0a0e1fa852646e  bin/tart-guest-agent' | shasum -a 256 -c -
chmod 755 bin/tart-guest-agent
mkdir -p "$HOME/Applications/Baguette.app/Contents/MacOS"
clang -fobjc-arc -framework Cocoa -framework ApplicationServices -framework CoreGraphics vm/native-launcher.m -o "$HOME/Applications/Baguette.app/Contents/MacOS/Baguette"
.venv/bin/python - <<'PY'
from pathlib import Path
import plistlib
p=Path.home()/'Applications/Baguette.app/Contents/Info.plist'
p.write_bytes(plistlib.dumps({'CFBundleIdentifier':'io.baguette.wechat.guest','CFBundleName':'Baguette','CFBundleExecutable':'Baguette','CFBundlePackageType':'APPL','CFBundleVersion':'1','LSMinimumSystemVersion':'13.0'}))
PY
chmod 755 vm/guest-agent-launcher.zsh
codesign --force --deep --sign - "$HOME/Applications/Baguette.app"
print 'Guest installed. Open Baguette.app, grant guest permissions, then log in to the dedicated WeChat account.'
open "$HOME/Applications/Baguette.app"
