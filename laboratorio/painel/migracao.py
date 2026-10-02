"""Snapshot e restauração transacional da telemetria, sem executar SQL do pacote."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path

import pymysql
from rede import atomic_json, read_json

COLUMNS = ('id', 'received_at', 'mqtt_username', 'client_id', 'topic', 'boot_id',
           'sample_seq', 'source', 'accel_x_g', 'accel_y_g', 'accel_z_g', 'payload')
DATA_FILE = 'telemetria.jsonl.gz'
MAX_BYTES = 128 * 1024 * 1024


class MigrationError(ValueError):
    pass


def canonical(row):
    data = {key: row[key] for key in COLUMNS}
    if isinstance(data['received_at'], datetime):
        data['received_at'] = data['received_at'].isoformat(timespec='milliseconds')
    if isinstance(data['payload'], str):
        data['payload'] = json.loads(data['payload'])
    return data


def encoded(row):
    return json.dumps(canonical(row), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'


def connect(folder, write=False):
    folder = Path(folder)
    settings = read_json(folder / 'runtime/settings.json')
    secret = read_json(folder / 'runtime/secrets.json')
    return pymysql.connect(host='127.0.0.1', port=settings['mysql_port'],
                           user='emqx_lab' if write else 'lab_reader',
                           password=secret['mysql_emqx' if write else 'mysql_reader'],
                           database='athlete_lab', charset='utf8mb4', autocommit=False,
                           connect_timeout=5, read_timeout=30, write_timeout=30,
                           init_command="SET time_zone = '+00:00'",
                           cursorclass=pymysql.cursors.DictCursor)


def export_history(folder, target):
    """Uma leitura consistente; não interrompe nem altera o banco de origem."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    with connect(folder) as connection:
        with connection.cursor() as cursor:
            cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            cursor.execute('SELECT ' + ','.join(COLUMNS) + ' FROM telemetry ORDER BY id')
            rows = [canonical(row) for row in cursor.fetchall()]
        connection.rollback()
    content = b''.join(encoded(row) for row in rows)
    if len(content) > MAX_BYTES:
        raise MigrationError('O histórico excede o limite deste exportador (128 MiB).')
    compressed = gzip.compress(content, mtime=0)
    (target / DATA_FILE).write_bytes(compressed)
    manifest = {'format_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'database': 'athlete_lab', 'table': 'telemetry', 'columns': list(COLUMNS),
                'rows': len(rows), 'physical_rows': sum(r['source'] == 'device' for r in rows),
                'test_rows': sum(r['source'] == 'test' for r in rows),
                'first_received_at_utc': rows[0]['received_at'] if rows else None,
                'last_received_at_utc': rows[-1]['received_at'] if rows else None,
                'file': DATA_FILE, 'sha256': hashlib.sha256(compressed).hexdigest(),
                'content_sha256': hashlib.sha256(content).hexdigest()}
    atomic_json(target / 'manifest.json', manifest)
    return manifest


def load_history(folder):
    directory = Path(folder) / 'migracao'
    if not directory.exists():
        return None
    try:
        manifest = read_json(directory / 'manifest.json')
        if (manifest['format_version'] != 1 or manifest['columns'] != list(COLUMNS)
                or manifest['file'] != DATA_FILE or manifest['table'] != 'telemetry'
                or manifest['database'] != 'athlete_lab'
                or type(manifest['rows']) is not int or not 0 <= manifest['rows'] <= 1_000_000):
            raise ValueError()
        path = directory / DATA_FILE
        if path.stat().st_size > MAX_BYTES:
            raise ValueError()
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['sha256']:
            raise ValueError()
        with gzip.open(path, 'rb') as file:
            raw = file.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != manifest['content_sha256']:
            raise ValueError()
        rows = [json.loads(line) for line in raw.splitlines()]
        if len(rows) != manifest['rows']:
            raise ValueError()
        ids, identities = set(), set()
        for row in rows:
            if set(row) != set(COLUMNS):
                raise ValueError()
            if type(row['id']) is not int or not 0 < row['id'] < 2**64 or row['id'] in ids:
                raise ValueError()
            ids.add(row['id'])
            if type(row['sample_seq']) is not int or not 0 <= row['sample_seq'] < 2**64:
                raise ValueError()
            for key, limit in (('mqtt_username', 64), ('client_id', 64), ('topic', 255), ('boot_id', 32)):
                if not isinstance(row[key], str) or not 1 <= len(row[key]) <= limit:
                    raise ValueError()
            if row['mqtt_username'] not in ('m5-atleta-01', 'lab-teste-01') or row['source'] not in ('device', 'test'):
                raise ValueError()
            identity = (row['mqtt_username'], row['boot_id'], row['sample_seq'])
            if identity in identities:
                raise ValueError()
            identities.add(identity)
            timestamp = datetime.fromisoformat(row['received_at'])
            if timestamp.tzinfo is not None:
                raise ValueError()
            for key in ('accel_x_g', 'accel_y_g', 'accel_z_g'):
                if type(row[key]) not in (int, float) or not math.isfinite(row[key]):
                    raise ValueError()
            if not isinstance(row['payload'], dict):
                raise ValueError()
            encoded(row)
        return manifest, rows
    except (OSError, EOFError, ValueError, TypeError, KeyError, OverflowError):
        raise MigrationError('O histórico de migração está incompleto ou corrompido. Extraia novamente o ZIP original.') from None


def restore_history(folder, snapshot=None):
    snapshot = load_history(folder) if snapshot is None else snapshot
    if snapshot is None:
        return None
    manifest, rows = snapshot
    inserted = 0
    try:
        with connect(folder, write=True) as connection:
            try:
                with connection.cursor() as cursor:
                    # Verifica antes de inserir e nunca substitui linhas de outra instalação.
                    found = {}
                    for start in range(0, len(rows), 500):
                        ids = [r['id'] for r in rows[start:start + 500]]
                        cursor.execute('SELECT ' + ','.join(COLUMNS) + ' FROM telemetry WHERE id IN ('
                                       + ','.join(['%s'] * len(ids)) + ')', ids)
                        found.update((r['id'], canonical(r)) for r in cursor.fetchall())
                    missing = []
                    for row in rows:
                        if row['id'] in found:
                            if encoded(found[row['id']]) != encoded(row):
                                raise MigrationError('Este banco já contém registros diferentes. Use uma instalação nova para restaurar este pacote; nenhum registro foi substituído.')
                        else:
                            missing.append(row)
                    statement = 'INSERT INTO telemetry (' + ','.join(COLUMNS) + ') VALUES (' + ','.join(['%s'] * len(COLUMNS)) + ')'
                    for start in range(0, len(missing), 200):
                        values = []
                        for row in missing[start:start + 200]:
                            data = dict(row, received_at=datetime.fromisoformat(row['received_at']),
                                        payload=json.dumps(row['payload'], ensure_ascii=False, allow_nan=False))
                            values.append(tuple(data[key] for key in COLUMNS))
                        cursor.executemany(statement, values)
                    # Releitura integral prova IDs, horários, identidade e todos os campos do JSON.
                    verified = []
                    for start in range(0, len(rows), 500):
                        batch = rows[start:start + 500]
                        ids = [r['id'] for r in batch]
                        cursor.execute('SELECT ' + ','.join(COLUMNS) + ' FROM telemetry WHERE id IN ('
                                       + ','.join(['%s'] * len(ids)) + ')', ids)
                        actual = {r['id']: r for r in cursor.fetchall()}
                        if any(r['id'] not in actual or encoded(actual[r['id']]) != encoded(r) for r in batch):
                            raise MigrationError('A conferência do histórico falhou. A restauração foi revertida.')
                        verified.extend(encoded(actual[r['id']]) for r in batch)
                    if hashlib.sha256(b''.join(verified)).hexdigest() != manifest['content_sha256']:
                        raise MigrationError('A conferência do histórico falhou. A restauração foi revertida.')
                connection.commit()
                inserted = len(missing)
            except Exception:
                connection.rollback()
                raise
    except pymysql.MySQLError:
        raise MigrationError('Não foi possível restaurar o histórico no MySQL. A transação foi revertida; confira se a instalação é nova e tente iniciar novamente.') from None
    report = {'verified_at_utc': datetime.now(timezone.utc).isoformat(),
              'snapshot_sha256': manifest['sha256'], 'rows_verified': len(rows),
              'rows_inserted': inserted, 'rows_already_present': len(rows) - inserted, 'passed': True}
    atomic_json(Path(folder) / 'runtime/restauracao-historico.json', report)
    return report
