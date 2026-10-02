"""Captura aceleração, giroscópio e decisões do contador por USB ou Wi-Fi, sem credenciais."""
import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import time

import serial

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('ms', 'ax_g', 'ay_g', 'az_g', 'gx_dps', 'gy_dps', 'gz_dps',
          'filtered_g', 'cadence_ms', 'pending_peaks', 'event', 'steps', 'active')
EVENTS = {0: 'sample', 1: 'first_peak', 2: 'too_close', 3: 'restart_gap',
          4: 'restart_cadence', 5: 'candidate', 6: 'confirmed', 7: 'counted',
          8: 'invalid_sample', 9: 'sample_gap', 10: 'early_cadence', 11: 'motion_artifact'}
INTEGER_FIELDS = {'ms', 'cadence_ms', 'pending_peaks', 'event', 'steps', 'active'}


def parse_sample(line):
    if not line.startswith('IMU_SAMPLE '):
        return None
    values = line[len('IMU_SAMPLE '):].split(',')
    if len(values) != len(FIELDS):
        raise ValueError('Amostra USB incompleta')
    row = {key: int(value) if key in INTEGER_FIELDS else float(value)
           for key, value in zip(FIELDS, values)}
    if not all(math.isfinite(value) for value in row.values()):
        raise ValueError('Amostra USB não finita')
    if any(not 0 <= row[key] <= 0xffffffff for key in INTEGER_FIELDS):
        raise ValueError('Inteiro USB fora do intervalo')
    if row['event'] not in EVENTS or row['active'] not in (0, 1):
        raise ValueError('Estado USB inválido')
    return row


def summarize(rows, dropped, malformed, expected, session_changes=0):
    if len(rows) < 2:
        raise ValueError('Poucas amostras: confira o firmware 2.1.2 ou posterior e a porta USB.')
    intervals = [(b['ms'] - a['ms']) & 0xffffffff for a, b in zip(rows, rows[1:])]
    resets = sum(b['steps'] < a['steps'] for a, b in zip(rows, rows[1:]))
    count = rows[-1]['steps'] - rows[0]['steps'] if not (resets or session_changes) else None
    # Durante a pausa o firmware não executa StepCounter.add(); lastEvent()
    # ainda contém a decisão anterior. Ela não é uma nova decisão do detector.
    events = Counter(EVENTS[row['event']] for row in rows if row['active'] and row['event'])
    return {'samples': len(rows), 'duration_s': sum(intervals) / 1000,
            'median_sample_interval_ms': statistics.median(intervals),
            'largest_sample_gap_ms': max(intervals),
            'sample_gaps_over_60ms': sum(dt > 60 for dt in intervals),
            'device_dropped_samples': dropped, 'malformed_lines': malformed,
            'paused_samples': sum(not row['active'] for row in rows),
            'session_resets': resets, 'session_id_changes': session_changes,
            'initial_steps': rows[0]['steps'],
            'final_steps': rows[-1]['steps'], 'counted_steps': count,
            'manually_counted_steps': expected,
            'count_error': count - expected if count is not None and expected is not None else None,
            'detector_events': dict(events)}


def parse_mqtt_samples(payload):
    if 'imu_trace' not in payload:
        return []
    if payload.get('imu_trace_schema') != 2:
        raise ValueError('Versão de diagnóstico MQTT não reconhecida')
    rows = []
    for values in payload['imu_trace']:
        if len(values) != len(FIELDS):
            raise ValueError('Amostra MQTT incompleta')
        values = list(values)
        for index in (1, 2, 3, 7):
            values[index] /= 10000
        for index in (4, 5, 6):
            values[index] /= 100
        rows.append(parse_sample('IMU_SAMPLE ' + ','.join(map(str, values))))
    return rows


def parse_trace_begin(line, seconds):
    values = dict(item.split('=', 1) for item in line.split()[1:])
    timeout = int(values['timeout_s'])
    if seconds > timeout - 5:
        raise ValueError(f'O firmware grava por {timeout}s; atualize-o ou reduza --seconds para {timeout - 5}.')
    return timeout, int(values['start_ms']) if 'start_ms' in values else None


def samples_since_start(samples, start_ms, timeout):
    # Um pacote que já estava na fila de rede antes do comando não pertence ao teste.
    return [row for row in samples if start_ms is None or
            ((row['ms'] - start_ms) & 0xffffffff) < timeout * 1000]


def capture_wifi(port, seconds, label, expected, output, stop_file=None):
    import pymysql
    settings = json.loads((ROOT / 'runtime/settings.json').read_text(encoding='utf-8-sig'))
    secrets = json.loads((ROOT / 'runtime/secrets.json').read_text(encoding='utf-8-sig'))
    config = json.loads((ROOT / 'config.local.json').read_text(encoding='utf-8-sig'))
    rows, dropped, packets, malformed, boot = [], None, 0, 0, None
    session, session_changes, ready = None, 0, False
    output.mkdir(parents=True, exist_ok=False)
    with pymysql.connect(host='127.0.0.1', port=settings['mysql_port'],
                         user='lab_reader', password=secrets['mysql_reader'],
                         database='athlete_lab', autocommit=True,
                         connect_timeout=5, read_timeout=5, write_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT COALESCE(MAX(id),0) FROM telemetry')
            last_id = cursor.fetchone()[0]
        with serial.Serial(port, 115200, timeout=.2, write_timeout=3) as device:
            time.sleep(3)
            device.reset_input_buffer()
            # Algumas interfaces USB reiniciam a placa ao abrir. Esperar a
            # reconexão evita recusar o teste enquanto Wi-Fi/MQTT ainda sobem.
            deadline = time.monotonic() + 30
            next_try = 0
            while time.monotonic() < deadline:
                if time.monotonic() >= next_try:
                    device.write(b'TRACE_MQTT ON\n')
                    next_try = time.monotonic() + 2
                line = device.readline().decode('utf-8', errors='replace').strip()
                if line.startswith('IMU_TRACE_BEGIN schema=2 '):
                    timeout, start_ms = parse_trace_begin(line, seconds)
                    break
            else:
                raise ValueError('TRACE_MQTT não iniciou: confira firmware 2.1.3+, Wi-Fi e MQTT conectados.')
        ready_deadline = time.monotonic() + 10
        deadline = time.monotonic() + seconds
        with (output / 'imu.csv').open('w', newline='', encoding='utf-8') as file, \
                (output / 'packets.jsonl').open('w', encoding='utf-8') as packet_file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            while time.monotonic() < deadline and not (stop_file and stop_file.exists()):
                with connection.cursor() as cursor:
                    cursor.execute('SELECT id,payload FROM telemetry WHERE id>%s AND client_id=%s '
                                   'AND source=\'device\' ORDER BY id LIMIT 500',
                                   (last_id, config.get('device_id', 'm5-atleta-01')))
                    pending = cursor.fetchall()
                for row_id, raw in pending:
                    last_id = row_id
                    payload = json.loads(raw)
                    try:
                        samples = samples_since_start(parse_mqtt_samples(payload), start_ms, timeout)
                    except (ValueError, TypeError):
                        malformed += 1
                        continue
                    if not samples:
                        continue
                    if boot is not None and boot != payload.get('boot_id'):
                        raise ValueError('A placa reiniciou durante a captura; repita o teste.')
                    boot = payload.get('boot_id')
                    current_session = payload.get('sessao')
                    if not isinstance(current_session, str) or not current_session:
                        raise ValueError('Diagnóstico sem identificador de sessão; não é possível validar o teste.')
                    if session is not None and session != current_session:
                        session_changes += 1
                    session = current_session
                    packets += 1
                    dropped = payload.get('imu_trace_dropped')
                    rows.extend(samples)
                    writer.writerows(samples)
                    packet_file.write(json.dumps({'id': row_id, 'received_at_host_utc':
                        datetime.now(timezone.utc).isoformat(), 'sessao': session, 'boot_id': boot,
                        'sample_seq': payload.get('sample_seq'), 'imu_trace': payload['imu_trace']}) + '\n')
                    file.flush()
                    packet_file.flush()
                    if not ready:
                        ready = True
                        print(f'CAPTURE_READY transport=wifi seconds={seconds} label={label} '
                              f'session={session} initial_steps={samples[0]["steps"]}', flush=True)
                if not ready and time.monotonic() > ready_deadline:
                    raise ValueError('O M5 confirmou o comando, mas as amostras não chegaram por Wi-Fi ao banco.')
                time.sleep(.2)
    report = summarize(rows, dropped, malformed, expected, session_changes)
    report.update(recorded_at_utc=datetime.now(timezone.utc).isoformat(), label=label,
                  transport='wifi_mqtt_mysql', received_packets=packets, boot_id=boot,
                  final_session_id=session, firmware_trace_timeout_s=timeout,
                  stopped_by_file=bool(stop_file and stop_file.exists()))
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)
    print(f'CAPTURE_SAVED {output}', flush=True)
    return report


def capture(port, seconds, label, expected, output):
    rows, malformed, dropped, status = [], 0, None, None
    output.mkdir(parents=True, exist_ok=False)
    # Abrir a porta pode reiniciar a placa. A contagem deste teste começa
    # após IMU_TRACE_BEGIN, enquanto a pessoa ainda deve estar parada.
    with serial.Serial(port, 115200, timeout=.2, write_timeout=3) as device:
        time.sleep(3)
        device.reset_input_buffer()
        device.write(b'STATUS\nTRACE_IMU ON\n')
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                line = device.readline().decode('utf-8', errors='replace').strip()
                if line.startswith('STATUS '):
                    status = line
                if line.startswith('IMU_TRACE_BEGIN schema=1 '):
                    parse_trace_begin(line, seconds)
                    break
            else:
                raise ValueError('A placa não confirmou TRACE_IMU. Precisa do firmware 2.1.2 ou posterior.')
            print(f'CAPTURE_READY seconds={seconds} label={label}', flush=True)
            deadline = time.monotonic() + seconds
            csv_path = output / 'imu.csv'
            with csv_path.open('w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()

                def collect(line):
                    nonlocal malformed
                    try:
                        row = parse_sample(line)
                    except ValueError:
                        malformed += 1
                        return
                    if row is not None:
                        rows.append(row)
                        writer.writerow(row)

                while time.monotonic() < deadline:
                    collect(device.readline().decode('utf-8', errors='replace').strip())
                device.write(b'TRACE_IMU OFF\n')
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    line = device.readline().decode('utf-8', errors='replace').strip()
                    if line.startswith('IMU_TRACE_DONE '):
                        values = dict(item.split('=', 1) for item in line.split()[1:])
                        dropped = int(values['dropped'])
                        break
                    collect(line)
        finally:
            device.write(b'TRACE_IMU OFF\n')
    report = summarize(rows, dropped, malformed, expected)
    report.update(recorded_at_utc=datetime.now(timezone.utc).isoformat(), label=label, status=status)
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)
    print(f'CAPTURE_SAVED {output}', flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, help='USB para iniciar o diagnóstico; pode ser removida no modo Wi-Fi')
    parser.add_argument('--wifi', action='store_true', help='Lê o diagnóstico recebido por MQTT/MySQL, liberando o cabo USB')
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--label', default='walking')
    parser.add_argument('--expected-steps', type=int)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--stop-file', type=Path, help='No Wi-Fi, finalize e salve quando este arquivo existir')
    args = parser.parse_args()
    if not 5 <= args.seconds <= 590 or (args.expected_steps is not None and args.expected_steps < 0):
        parser.error('Use de 5 a 590 segundos e uma contagem manual não negativa.')
    if args.stop_file and (not args.wifi or args.stop_file.exists()):
        parser.error('--stop-file precisa do modo Wi-Fi e de um caminho que ainda não exista.')
    output = args.output or ROOT / 'runtime/calibracao' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    if args.wifi:
        capture_wifi(args.port, args.seconds, args.label, args.expected_steps, output, args.stop_file)
    else:
        capture(args.port, args.seconds, args.label, args.expected_steps, output)


if __name__ == '__main__':
    main()
