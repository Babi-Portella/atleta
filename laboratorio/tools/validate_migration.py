"""Testa a migração em containers descartáveis isolados, sem alterar atleta-lab."""
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'painel'))
import migracao
import servidor
from rede import atomic_json, read_json


def free_port():
    with socket.socket() as connection:
        connection.bind(('127.0.0.1', 0))
        return connection.getsockname()[1]


def count(folder):
    with migracao.connect(folder) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM telemetry')
            return cursor.fetchone()['n']


def main():
    stamp = datetime.now().strftime('%Y%m%d%H%M%S')
    project = 'atleta-migracao-teste-' + stamp
    folder = ROOT / 'runtime' / ('validacao-migracao-' + stamp)
    folder.mkdir(parents=True, exist_ok=False)
    checks = []
    report = {'executed_at_utc': datetime.now(timezone.utc).isoformat(), 'project': project,
              'scope': 'Instalação vazia isolada neste PC; computador de destino não testado.',
              'checks': checks, 'passed': False}

    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})
        print(('PASS ' if value else 'FAIL ') + name, flush=True)
        assert value, name

    snapshot = migracao.export_history(ROOT, folder / 'migracao')
    report['snapshot'] = snapshot
    env = dict(os.environ)
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    env['PATH'] = ';'.join(str(p) for p in (windows, windows / 'System32'))
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    exe = ROOT / 'entrega/PainelIP.exe'
    report['exe_sha256'] = hashlib.sha256(exe.read_bytes()).hexdigest()
    with patch.object(servidor, 'PROJECT', project):
        controller = servidor.LabController(folder, progress=lambda s: print(s, flush=True))
        try:
            result = subprocess.run([str(exe), '--preparar', '--pasta', str(folder)], env=env,
                                    timeout=40, creationflags=subprocess.CREATE_NO_WINDOW)
            check('EXE prepara instalação vazia sem Python no PATH', result.returncode == 0 and servidor.initialized(folder))
            settings = read_json(folder / 'runtime/settings.json')
            settings.update(profile='local', bind='127.0.0.1', mqtt_port=free_port(), dashboard_port=free_port(), mysql_port=free_port())
            atomic_json(folder / 'runtime/settings.json', settings)
            env_path = folder / 'runtime/compose.env'
            compose_env = env_path.read_text(encoding='utf-8')
            for key, value in [('BIND_ADDRESS', '127.0.0.1'), ('MQTT_PORT', settings['mqtt_port']),
                               ('DASHBOARD_PORT', settings['dashboard_port']), ('MYSQL_PORT', settings['mysql_port'])]:
                compose_env = re.sub(r'^' + key + '=.*$', key + '=' + str(value), compose_env, flags=re.M)
            env_path.write_text(compose_env, encoding='utf-8')
            report['ports'] = {key: settings[key] for key in ('mqtt_port', 'dashboard_port', 'mysql_port')}
            original_secrets = read_json(ROOT / 'runtime/secrets.json')
            new_secrets = read_json(folder / 'runtime/secrets.json')
            check('Destino usa credenciais novas e separadas da origem', all(new_secrets[key] != value for key, value in original_secrets.items()))
            controller.ensure_engine(start=False)
            controller.run(controller.compose_args('up', '-d', '--wait', '--wait-timeout', '180', 'mysql'), timeout=240)
            check('MySQL de destino começa vazio', count(folder) == 0)

            real_connect = migracao.connect
            class BrokenCursor:
                def __init__(self, cursor): self.cursor = cursor
                def __getattr__(self, name): return getattr(self.cursor, name)
                def __enter__(self): self.cursor.__enter__(); return self
                def __exit__(self, *args): return self.cursor.__exit__(*args)
                def executemany(self, *args):
                    self.cursor.executemany(*args)
                    raise migracao.pymysql.OperationalError(9998, 'Falha simulada depois do primeiro lote')
            class BrokenConnection:
                def __init__(self, connection): self.connection = connection
                def __getattr__(self, name): return getattr(self.connection, name)
                def __enter__(self): self.connection.__enter__(); return self
                def __exit__(self, *args): return self.connection.__exit__(*args)
                def cursor(self): return BrokenCursor(self.connection.cursor())
            interrupted = False
            with patch.object(migracao, 'connect', side_effect=lambda *a, **k: BrokenConnection(real_connect(*a, **k))):
                try: migracao.restore_history(folder)
                except migracao.MigrationError: interrupted = True
            check('Falha durante a importação reverte todos os registros', interrupted and count(folder) == 0)

            result = controller.start(False)
            restored = read_json(folder / 'runtime/restauracao-historico.json')
            check('Iniciar restaura e confere integralmente o histórico', result['started'] and restored['passed'] and restored['rows_inserted'] == snapshot['rows'] and count(folder) == snapshot['rows'])
            result = controller.start(False)
            repeated = read_json(folder / 'runtime/restauracao-historico.json')
            check('Repetir Iniciar não duplica o histórico', repeated['rows_inserted'] == 0 and count(folder) == snapshot['rows'])

            modified = copy.deepcopy(migracao.load_history(folder))
            modified[1][0]['accel_x_g'] += 1
            blocked = False
            try: migracao.restore_history(folder, modified)
            except migracao.MigrationError: blocked = True
            check('Dados conflitantes não substituem registros existentes', blocked and migracao.restore_history(folder)['rows_inserted'] == 0)

            # Testes MQTT usam contas sintéticas neste broker isolado, nunca a identidade do M5.
            import lab
            old_root, old_runtime = lab.ROOT, lab.RUNTIME
            lab.ROOT, lab.RUNTIME = folder, folder / 'runtime'
            try:
                import verify
                verify.ROOT, verify.RUNTIME = folder, folder / 'runtime'
                verify.run('127.0.0.1', settings['mqtt_port'], settings['mysql_port'], settings['dashboard_port'])
            finally:
                lab.ROOT, lab.RUNTIME = old_root, old_runtime
            server = read_json(folder / 'evidencias/validacao-servidor.json')
            check('28 verificações MQTT/MySQL passam no servidor restaurado', server['passed'] and len(server['checks']) == 28)
            after = migracao.restore_history(folder)
            check('Novas mensagens coexistem com o histórico restaurado', after['rows_inserted'] == 0 and count(folder) == snapshot['rows'] + 3)
            report['restoration'] = restored
            report['server_checks'] = server['checks']
            report['passed'] = True
        finally:
            # Conserva os volumes de teste para inspeção; para apenas os containers deste teste.
            if controller.docker:
                controller.run(controller.compose_args('stop', 'emqx', 'mysql'), timeout=90, check=False)
            atomic_json(ROOT / 'evidencias/validacao-migracao.json', report)
            print('Relatório: laboratorio/evidencias/validacao-migracao.json', flush=True)
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
