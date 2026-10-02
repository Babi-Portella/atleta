"""Verifica erro de início e detalhes em janela real, sem iniciar Docker."""
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from app import App, VERSION
from rede import atomic_json
from servidor import LabError
from smoke_gui import wait, capture_window


def main():
    evidence = Path(__file__).resolve().parents[1] / 'evidencias'
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    with tempfile.TemporaryDirectory(prefix='atleta-erro-') as tmp:
        root = tk.Tk()
        try:
            app = App(root, tmp)
            wait(root, lambda: app.result is not None and not app.busy)
            with patch('app.LabController.start', side_effect=FileNotFoundError('arquivo de teste não encontrado')):
                app.primary.invoke()
                wait(root, lambda: not app.busy)
            log = Path(tmp) / 'runtime/painel-acao.log'
            assert 'FileNotFoundError' in log.read_text(encoding='utf-8')
            assert 'arquivo de teste não encontrado' in log.read_text(encoding='utf-8')
            assert app.primary.instate(['!disabled'])
            with patch('app.os.startfile') as open_file:
                app.details_button.invoke()
                open_file.assert_called_once_with(log)
            with patch('app.LabController.start', side_effect=LabError(
                    'Abra o Docker Desktop, conclua a configuração inicial e confira se o mecanismo Linux está funcionando. Depois tente novamente.',
                    'docker_not_ready')):
                app.primary.invoke()
                wait(root, lambda: not app.busy)
            assert app.status.get() == 'Docker ainda não está pronto'
            assert app.primary.instate(['!disabled'])
            root.deiconify()
            root.geometry('590x700')
            root.update()
            wait(root, lambda: root.winfo_width() >= 590 and root.state() == 'normal')
            root.update_idletasks()
            capture_window(root, evidence / 'painel-erro-inicializacao.png')
            report = {'version': VERSION, 'passed': True,
                      'executed_at': datetime.now(timezone.utc).isoformat(),
                      'scope': 'Janela Tk real; falhas injetadas; nenhum serviço Docker iniciado',
                      'unexpected_exception_logged': True, 'details_opens_log': True,
                      'docker_failure_title_specific': True, 'retry_button_enabled': True}
            atomic_json(evidence / 'validacao-painel-erro.json', report)
            print(json.dumps(report, ensure_ascii=False))
        finally:
            root.destroy()


if __name__ == '__main__':
    main()
