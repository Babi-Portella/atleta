import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from wifi_pc import select_wifi, detect_wifi, autofill
import conexao_m5
from rede import atomic_json, read_json, Interface


class WifiAutoTests(unittest.TestCase):
    def test_new_network_never_reuses_saved_password(self):
        self.assertEqual(autofill('CASA', 'SENHA_DA_CASA', 'LAB'), ('LAB', ''))
        self.assertEqual(autofill('Claro11', 'SENHA', 'CLARO11'), ('CLARO11', ''))

    def test_same_network_reuses_only_project_password(self):
        self.assertEqual(autofill('LAB', 'SENHA_SALVA_NO_PROJETO', 'LAB'), ('LAB', 'SENHA_SALVA_NO_PROJETO'))

    def test_wired_or_disconnected_pc_does_not_invent_ssid(self):
        self.assertEqual(select_wifi([])['state'], 'no_wifi')
        self.assertIsNone(select_wifi([{'ssid': 'ANTIGA', 'connected': False}])['ssid'])
        self.assertEqual(autofill('REDE_M5', 'SENHA', None), ('REDE_M5', 'SENHA'))

    def test_active_network_supports_unicode_and_ignores_old_profile(self):
        self.assertEqual(select_wifi([{'ssid': 'Laboratório', 'connected': True},
                                      {'ssid': 'ANTIGA', 'connected': False}])['ssid'], 'Laboratório')
        self.assertEqual(select_wifi({'ssid': 'Casa', 'connected': True})['ssid'], 'Casa')

    def test_multiple_active_networks_are_not_chosen_arbitrarily(self):
        result = select_wifi([{'ssid': 'A', 'connected': True}, {'ssid': 'B', 'connected': True}])
        self.assertEqual(result['state'], 'multiple')
        self.assertIsNone(result['ssid'])

    def test_windows_failure_keeps_manual_entry_available(self):
        with patch('wifi_pc.subprocess.run', side_effect=subprocess.TimeoutExpired('powershell', 10)):
            result = detect_wifi()
        self.assertEqual(result['state'], 'unavailable')
        self.assertIsNone(result['ssid'])

    def test_target_uses_current_pc_and_exact_lab_ports_preserving_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            atomic_json(Path(tmp) / 'runtime/settings.json', {'bind': '0.0.0.0', 'mqtt_port': 1883, 'dashboard_port': 18083})
            atomic_json(Path(tmp) / 'config.local.json', {'mqtt_host': '192.168.0.67', 'weight_kg': 90, 'wifi_password': 'PRIVADA'})
            status = {'mqtt_online': True, 'dashboard_online': True, 'mqtt_port': 1883, 'dashboard_port': 18083}
            with patch('conexao_m5.detect_interfaces', return_value=[Interface('10.0.0.20', 'Wi-Fi', True)]), \
                 patch('conexao_m5.inspect_pair', return_value=status) as probe:
                target = conexao_m5.prepare_target(tmp)
            self.assertEqual(target, {'host': '10.0.0.20', 'port': 1883})
            probe.assert_called_once_with('10.0.0.20', (1883, 18083))
            config = read_json(Path(tmp) / 'config.local.json')
            self.assertEqual(config['weight_kg'], 90)
            self.assertEqual(config['wifi_password'], 'PRIVADA')
            self.assertEqual(config['mqtt_host'], '10.0.0.20')

    def test_network_disabled_stops_before_usb_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            atomic_json(Path(tmp) / 'runtime/settings.json', {'bind': '127.0.0.1', 'mqtt_port': 1883, 'dashboard_port': 18083})
            with patch('conexao_m5.send_configuration') as send:
                with self.assertRaisesRegex(ValueError, 'Permitir conexão'):
                    conexao_m5.configure_and_check(tmp, 'COM_TESTE')
                send.assert_not_called()

    def test_old_or_other_device_sample_is_not_live_success(self):
        sample = {'payload': {'source': 'device', 'boot_id': 'novo', 'sample_seq': 2}, 'age_seconds': 100, 'id': 45}
        self.assertIsNone(conexao_m5.persisted_match([sample], {('novo', 2)}))
        sample['age_seconds'] = 1
        self.assertIsNone(conexao_m5.persisted_match([sample], {('outro', 2)}))
        self.assertEqual(conexao_m5.persisted_match([sample], {('novo', 2)}), 45)

    def test_saved_configuration_alone_is_not_connection_success(self):
        state = {'samples': set()}
        conexao_m5.observe('CONFIG_OK', state)
        self.assertNotIn('confirmada', conexao_m5.conclusion(state, {'host': '10.0.0.20', 'port': 1883}))

    def test_diagnostic_distinguishes_wifi_auth_server_and_database(self):
        target = {'host': '10.0.0.20', 'port': 1883}
        self.assertIn('não entrou no Wi-Fi', conexao_m5.conclusion({'usb_response': True, 'wifi': False}, target))
        self.assertIn('recusou o login', conexao_m5.conclusion({'usb_response': True, 'wifi': True, 'mqtt': False, 'mqtt_error': 5}, target))
        self.assertIn('10.0.0.20:1883', conexao_m5.conclusion({'usb_response': True, 'wifi': True, 'mqtt': False}, target))
        self.assertIn('nenhuma leitura nova', conexao_m5.conclusion({'usb_response': True, 'wifi': True, 'mqtt': True}, target))

    def test_usb_telemetry_and_database_confirmation_report_no_passwords(self):
        with tempfile.TemporaryDirectory() as tmp:
            connection = MagicMock()
            connection.__enter__.return_value = connection
            payload = {'source': 'device', 'boot_id': 'nova-sessao', 'sample_seq': 3, 'mqtt_connected': True}
            connection.readline.side_effect = [b'STATUS wifi=1 mqtt=1 imu=1\n', ('TELEMETRY ' + json.dumps(payload) + '\n').encode()]
            row = {'id': 42, 'payload': payload, 'age_seconds': 0.1}
            with patch('conexao_m5.open_serial', return_value=connection), patch('conexao_m5.time.sleep'), \
                 patch('conexao_m5.fetch_readings', return_value=[row]):
                result = conexao_m5.verify_connection(tmp, 'COM_TESTE', {'host': '10.0.0.20', 'port': 1883})
            self.assertIn('leitura nova gravada', result)
            report = read_json(Path(tmp) / 'runtime/diagnostico-conexao-m5.json')
            self.assertTrue(report['live_data_confirmed'])
            self.assertEqual(report['mysql_row_id'], 42)
            self.assertNotIn('samples', report)


if __name__ == '__main__':
    unittest.main(verbosity=2)
