import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

import rede


class NetworkTests(unittest.TestCase):
    def test_dashboard_requires_healthy_emqx_response(self):
        class Handler(BaseHTTPRequestHandler):
            code = 200
            body = b'Node emqx@test is started\nemqx is running'
            def do_GET(self):
                self.send_response(self.code)
                self.end_headers()
                self.wfile.write(self.body)
            def log_message(self, *args):
                pass
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                self.assertTrue(rede.dashboard_probe('127.0.0.1', server.server_port))
                Handler.code = 503
                self.assertFalse(rede.dashboard_probe('127.0.0.1', server.server_port))
                Handler.code, Handler.body = 200, b'<html>ordinary website</html>'
                self.assertFalse(rede.dashboard_probe('127.0.0.1', server.server_port))
            finally:
                server.shutdown()
                thread.join(2)

    def test_prefers_real_gateway_and_excludes_unusable_ips(self):
        records = [{'ip': '172.20.80.1', 'name': 'vEthernet', 'gateway': False},
                   {'ip': '192.168.1.10', 'name': 'Wi-Fi', 'gateway': True},
                   {'ip': '127.0.0.1'}, {'ip': '169.254.2.1'}, {'ip': '::1'}, {'ip': '0.0.0.0'}]
        found = rede.parse_interfaces(records)
        self.assertEqual([x.ip for x in found], ['192.168.1.10', '172.20.80.1'])

    def test_powershell_single_object(self):
        self.assertEqual(rede.parse_interfaces({'ip': '10.0.0.8', 'name': 'Ethernet'})[0].ip, '10.0.0.8')

    def test_mqtt_reply_can_be_fragmented_and_refuse_credentials(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            received = []
            def respond():
                with server.accept()[0] as client:
                    received.append(client.recv(256))
                    client.sendall(b'\x20\x02')
                    client.sendall(b'\x00\x05')
            thread = threading.Thread(target=respond)
            thread.start()
            result = rede.mqtt_probe('127.0.0.1', server.getsockname()[1])
            thread.join(2)
        self.assertTrue(result['online'])
        self.assertEqual(result['connack'], 5)
        self.assertIn(b'MQTT', received[0])
        self.assertNotIn(b'm5-atleta-01', received[0])

    def test_arbitrary_open_port_is_not_mqtt(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            def respond():
                with server.accept()[0] as client:
                    client.recv(256)
                    client.sendall(b'HTTP')
            thread = threading.Thread(target=respond)
            thread.start()
            result = rede.mqtt_probe('127.0.0.1', server.getsockname()[1])
            thread.join(2)
        self.assertFalse(result['online'])

    def test_only_loopback_cannot_be_online_on_lan(self):
        def inspect(host, pair):
            return {'host': host, 'mqtt_port': pair[0], 'dashboard_port': pair[1],
                    'mqtt_online': host == '127.0.0.1', 'dashboard_online': host == '127.0.0.1'}
        with patch.object(rede, 'inspect_pair', side_effect=inspect):
            result = rede.diagnose('192.168.1.10', [(18830, 18084)])
        self.assertEqual(result['state'], 'local_only')
        self.assertFalse(result['lan']['mqtt_online'])

    def test_online_requires_mqtt_and_emqx_dashboard(self):
        def inspect(host, pair):
            return {'host': host, 'mqtt_port': pair[0], 'dashboard_port': pair[1],
                    'mqtt_online': True, 'dashboard_online': False}
        with patch.object(rede, 'inspect_pair', side_effect=inspect):
            self.assertEqual(rede.diagnose('10.0.0.8', [(1883, 18083)])['state'], 'mqtt_only')
        with patch.object(rede, 'inspect_pair', side_effect=lambda h, p: dict(inspect(h, p), dashboard_online=True)):
            self.assertEqual(rede.diagnose('10.0.0.8', [(1883, 18083)])['state'], 'online')

    def test_save_preserves_secrets_and_exports_only_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            original = {'wifi_ssid': 'rede teste', 'wifi_password': 'SEGREDO_WIFI_TESTE',
                        'mqtt_host': '10.0.0.1', 'mqtt_port': 1883, 'device_id': 'm5-atleta-01', 'extra': 42}
            device = dict(original, mqtt_password='SEGREDO_MQTT_TESTE', mqtt_username='m5-atleta-01')
            rede.atomic_json(folder / 'config.local.json', original)
            rede.atomic_json(folder / 'runtime/device-config.json', device)
            result = {'ip': '192.168.1.10', 'mqtt_port': 18830, 'dashboard_port': 18084,
                      'state': 'offline', 'checked_at': 'teste'}
            rede.save_address(folder, result)
            expected = dict(original, mqtt_host=result['ip'], mqtt_port=18830)
            self.assertEqual(rede.read_json(folder / 'config.local.json'), expected)
            self.assertEqual(rede.read_json(folder / 'runtime/device-config.json')['mqtt_password'], device['mqtt_password'])
            public = (folder / 'endereco-servidor.json').read_text()
            self.assertNotIn('SEGREDO', public)
            self.assertNotIn('wifi_ssid', public)

    def test_corrupted_device_config_does_not_replace_main_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            original = {'mqtt_host': '10.0.0.7'}
            rede.atomic_json(folder / 'config.local.json', original)
            (folder / 'runtime').mkdir()
            (folder / 'runtime/device-config.json').write_text('{broken')
            with self.assertRaises(ValueError):
                rede.save_address(folder, {'ip': '10.0.0.9', 'mqtt_port': 1883})
            self.assertEqual(rede.read_json(folder / 'config.local.json'), original)

    def test_rejects_loopback_as_device_address(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            rede.save_address(tmp, {'ip': '127.0.0.1', 'mqtt_port': 1883})
        self.assertIsNone(rede.port(True, None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
