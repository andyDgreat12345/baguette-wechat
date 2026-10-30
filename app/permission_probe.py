"""Permission preflight; --request is intended only inside the bot VM."""
import argparse
import json
import platform
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", action="store_true")
    args = parser.parse_args()
    from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

    if args.request:
        attestation = Path.home() / "baguette/runtime/guest-attestation.json"
        if not attestation.exists() or not json.loads(attestation.read_text()).get("isolated_guest"):
            raise SystemExit("Permission prompts are only enabled in the configured guest desktop")
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        if not CGPreflightScreenCaptureAccess():
            CGRequestScreenCaptureAccess()
    print(json.dumps({"accessibility": bool(AXIsProcessTrusted()),
                      "screen_capture": bool(CGPreflightScreenCaptureAccess()),
                      "macos": platform.mac_ver()[0]}))


if __name__ == "__main__":
    main()
