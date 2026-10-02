import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from configurar_m5 import save_device_settings
from m5_serial import configuration_payload, send_configuration
from rede import atomic_json, read_json


class M5Tests(unittest.TestCase):
    def prepare(self, folder):
        atomic_json(Path(folder) / 'config.local.json', {'device_id': 'm5-atleta-01',
                    'wifi_ssid': 'REDE_TESTE', 'wifi_password': 'SENHA_TESTE',
                    'mqtt_host': '192.168.0.67', 'mqtt_port': 18830, 'extra': 'preservado'})
        atomic_json(Path(folder) / 'runtime/secrets.json', {'m5-atleta-01': 'SEGREDO_MQTT_TESTE'})

    def test_blank_profile_is_null_and_preserves_server_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.prepare(tmp)
            result = save_device_settings(tmp, 'Rede Nova', 'SENHA_NOVA')
            self.assertEqual(result['mqtt_host'], '192.168.0.67')
            self.assertEqual(result['mqtt_port'], 18830)
            self.assertEqual(result['extra'], 'preservado')
            for field in ('weight_kg', 'step_length_m', 'activity_met', 'athlete_id'):
                self.assertIsNone(result[field])

    def test_profile_accepts_decimal_comma(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.prepare(tmp)
            result = save_device_settings(tmp, 'REDE_TESTE', 'SENHA_TESTE', '70,5', '0,7', '3,8', '1')
            self.assertEqual(result['weight_kg'], 70.5)
            self.assertEqual(result['step_length_m'], 0.7)
            self.assertEqual(result['activity_met'], 3.8)
            self.assertEqual(result['athlete_id'], 1)

    def test_invalid_profile_does_not_replace_saved_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.prepare(tmp)
            path = Path(tmp) / 'config.local.json'
            original = path.read_bytes()
            for weight in ('nan', '-10', 'inf', '401', 'texto'):
                with self.assertRaises(ValueError):
                    save_device_settings(tmp, 'REDE_TESTE', 'SENHA_TESTE', weight)
                self.assertEqual(path.read_bytes(), original)

    def test_utf8_ssid_limit_is_checked_in_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_device_settings(tmp, 'á' * 17, 'SENHA_TESTE')
            self.assertFalse((Path(tmp) / 'config.local.json').exists())

    def test_usb_payload_uses_device_credentials_without_copying_admin_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.prepare(tmp)
            data = json.loads(configuration_payload(tmp).decode()[7:])
            self.assertEqual(data['mqtt_username'], 'm5-atleta-01')
            self.assertEqual(data['mqtt_password'], 'SEGREDO_MQTT_TESTE')
            self.assertEqual(data['mqtt_port'], 18830)
            self.assertNotIn('dashboard', data)

    def test_loopback_host_is_rejected_before_opening_serial_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.prepare(tmp)
            path = Path(tmp) / 'config.local.json'
            data = read_json(path)
            data['mqtt_host'] = '127.0.0.1'
            atomic_json(path, data)
            with patch('m5_serial.open_serial') as open_port:
                with self.assertRaises(ValueError):
                    send_configuration(tmp, 'COM_TESTE')
                open_port.assert_not_called()

    def test_usb_requires_explicit_config_acknowledgment(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.prepare(tmp)
            connection = MagicMock()
            connection.__enter__.return_value = connection
            connection.readline.side_effect = [b'STATUS wifi=0\n', b'CONFIG_OK\n']
            with patch('m5_serial.open_serial', return_value=connection), patch('m5_serial.time.sleep'):
                result = send_configuration(tmp, 'COM_TESTE')
            self.assertIn('Configuração enviada', result)
            connection.write.assert_called_once()

    def test_usb_rejection_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.prepare(tmp)
            connection = MagicMock()
            connection.__enter__.return_value = connection
            connection.readline.return_value = b'CONFIG_ERROR values\n'
            with patch('m5_serial.open_serial', return_value=connection), patch('m5_serial.time.sleep'):
                with self.assertRaisesRegex(ValueError, 'recusou'):
                    send_configuration(tmp, 'COM_TESTE')


if __name__ == '__main__':
    unittest.main(verbosity=2)
