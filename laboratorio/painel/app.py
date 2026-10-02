"""Painel portátil para preparar, iniciar e parar o laboratório EMQX/MySQL."""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from rede import detect_interfaces, diagnose, diagnose_local, find_folder, port_pairs, save_address, atomic_json, read_json
from servidor import LabController, LabError, network_enabled, initialized, prepare_files, operation_lock, DOCKER_DOWNLOAD

VERSION = '1.5.0'
BG, WHITE, TEXT, MUTED = '#F3F5F7', '#FFFFFF', '#17212B', '#52616F'
ACCENT, GOOD, WARN, BAD = '#176453', '#166448', '#865500', '#A52D36'


class App:
    def __init__(self, root, folder):
        self.root, self.folder = root, Path(folder)
        self.events = queue.Queue()
        self.busy = False
        self.interfaces = []
        self.result = self.saved = self.last_error = None
        self.error_kind = None
        self.ip = tk.StringVar(value='Detectando…')
        self.adapter = tk.StringVar()
        self.status = tk.StringVar(value='Verificando o servidor')
        self.details = tk.StringVar(value='Consultando as conexões deste computador…')
        self.ports = tk.StringVar(value='MQTT —     Dashboard —')
        self.feedback = tk.StringVar(value='Clique em iniciar para preparar o laboratório e abrir o Dashboard.')
        self.allow_network = tk.BooleanVar(value=network_enabled(self.folder))
        root.title('Atleta IP — servidor do laboratório')
        icon = Path(sys._MEIPASS) / 'painel.ico' if getattr(sys, 'frozen', False) else Path(__file__).parent / 'build/painel.ico'
        if icon.is_file():
            root.iconbitmap(str(icon))
        root.configure(bg=BG)
        root.resizable(True, False)
        root.minsize(590, 0)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TCombobox', font=('Segoe UI', 10), padding=6)
        style.configure('Primary.TButton', font=('Segoe UI', 11, 'bold'), padding=(16, 12),
                        background=ACCENT, foreground=WHITE, borderwidth=0, focusthickness=2, focuscolor=TEXT)
        style.map('Primary.TButton', background=[('disabled', '#D5DFDB'), ('pressed', '#104637'), ('active', '#124F41')],
                  foreground=[('disabled', '#485A53')])
        style.configure('Secondary.TButton', font=('Segoe UI', 10), padding=(9, 9),
                        background=WHITE, foreground=TEXT, borderwidth=1, focuscolor=ACCENT)
        style.map('Secondary.TButton', background=[('active', '#E5EBE8')])
        style.configure('TCheckbutton', background=BG, foreground=TEXT, font=('Segoe UI', 10))
        style.map('TCheckbutton', background=[('active', BG)])
        outer = tk.Frame(root, bg=BG, padx=26, pady=18)
        outer.pack(fill='both', expand=True)
        tk.Label(outer, text='Servidor do laboratório', font=('Segoe UI', 19, 'bold'), fg=TEXT, bg=BG,
                 anchor='w').pack(fill='x')
        tk.Label(outer, text='EMQX e MySQL prontos com um clique', font=('Segoe UI', 10), fg=MUTED, bg=BG,
                 anchor='w').pack(fill='x', pady=(4, 14))
        card = tk.Frame(outer, bg=WHITE, highlightbackground='#DCE2E7', highlightthickness=1, padx=20, pady=15)
        card.pack(fill='x')
        tk.Label(card, text='ENDEREÇO IP', font=('Segoe UI', 9, 'bold'), fg=MUTED, bg=WHITE, anchor='w').pack(fill='x')
        tk.Label(card, textvariable=self.ip, font=('Consolas', 27, 'bold'), fg=TEXT, bg=WHITE,
                 anchor='w').pack(fill='x', pady=(3, 10))
        self.combo = ttk.Combobox(card, textvariable=self.adapter, state='disabled', takefocus=True)
        self.combo.pack(fill='x')
        self.combo.bind('<<ComboboxSelected>>', lambda event: self.refresh(False, keep=True))
        self.status_label = tk.Label(card, textvariable=self.status, font=('Segoe UI', 12, 'bold'), fg=MUTED,
                                     bg=WHITE, anchor='w')
        self.status_label.pack(fill='x', pady=(15, 5))
        self.detail_label = tk.Label(card, textvariable=self.details, font=('Segoe UI', 10), fg=MUTED, bg=WHITE,
                                     anchor='nw', justify='left', wraplength=480, height=3)
        self.detail_label.pack(fill='x')
        tk.Label(card, textvariable=self.ports, font=('Consolas', 10), fg=TEXT, bg=WHITE,
                 anchor='w').pack(fill='x', pady=(5, 0))
        self.network_check = ttk.Checkbutton(outer, text='Permitir conexão do M5 pela rede', variable=self.allow_network)
        self.network_check.pack(anchor='w', pady=(12, 10))
        self.primary = ttk.Button(outer, text='Iniciar laboratório e abrir Dashboard', style='Primary.TButton', command=self.start_lab)
        self.primary.pack(fill='x', pady=(0, 9))
        row = tk.Frame(outer, bg=BG)
        row.pack(fill='x')
        self.refresh_button = ttk.Button(row, text='Atualizar IP', style='Secondary.TButton',
                                         command=lambda: self.refresh(True, keep=True))
        self.refresh_button.pack(side='left', fill='x', expand=True, padx=(0, 5))
        self.stop_button = ttk.Button(row, text='Parar laboratório', style='Secondary.TButton', command=self.stop_lab)
        self.stop_button.pack(side='left', fill='x', expand=True, padx=(5, 0))
        row2 = tk.Frame(outer, bg=BG)
        row2.pack(fill='x', pady=(9, 0))
        self.copy_button = ttk.Button(row2, text='Copiar IP', style='Secondary.TButton', command=self.copy_ip)
        self.copy_button.pack(side='left', fill='x', expand=True, padx=(0, 5))
        self.dashboard_button = ttk.Button(row2, text='Abrir Dashboard', style='Secondary.TButton', command=self.open_dashboard)
        self.dashboard_button.pack(side='left', fill='x', expand=True, padx=5)
        self.password_button = ttk.Button(row2, text='Copiar senha admin', style='Secondary.TButton', command=self.copy_password)
        self.password_button.pack(side='left', fill='x', expand=True, padx=(5, 0))
        device_row = tk.Frame(outer, bg=BG)
        device_row.pack(fill='x', pady=(9, 0))
        self.m5_button = ttk.Button(device_row, text='Configurar Wi-Fi e perfil do M5 por USB',
                                    style='Secondary.TButton', command=self.open_m5_config)
        self.m5_button.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.athlete_button = ttk.Button(device_row, text='Ver dados do atleta',
                                        style='Secondary.TButton', command=self.open_athlete_data)
        self.athlete_button.pack(side='right', fill='x', expand=True)
        self.feedback_label = tk.Label(outer, textvariable=self.feedback, font=('Segoe UI', 10), fg=MUTED,
                                       bg=BG, justify='left', anchor='nw', wraplength=520, height=2)
        self.feedback_label.pack(fill='x', pady=(12, 0))
        footer = tk.Frame(outer, bg=BG)
        footer.pack(fill='x', pady=(4, 0))
        tk.Label(footer, text=f'v{VERSION} • Fechar mantém os serviços ligados.', font=('Segoe UI', 9), fg=MUTED,
                 bg=BG).pack(side='left')
        self.details_button = tk.Button(footer, text='Ver detalhes', font=('Segoe UI', 9, 'underline'), bg=BG,
                                        fg=ACCENT, relief='flat', cursor='hand2', command=self.open_details)
        self.details_button.pack(side='right')
        self.actions = (self.primary, self.refresh_button, self.stop_button, self.copy_button,
                        self.dashboard_button, self.password_button, self.network_check, self.m5_button)
        root.bind('<F5>', lambda event: self.refresh(False, keep=True))
        root.bind('<Configure>', self.resize)
        root.after(80, self.poll)
        root.after(150, lambda: self.refresh(False))

    def resize(self, event):
        if event.widget == self.root:
            self.detail_label.configure(wraplength=max(400, event.width - 100))
            self.feedback_label.configure(wraplength=max(440, event.width - 56))

    def selected_ip(self):
        index = self.combo.current()
        return self.interfaces[index].ip if 0 <= index < len(self.interfaces) else None

    def snapshot(self, save, selected):
        interfaces = detect_interfaces()
        chosen = next((item for item in interfaces if item.ip == selected), interfaces[0] if interfaces else None)
        pairs = port_pairs(self.folder)
        result = diagnose(chosen.ip, pairs) if chosen else diagnose_local(pairs)
        path = save_address(self.folder, result) if save and chosen else None
        return interfaces, chosen, result, path

    def dispatch(self, title, worker):
        if self.busy:
            return
        self.busy, self.last_error, self.error_kind = True, None, None
        for button in self.actions:
            button.configure(state='disabled')
        self.combo.configure(state='disabled')
        self.primary.configure(text='Aguarde…')
        self.status.set(title)
        self.status_label.configure(fg=MUTED)
        self.details.set('A janela continuará respondendo durante a operação.')
        self.feedback.set('Aguarde a conclusão antes de iniciar outra operação.')
        def run():
            try:
                self.events.put(('result', worker()))
            except Exception as error:
                LabController(self.folder).record_error(error, f'{title} (Painel {VERSION})')
                if isinstance(error, LabError):
                    message, kind = str(error), error.kind
                elif isinstance(error, PermissionError):
                    message, kind = 'Sem permissão para gravar. Mova o aplicativo para uma pasta sua.', 'permission'
                elif isinstance(error, ValueError):
                    message, kind = 'Configuração inválida. Confira os arquivos JSON antes de tentar novamente.', 'configuration'
                else:
                    message, kind = f'Não foi possível concluir ({type(error).__name__}). Consulte os detalhes.', 'operation'
                self.events.put(('error', (message, kind)))
        threading.Thread(target=run, daemon=True).start()

    def refresh(self, save, keep=False):
        selected = self.selected_ip() if keep else None
        self.dispatch('Verificando o servidor', lambda: (*self.snapshot(save, selected), None))

    def start_lab(self):
        selected, allow = self.selected_ip(), self.allow_network.get()
        def worker():
            controller = LabController(self.folder, lambda text: self.events.put(('progress', text)))
            result = controller.start(allow)
            return (*self.snapshot(True, selected), {'type': 'start', **result})
        self.dispatch('Iniciando o laboratório', worker)

    def stop_lab(self):
        selected = self.selected_ip()
        def worker():
            controller = LabController(self.folder, lambda text: self.events.put(('progress', text)))
            result = controller.stop()
            return (*self.snapshot(False, selected), {'type': 'stop', **result})
        self.dispatch('Parando o laboratório', worker)

    def poll(self):
        try:
            kind, value = self.events.get_nowait()
        except queue.Empty:
            self.root.after(80, self.poll)
            return
        if kind == 'progress':
            self.details.set(value)
            self.root.after(80, self.poll)
            return
        self.busy = False
        for button in self.actions:
            button.configure(state='normal')
        self.primary.configure(text='Iniciar laboratório e abrir Dashboard')
        self.stop_button.configure(state='normal' if initialized(self.folder) else 'disabled')
        self.password_button.configure(state='normal' if (self.folder / 'runtime/secrets.json').is_file() else 'disabled')
        self.copy_button.configure(state='disabled')
        self.dashboard_button.configure(state='disabled')
        if kind == 'result':
            self.interfaces, chosen, self.result, path, action = value
            self.ip.set(chosen.ip if chosen else 'Sem IP de rede')
            self.combo.configure(values=[f'{item.name} — {item.ip}' for item in self.interfaces],
                                 state='readonly' if chosen else 'disabled')
            if chosen:
                self.combo.current(self.interfaces.index(chosen))
                self.copy_button.configure(state='normal')
            else:
                self.adapter.set('Conecte este PC ao Wi-Fi ou Ethernet')
            state = self.result['state']
            if state == 'online':
                title, detail, color = 'Online — EMQX respondendo', 'MQTT e Dashboard responderam neste IP. O teste de conexão a partir do M5 ainda depende da placa.', GOOD
            elif state == 'mqtt_only':
                title, detail, color = 'MQTT online • Dashboard indisponível', 'Um broker MQTT respondeu, mas o Dashboard não foi identificado nas portas verificadas.', WARN
            elif state == 'local_only':
                title, detail, color = 'Pronto para usar neste PC', 'O Dashboard está disponível localmente. Para conectar o M5, marque a opção de rede e clique em iniciar.', WARN
                if self.allow_network.get():
                    detail = 'O MQTT respondeu apenas pelo acesso local. Confira a publicação das portas e o firewall para conectar o M5.'
                if not self.result['loopback']['dashboard_online']:
                    title, detail = 'MQTT disponível apenas neste PC', 'O MQTT respondeu por localhost, mas o Dashboard não foi identificado nas portas verificadas.'
            else:
                title, detail, color = 'Offline — servidor sem resposta', 'Clique em iniciar. O programa prepara os arquivos, inicia o Docker e aguarda o EMQX e o MySQL.', BAD
            if not chosen and state == 'offline':
                title, detail = 'Sem IP de rede', 'Conecte este PC à rede. Se as imagens já estiverem instaladas, o laboratório também pode iniciar localmente.'
            self.status.set(title)
            self.status_label.configure(fg=color)
            self.details.set(detail)
            self.ports.set(f"MQTT {self.result['mqtt_port']}     Dashboard {self.result['dashboard_port']}")
            self.dashboard_button.configure(state='normal' if self.result['dashboard_url'] else 'disabled')
            self.saved = path or self.saved
            if action and action['type'] == 'start':
                self.feedback.set('Laboratório iniciado. Login: admin. Use “Copiar senha admin” para entrar no Dashboard.')
                webbrowser.open(action['dashboard_url'])
            elif action and action['type'] == 'stop':
                self.feedback.set('Laboratório parado. Dados e configurações foram preservados.')
            elif path:
                self.feedback.set('IP atualizado na configuração. Wi-Fi e senhas existentes foram preservados.')
            else:
                self.feedback.set(f'Verificado às {datetime.now():%H:%M:%S}. Clique em iniciar para abrir o laboratório.')
        else:
            self.last_error, self.error_kind = value
            self.status.set({'docker_missing': 'Docker não encontrado',
                             'docker_not_ready': 'Docker ainda não está pronto',
                             'docker_network': 'Falha de rede no Docker',
                             'port_busy': 'Porta do laboratório ocupada',
                             'permission': 'Sem permissão para gravar'}.get(self.error_kind, 'Não foi possível concluir'))
            self.status_label.configure(fg=BAD)
            self.details.set(self.last_error)
            self.feedback.set('Clique em Instalar Docker para a instalação inicial.' if self.error_kind == 'docker_missing'
                              else 'Clique em Ver detalhes para consultar o registro da operação.')
        self.details_button.configure(text='Instalar Docker' if self.error_kind == 'docker_missing' else 'Ver detalhes')
        self.root.after(80, self.poll)

    def copy_ip(self):
        if self.result and self.result['ip']:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.result['ip'])
            self.feedback.set('IP copiado para a área de transferência.')

    def copy_password(self):
        try:
            password = read_json(self.folder / 'runtime/secrets.json')['dashboard']
            self.root.clipboard_clear()
            self.root.clipboard_append(password)
            self.feedback.set('Senha copiada. No Dashboard, use o usuário admin e cole a senha.')
        except (OSError, ValueError, KeyError):
            self.feedback.set('A senha desta instalação ainda não está disponível.')

    def open_dashboard(self):
        if self.result and self.result['dashboard_url']:
            webbrowser.open(self.result['dashboard_url'])

    def open_m5_config(self):
        from configurar_m5 import ConfigWindow
        window = getattr(self, 'm5_window', None)
        if window is not None and window.winfo_exists():
            window.lift()
            return
        self.m5_window = tk.Toplevel(self.root)
        ConfigWindow(self.m5_window, self.folder)

    def open_athlete_data(self):
        from dados_atleta import AthleteWindow
        window = getattr(self, 'athlete_window', None)
        if window is not None and window.winfo_exists():
            window.lift()
            return
        self.athlete_window = tk.Toplevel(self.root)
        AthleteWindow(self.athlete_window, self.folder)

    def open_details(self):
        if self.error_kind == 'docker_missing':
            webbrowser.open(DOCKER_DOWNLOAD)
            return
        log = self.folder / 'runtime/painel-acao.log'
        if log.is_file():
            os.startfile(log)
        else:
            self.feedback.set('Nenhuma operação de iniciar ou parar foi registrada nesta pasta.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pasta', type=Path, help='Pasta da configuração do laboratório')
    parser.add_argument('--diagnostico', type=Path, help='Salva diagnóstico sem abrir a janela ou alterar a configuração')
    parser.add_argument('--preparar', action='store_true', help='Prepara os arquivos sem iniciar serviços; exige --pasta')
    parser.add_argument('--dados-atleta', action='store_true', help='Abre diretamente a tela de leituras do M5')
    args = parser.parse_args()
    executable = sys.executable if getattr(sys, 'frozen', False) else __file__
    folder = args.pasta or find_folder(executable)
    if not args.pasta and getattr(sys, 'frozen', False) and not (folder / 'compose.yaml').exists():
        folder = folder / 'laboratorio'
    if args.preparar:
        if not args.pasta:
            parser.error('--preparar exige uma pasta explícita em --pasta')
        with operation_lock(folder):
            prepare_files(folder, network_enabled(folder))
        return
    if args.diagnostico:
        interfaces = detect_interfaces()
        result = diagnose(interfaces[0].ip, port_pairs(folder)) if interfaces else diagnose_local(port_pairs(folder))
        atomic_json(args.diagnostico, result)
        return
    if os.name == 'nt':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    if args.dados_atleta:
        from dados_atleta import AthleteWindow
        ttk.Style(root).theme_use('clam')
        AthleteWindow(root, folder)
    else:
        App(root, folder)
    root.mainloop()


if __name__ == '__main__':
    main()
