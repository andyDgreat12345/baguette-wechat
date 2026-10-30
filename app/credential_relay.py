"""Loopback DeepSeek relay: keep the existing provider key on the host Mac."""
from __future__ import annotations

import argparse
import http.client
import hmac
import json
import os
import secrets
import ssl
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import dotenv_values


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A bearer key must never follow a provider redirect to another origin.
        return None


def resolve_proxy(policy: str | None) -> str | None:
    """Re-read macOS routing for each call; never silently fall back to direct."""
    if not policy or policy == "direct":
        return None
    if policy == "system":
        getter = getattr(urllib.request, "getproxies_macosx_sysconf", urllib.request.getproxies)
        proxies = getter()
        policy = proxies.get("https") or proxies.get("http")
        if not policy:
            raise ValueError("System HTTP proxy is unavailable; direct fallback is disabled")
    target = urlsplit(policy)
    if (target.scheme != "http" or not target.hostname or not target.port
            or target.username or target.password or target.path not in {"", "/"}
            or target.query or target.fragment):
        raise ValueError("An HTTP CONNECT proxy without credentials is required")
    return policy


def provider_request(payload: dict, key: str, proxy: str | None,
                     timeout: float = 60) -> tuple[int, bytes]:
    """TLS terminates only at the fixed DeepSeek origin, including via CONNECT.

    http.client does not consult NO_PROXY, bypass lists or ambient proxy vars.
    No redirects are followed and no credential is sent in CONNECT headers.
    """
    context = ssl.create_default_context()
    if proxy:
        route = urlsplit(proxy)
        connection = http.client.HTTPSConnection(route.hostname, route.port,
                                                 timeout=timeout, context=context)
        connection.set_tunnel("api.deepseek.com", 443)
    else:
        connection = http.client.HTTPSConnection("api.deepseek.com", 443,
                                                 timeout=timeout, context=context)
    try:
        connection.request("POST", "/chat/completions",
                           body=json.dumps(payload).encode(),
                           headers={"Content-Type": "application/json",
                                    "Authorization": "Bearer " + key})
        response = connection.getresponse()
        content = response.read(16 * 1024 * 1024 + 1)
        if len(content) > 16 * 1024 * 1024:
            raise ValueError("Provider response exceeds size limit")
        return response.status, content
    finally:
        connection.close()


class Relay:
    def __init__(self, credential_file: Path, token_file: Path, proxy: str | None):
        self.credential_file = credential_file
        self.token_file = token_file
        self.token = token_file.read_text().strip() if token_file.exists() else secrets.token_urlsafe(40)
        token_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        token_file.write_text(self.token + "\n")
        token_file.chmod(0o600)
        self.proxy_policy = proxy or "direct"
        self.lock = threading.Lock()
        self.requests = 0
        self.last_status = None
        self.last_route = None

    def key(self) -> str:
        return str(dotenv_values(self.credential_file).get("DEEPSEEK_API_KEY") or "")

    def call(self, payload: dict) -> tuple[int, bytes]:
        key = self.key()
        if not key:
            return 503, b'{"error":{"message":"DeepSeek credential reference is unavailable"}}'
        if payload.get("model", "deepseek-flash") != "deepseek-flash":
            return 400, b'{"error":{"message":"This relay is configured for deepseek-flash"}}'
        payload["model"] = "deepseek-flash"
        payload["stream"] = False
        try:
            proxy = resolve_proxy(self.proxy_policy)
            self.last_route = proxy or "direct"
            status, content = provider_request(payload, key, proxy)
        except Exception as exc:
            status = 502
            content = json.dumps({"error": {"message": "DeepSeek connection failed", "type": type(exc).__name__}}).encode()
        with self.lock:
            self.requests += 1
            self.last_status = status
        return status, content


def handler_for(relay: Relay):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def output(self, status: int, content: bytes):
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def authorized(self) -> bool:
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + relay.token)

        def do_GET(self):
            if self.path != "/health":
                self.output(404, b'{}')
                return
            self.output(200, json.dumps({"configured": bool(relay.key()), "requests": relay.requests,
                                        "last_status": relay.last_status,
                                        "proxy_policy": relay.proxy_policy,
                                        "last_route": relay.last_route}).encode())

        def do_POST(self):
            if not self.authorized():
                self.output(401, b'{"error":"unauthorized"}')
                return
            if self.path not in ("/chat/completions", "/v1/chat/completions"):
                self.output(404, b'{}')
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16 * 1024 * 1024:
                    self.output(413, b'{"error":"request_size"}')
                    return
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
                    raise ValueError("messages required")
            except (ValueError, TypeError):
                self.output(400, b'{"error":"invalid_request"}')
                return
            self.output(*relay.call(payload))

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18764)
    parser.add_argument("--proxy", default="system")
    args = parser.parse_args()
    os.umask(0o077)
    relay = Relay(args.credential_file, args.token_file, args.proxy)
    print(json.dumps({"service": "DeepSeek credential relay", "listen": "127.0.0.1", "port": args.port, "configured": bool(relay.key())}), flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(relay)).serve_forever()


if __name__ == "__main__":
    main()
