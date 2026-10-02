"""Validação opt-in da placa real, seus comandos USB e a persistência das suas amostras."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import pymysql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'painel'))
from m5_serial import open_serial
from rede import atomic_json, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    args = parser.parse_args()
    samples, inventories, tests, events = [], [], [], []
    with open_serial(args.port) as connection:
        time.sleep(3)
        connection.reset_input_buffer()
        def collect(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                line = connection.readline().decode('utf-8', errors='replace').strip()
                for prefix, target in (('TELEMETRY ', samples), ('INVENTORY ', inventories), ('SELFTEST ', tests)):
                    if line.startswith(prefix):
                        try:
                            target.append(json.loads(line[len(prefix):]))
                        except ValueError:
                            pass
                        break
                else:
                    if line.startswith(('STATUS ', 'SESSION_', 'BLE_STATUS ', 'WIFI_', 'MQTT_')):
                        events.append(line)
        for command, seconds in (('INVENTORY', 2), ('SCAN_I2C', 3), ('SELFTEST', 2),
                                  ('STATUS', 2), ('SESSION PAUSE', 5), ('SESSION RESUME', 3),
                                  ('BLE ON', 5), ('BLE OFF', 3)):
            connection.write((command + '\n').encode())
            connection.flush()
            collect(seconds)
        collect(4)
    assert len(samples) >= 5, 'Poucas amostras reais recebidas'
    assert inventories and inventories[0]['imu_who_am_i'] == 0x19
    checks = [value for value in tests[-1].values() if isinstance(value, bool)] if tests else []
    assert checks and all(checks), 'Autoteste da placa falhou ou não trouxe verificações'
    assert all(sample['source'] == 'device' and all(math.isfinite(sample[k]) for k in ('accel_x_g','accel_y_g','accel_z_g')) for sample in samples)
    assert all(sample['bpm'] is None and sample['temperatura_pele_c'] is None and sample['latitude'] is None and sample['longitude'] is None for sample in samples)
    paused = [sample for sample in samples if not sample['sessao_ativa']]
    assert len(paused) >= 2 and len({s['duracao_s'] for s in paused}) == 1, 'Tempo avançou durante pausa'
    assert len({s['passos'] for s in paused}) == 1, 'Passos avançaram durante pausa'
    assert any(s['bluetooth'] == 'anunciando' for s in samples), 'BLE não ativou'
    assert samples[-1]['bluetooth'] == 'desligado', 'BLE não voltou ao estado desligado'
    latest = samples[-1]
    settings = read_json(ROOT / 'runtime/settings.json')
    secrets = read_json(ROOT / 'runtime/secrets.json')
    connection = pymysql.connect(host='127.0.0.1', port=settings['mysql_port'], user='lab_reader',
                                 password=secrets['mysql_reader'], database='athlete_lab', autocommit=True,
                                 cursorclass=pymysql.cursors.DictCursor)
    with connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id,client_id,mqtt_username,topic,payload FROM telemetry WHERE boot_id=%s AND source=%s ORDER BY sample_seq',
                           (latest['boot_id'], 'device'))
            rows = cursor.fetchall()
    stored = {json.loads(row['payload'])['sample_seq']: json.loads(row['payload']) for row in rows}
    matched = [s for s in samples if stored.get(s['sample_seq']) == s]
    wifi_ok = any(s['wifi'] == 'conectado' and s['mqtt_connected'] for s in samples)
    persistence_ok = len(matched) >= 3
    report = {'executed_at_utc': datetime.now(timezone.utc).isoformat(),
              'passed': True, 'scope': 'Sensores e comandos na placa física; persistência verificada separadamente',
              'firmware_sha256': hashlib.sha256((ROOT/'entrega/firmware/firmware.bin').read_bytes()).hexdigest(),
              'source_sha256': hashlib.sha256((ROOT/'firmware/src/main.cpp').read_bytes()).hexdigest(),
              'serial_port': args.port, 'inventories': inventories, 'algorithm_selftest': tests[-1],
              'real_samples_received': len(samples), 'pause_verified': True, 'resume_verified': latest['sessao_ativa'],
              'ble_enabled_and_disabled_on_board': True, 'ble_remote_client_tested': False,
              'wifi_mqtt_connected': wifi_ok, 'mysql_rows_same_boot': len(rows),
              'samples_identical_in_mysql': len(matched), 'direct_device_mqtt_mysql_verified': wifi_ok and persistence_ok,
              'last_sample': latest, 'physical_step_accuracy_calibrated': False,
              'external_bpm_skin_temperature_gps_tested': False}
    atomic_json(ROOT / 'evidencias/validacao-m5-fisico.json', report)
    atomic_json(ROOT / 'evidencias/amostras-m5-fisico.json', samples)
    print(json.dumps({'hardware_passed': True, 'samples':len(samples), 'wifi_mqtt':wifi_ok,
                      'identical_mysql_samples':len(matched), 'end_to_end':wifi_ok and persistence_ok,
                      'external_i2c':inventories[-1].get('external_i2c_addresses')}, ensure_ascii=False))
    if not wifi_ok or not persistence_ok:
        raise SystemExit('Placa validada por USB; envio direto por Wi-Fi/MySQL ainda pendente.')


if __name__ == '__main__':
    main()
