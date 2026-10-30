"""Host control panel; every WeChat UI command is routed into the named VM."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit
from baguette_config import load_config

BASE = Path(__file__).resolve().parent.parent
RUNTIME = BASE / "runtime"


def relay_command() -> list[str]:
    """Follow the active system proxy unless explicitly configured otherwise."""
    command = [sys.executable, str(BASE / "app/credential_relay.py"),
               "--credential-file", str(RUNTIME / "credentials.env"),
               "--token-file", str(RUNTIME / "relay-token")]
    proxy = os.environ.get("BAGUETTE_UPSTREAM_PROXY", load_config()["proxy"]).strip() or load_config()["proxy"]
    if proxy not in {"system", "direct"}:
        parsed = urlsplit(proxy)
        if parsed.scheme != "http" or not parsed.hostname or not parsed.port or parsed.username or parsed.password:
            raise ValueError("BAGUETTE_UPSTREAM_PROXY must be system, direct or an HTTP CONNECT proxy URL")
    command.extend(["--proxy", proxy])
    return command


def relay_ready() -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:18764/health", timeout=2) as response:
            return json.load(response).get("configured") is True
    except Exception:
        return False


def adapter_filename(profile: dict) -> str:
    mode = profile.get('adapter_mode', 'ax')
    if mode not in {'ax', 'visual'}:
        raise ValueError('Unknown guest adapter mode; no fallback to the physical Mac')
    return 'visual_adapter.py' if mode == 'visual' else 'guest_adapter.py'


def main():
    os.umask(0o077)
    RUNTIME.mkdir(exist_ok=True)
    if not relay_ready():
        with (RUNTIME / "relay.log").open("a") as log:
            subprocess.Popen(
                relay_command(),
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
        for _ in range(20):
            if relay_ready():
                break
            time.sleep(.25)
    profile_file = RUNTIME / "controller-profile.json"
    if not profile_file.exists():
        profile_file.write_text(json.dumps({"guest_adapter_verified": False,
                                           "spare_account_verified": False,
                                           "adapter_mode": "visual", "model_backend": "astrbot"}, indent=2) + "\n")
        profile_file.chmod(0o600)
    profile = json.loads(profile_file.read_text())
    if profile.get("model_backend") == "astrbot":
        auth_file = Path(profile.get("astrbot_auth_file", str(RUNTIME / "brain/auth.json")))
        if not auth_file.is_file():
            raise RuntimeError("Configured AstrBot credentials are unavailable; no fallback")
        os.environ["COMPANION_ASTRBOT_AUTH_FILE"] = str(auth_file)
    if profile.get('auto_resume_on_restart') is True:
        os.environ['COMPANION_AUTO_RESUME']='1'
    os.environ['COMPANION_GROUP_PARTICIPATION']=profile.get('group_participation',load_config().get('group_participation','directed'))
    adapter_name = adapter_filename(profile)
    tart = load_config()["tart_binary"]
    prefix = [str(tart), "exec", "-i", load_config()["vm_name"], "/bin/zsh", "-c",
              'exec "$HOME/baguette/.venv/bin/python" "$HOME/baguette/app/' + adapter_name + '" "$@"',
              "guest-adapter"]
    if load_config().get("tart_home"):
        os.environ["TART_HOME"] = str(Path(load_config()["tart_home"]).expanduser())
    os.environ["TART_NO_AUTO_PRUNE"] = "1"
    os.environ["COMPANION_ADAPTER_COMMAND_JSON"] = json.dumps(prefix)
    os.environ["COMPANION_ISOLATION_READY"] = "1" if profile.get("guest_adapter_verified") is True else "0"
    os.environ["COMPANION_SPARE_ACCOUNT_VERIFIED"] = "1" if profile.get("spare_account_verified") is True else "0"
    os.environ["DEEPSEEK_BASE_URL"] = "http://127.0.0.1:18764/v1"
    os.environ["DEEPSEEK_MODEL"] = load_config()["deepseek_model"]
    token = RUNTIME / "relay-token"
    os.environ["DEEPSEEK_API_KEY"] = token.read_text().strip() if token.exists() else ""
    command = [sys.executable, str(BASE / "app/companion.py"),
               "--data-dir", str(RUNTIME / "controller-data")]
    if not (RUNTIME / "controller-data/settings.json").exists():
        command.extend(["--config", str(RUNTIME / "settings.json")])
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
