"""Teste opt-in dos botões reais com a stack local dedicada. Preserva configuração e dados."""
import ctypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tkinter as tk
from unittest.mock import patch

from app import App
from rede import atomic_json
from servidor import LabController
from smoke_gui import wait, capture_window

LAB = Path(__file__).resolve().parents[1]


def database_signature():
    query = '''import hashlib,json,pathlib,sys
sys.path.insert(0,str(pathlib.Path('laboratorio/tools').resolve()))
import pymysql
from lab import load_secrets,read_json,RUNTIME
data=load_secrets(); settings=read_json(RUNTIME/'settings.json')
with pymysql.connect(host='127.0.0.1',port=settings['mysql_port'],user='lab_reader',password=data['mysql_reader'],database='athlete_lab') as connection:
    with connection.cursor() as cursor:
        cursor.execute('SELECT id,payload FROM telemetry ORDER BY id')
        rows=cursor.fetchall()
print(json.dumps({'rows':len(rows),'sha256':hashlib.sha256(json.dumps(rows).encode()).hexdigest()}))
'''
    result = subprocess.run([str(LAB.parent / '.venv-lab/Scripts/python.exe'), '-c', query],
                            cwd=LAB.parent, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main():
    paths = [LAB / name for name in ('config.local.json', 'endereco-servidor.json',
             'runtime/device-config.json', 'runtime/settings.json', 'runtime/compose.env')]
    before_files = {path: path.read_bytes() if path.exists() else None for path in paths}
    secret_hash = hashlib.sha256((LAB / 'runtime/secrets.json').read_bytes()).hexdigest()
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    app = App(root, LAB)
    try:
        with patch('app.webbrowser.open', return_value=True) as browser:
            wait(root, lambda: app.result is not None and not app.busy)
            app.allow_network.set(False)
            app.primary.invoke()
            assert app.busy and app.stop_button.instate(['disabled'])
            wait(root, lambda: not app.busy, timeout=360)
            assert app.last_error is None, app.last_error
            assert app.result['dashboard_url']
            browser.assert_called_once()
            first = database_signature()
            assert first['rows'] > 0
            root.update_idletasks()
            capture_window(root, LAB / 'evidencias/painel-iniciado.png')
            app.stop_button.invoke()
            wait(root, lambda: not app.busy, timeout=120)
            assert app.last_error is None, app.last_error
            assert app.result['state'] == 'offline'
            app.primary.invoke()
            wait(root, lambda: not app.busy, timeout=240)
            assert app.last_error is None, app.last_error
            assert browser.call_count == 2
            after = database_signature()
            assert first == after
            assert hashlib.sha256((LAB / 'runtime/secrets.json').read_bytes()).hexdigest() == secret_hash
            app.stop_button.invoke()
            wait(root, lambda: not app.busy, timeout=120)
            assert app.last_error is None and app.result['state'] == 'offline'
            report = {'passed': True, 'executed_at': datetime.now(timezone.utc).isoformat(),
                      'scope': 'Botões da janela Python com Docker Desktop, EMQX e MySQL reais locais',
                      'start_button_verified': True, 'stop_button_verified': True,
                      'dashboard_open_dispatched_twice': True, 'browser_navigation_mocked': True,
                      'mysql_rows_before': first['rows'], 'mysql_rows_after': after['rows'],
                      'payloads_preserved': True, 'credentials_preserved': True,
                      'services_stopped_after_test': True, 'configuration_restored_after_test': True,
                      'physical_m5_tested': False}
            atomic_json(LAB / 'evidencias/validacao-automacao-painel.json', report)
            print(json.dumps(report, ensure_ascii=False))
    finally:
        root.destroy()
        if app.busy:
            raise RuntimeError('Operação ainda ativa: aguarde antes de restaurar os arquivos')
        # O stop é restrito aos dois serviços próprios. Nenhum volume é removido.
        LabController(LAB).stop()
        for path, content in before_files.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)


if __name__ == '__main__':
    main()
