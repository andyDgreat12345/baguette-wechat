"""Transport regressions use dummy keys and a real local CONNECT listener."""
import importlib.util
import os
from pathlib import Path
import socket
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'credential_relay', Path(__file__).parents[1] / 'app/credential_relay.py')
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)


class TransportTests(unittest.TestCase):
    def test_explicit_connect_ignores_no_proxy_and_keeps_key_inside_tls(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(3)
        received = []

        def proxy():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(3)
                request = b''
                while b'\r\n\r\n' not in request:
                    request += connection.recv(4096)
                received.append(request)
                connection.sendall(b'HTTP/1.1 502 Test proxy\r\nContent-Length: 0\r\n\r\n')

        worker = threading.Thread(target=proxy, daemon=True)
        worker.start()
        try:
            with patch.dict(os.environ, {'NO_PROXY': '*', 'no_proxy': '*',
                                        'HTTPS_PROXY': 'http://127.0.0.1:1'}):
                with self.assertRaises(OSError):
                    relay.provider_request({'messages': []}, 'dummy-private-key',
                                           'http://127.0.0.1:' + str(listener.getsockname()[1]), 3)
            worker.join(4)
            self.assertEqual(len(received), 1)
            self.assertTrue(received[0].startswith(b'CONNECT api.deepseek.com:443 HTTP/'))
            self.assertNotIn(b'dummy-private-key', received[0])
            self.assertNotIn(b'Authorization', received[0])
        finally:
            listener.close()

    def test_system_port_is_resolved_again_after_proxy_restart(self):
        with patch.object(relay.urllib.request, 'getproxies_macosx_sysconf', create=True,
                          side_effect=[{'https': 'http://127.0.0.1:58591'},
                                       {'https': 'http://127.0.0.1:58592'}]):
            self.assertEqual(relay.resolve_proxy('system'), 'http://127.0.0.1:58591')
            self.assertEqual(relay.resolve_proxy('system'), 'http://127.0.0.1:58592')

    def test_missing_system_proxy_does_not_fall_back_to_direct(self):
        with patch.object(relay.urllib.request, 'getproxies_macosx_sysconf',
                          create=True, return_value={}):
            with self.assertRaises(ValueError):
                relay.resolve_proxy('system')

    def test_proxy_url_rejects_credentials_and_non_http_routes(self):
        for value in ['http://user:secret@127.0.0.1:1234', 'https://127.0.0.1:1234',
                      'http://127.0.0.1:1234/path', 'not-a-url']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                relay.resolve_proxy(value)

if __name__ == '__main__':
    unittest.main()
