"""Valida a janela com o banco real e depois estados controlados, sem alterar dados."""
import ctypes
from datetime import datetime, timezone
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from dados_atleta import AthleteWindow, DataError, fetch_readings, metric_values
from rede import atomic_json
from smoke_gui import wait, capture_window


def main():
    lab = Path(__file__).resolve().parents[1]
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    ttk.Style(root).theme_use('clam')
    ui = AthleteWindow(root, lab)
    try:
        wait(root, lambda: not ui.busy)
        assert ui.error is None, ui.error
        assert ui.rows, 'Nenhuma leitura física armazenada para esta validação'
        ui.auto.set(False)
        assert all(row['payload']['source'] == 'device' for row in ui.rows)
        latest = ui.rows[0]
        assert {k: v.get() for k,v in ui.metrics.items()} == metric_values(latest['payload'])
        assert len(ui.tree.get_children()) == len(ui.rows)
        ui.auto.set(True)
        ui.render_status()
        root.update()
        capture_window(root, lab/'evidencias/dados-atleta.png')
        native_count = len(ui.rows)
        ui.auto.set(False)
        # Atualização real sem bloquear a janela; banco consultado somente com SELECT.
        ui.refresh_button.invoke()
        assert ui.busy and ui.refresh_button.instate(['disabled'])
        wait(root, lambda: not ui.busy)
        assert ui.error is None
        root.geometry('800x660')
        root.update()
        for widget in (*ui.cards, ui.tree, ui.refresh_button, ui.help_label):
            assert widget.winfo_ismapped()
            assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
            assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
        capture_window(root, lab/'evidencias/dados-atleta-compacto.png')
        # Falha preserva os valores, mas nunca mantém o indicador de dados recentes.
        before = {key: value.get() for key,value in ui.metrics.items()}
        with patch('dados_atleta.fetch_readings', side_effect=DataError('Falha de consulta controlada')):
            ui.refresh()
            wait(root, lambda: not ui.busy)
        assert 'desatualizados' in ui.status.get()
        assert before == {key: value.get() for key,value in ui.metrics.items()}
        # Janela sem amostras reais não preenche números fictícios.
        with patch('dados_atleta.fetch_readings', return_value=[]):
            ui.refresh()
            wait(root, lambda: not ui.busy)
        assert 'Ainda não há leituras' in ui.status.get()
        assert all(value.get() == 'Indisponível' for value in ui.metrics.values())
        ui.tree.insert('', 'end', iid='temporary')
        ui.tree.delete('temporary')
        ui.rows = [dict(latest, age_seconds=60)]
        ui.loaded_at = time.monotonic()
        ui.auto.set(True)
        ui.render_status()
        assert 'Sem dados recentes' in ui.status.get()
        atomic_json(lab/'evidencias/validacao-dados-atleta.json', {
            'passed': True, 'executed_at_utc': datetime.now(timezone.utc).isoformat(),
            'scope': 'Janela Tk real e MySQL local real; erros e vazio simulados após captura',
            'real_rows_displayed': native_count, 'real_source_only': True,
            'display_matches_stored_payload': True, 'refresh_button_tested': True,
            'window_responsive': True, 'minimum_size_checked': [800,660],
            'missing_values_unavailable': True, 'stale_state_verified': True,
            'error_state_verified': True, 'empty_state_verified': True,
            'database_mutated': False})
        print('PASS: dados físicos, atualização, vazio, erro e leitura antiga na janela real')
    finally:
        ui.close()


if __name__ == '__main__':
    main()
