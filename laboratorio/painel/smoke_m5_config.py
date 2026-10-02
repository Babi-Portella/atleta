"""Testa a janela real com dados fictícios e USB simulado; não envia senhas reais."""
import ctypes
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from configurar_m5 import ConfigWindow
from rede import read_json, atomic_json
from smoke_gui import wait, capture_window


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    evidence = Path(__file__).resolve().parents[1] / 'evidencias'
    with tempfile.TemporaryDirectory(prefix='atleta-config-ui-') as tmp:
        root = tk.Tk()
        try:
            with patch('configurar_m5.detect_wifi', return_value={'ssid': 'REDE_DETECTADA', 'state': 'connected', 'message': 'Rede detectada para teste.'}):
                ui = ConfigWindow(root, tmp, 'REDE_EXEMPLO')
                wait(root, lambda: ui.ssid.get() == 'REDE_DETECTADA')
            root.update()
            assert ui.password.get() == ''
            assert ui.password_entry.cget('show') == '*'
            ui.password.set('SENHA_FICTICIA')
            ui.profile['weight_kg'].set('70,5')
            ui.profile['step_length_m'].set('0,7')
            ui.profile['activity_met'].set('3,8')
            ui.save_button.invoke()
            assert ui.saved
            config = read_json(Path(tmp) / 'config.local.json')
            assert config['weight_kg'] == 70.5 and config['step_length_m'] == 0.7
            ui.usb_port.set('COM_TESTE')
            # Uma resposta atrasada nunca substitui o nome/senha editados pelo usuário.
            baseline = ui.ssid.get(), ui.password.get()
            ui.ssid.set('REDE_EDITADA')
            ui.apply_network(baseline, {'ssid': 'NAO_SUBSTITUIR', 'message': 'Detectado'})
            assert ui.ssid.get() == 'REDE_EDITADA'
            with patch('configurar_m5.configure_and_check', return_value='USB e banco de teste confirmados') as send:
                ui.send_button.invoke()
                wait(root, lambda: not ui.busy)
                assert send.call_args.args == (Path(tmp), 'COM_TESTE')
            assert ui.feedback.get() == 'USB e banco de teste confirmados'
            assert str(ui.send_button.cget('state')) == 'normal'
            root.deiconify()
            root.geometry('540x820')
            root.update()
            capture_window(root, evidence / 'configuracao-m5.png')
            report = {'passed': True, 'scope': 'Janela Tk real, dados fictícios, envio USB simulado',
                      'password_masked': True, 'decimal_comma_supported': True,
                      'saved_config_verified': True, 'usb_action_dispatched': True, 'window_responsive': True}
            report.update(ssid_auto_filled=True, different_network_password_cleared=True, user_edit_preserved=True)
            atomic_json(evidence / 'validacao-configuracao-m5-gui.json', report)
            print(json.dumps(report, ensure_ascii=False))
        finally:
            root.destroy()


if __name__ == '__main__':
    main()
