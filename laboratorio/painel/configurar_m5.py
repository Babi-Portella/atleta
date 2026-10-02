"""Configuração local de Wi-Fi e perfil opcional do M5, sem imprimir credenciais."""
import argparse
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import queue
import threading

from rede import atomic_json, read_json, port
from m5_serial import device_ports
from conexao_m5 import configure_and_check
from wifi_pc import detect_wifi, autofill


def save_device_settings(folder, ssid, password, weight='', step_length='', met='', athlete_id=''):
    folder = Path(folder)
    if not ssid or len(ssid.encode('utf-8')) > 32:
        raise ValueError('Informe o nome da rede Wi-Fi, com até 32 bytes.')
    if password and not (8 <= len(password.encode('utf-8')) <= 63 or
                         len(password) == 64 and all(c in '0123456789abcdefABCDEF' for c in password)):
        raise ValueError('A senha Wi-Fi deve ter 8 a 63 bytes, ou 64 dígitos hexadecimais. Rede aberta pode ficar sem senha.')
    config = read_json(folder / 'config.local.json', {})
    if not isinstance(config, dict):
        raise ValueError('O arquivo de configuração precisa ser um objeto JSON.')
    profile = {}
    for key, raw, minimum, maximum in (
            ('weight_kg', weight, 10, 400), ('step_length_m', step_length, 0.1, 2.5),
            ('activity_met', met, 1, 25), ('athlete_id', athlete_id, 1, 2147483647)):
        if not raw.strip():
            profile[key] = None
            continue
        try:
            number = float(raw.replace(',', '.'))
        except ValueError:
            raise ValueError('Confira os números do perfil opcional.') from None
        if not minimum <= number <= maximum or key == 'athlete_id' and number != int(number):
            raise ValueError('Um número do perfil está fora do intervalo permitido.')
        profile[key] = int(number) if key == 'athlete_id' else number
    config.update(wifi_ssid=ssid, wifi_password=password, device_id='m5-atleta-01', **profile)
    config.setdefault('mqtt_host', '')
    config.setdefault('mqtt_port', 1883)
    if port(config['mqtt_port'], None) is None:
        raise ValueError('A porta MQTT na configuração é inválida.')
    atomic_json(folder / 'config.local.json', config)
    return config


class ConfigWindow:
    def __init__(self, root, folder, ssid=''):
        self.root, self.folder = root, Path(folder)
        self.saved = False
        self.busy = False
        self.detecting = False
        self.closed = False
        self.events = queue.Queue()
        config = read_json(self.folder / 'config.local.json', {})
        root.title('M5 — configurar Wi-Fi')
        root.configure(bg='#F3F5F7')
        root.minsize(480, 440)
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Conectar o M5 ao Wi-Fi', font=('Segoe UI', 17, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='Use uma rede de 2,4 GHz acessível ao servidor.',
                  font=('Segoe UI', 10)).pack(anchor='w', pady=(6, 20))
        self.ssid = tk.StringVar(value=ssid or config.get('wifi_ssid', ''))
        self.password = tk.StringVar(value=config.get('wifi_password', ''))
        for label, variable, mask in (('Nome da rede', self.ssid, ''), ('Senha da rede', self.password, '*')):
            ttk.Label(outer, text=label, font=('Segoe UI', 10)).pack(anchor='w', pady=(8, 4))
            entry = ttk.Entry(outer, textvariable=variable, show=mask, font=('Segoe UI', 12))
            entry.pack(fill='x', ipady=5)
            if mask:
                self.password_entry = entry
        self.show_password = tk.BooleanVar(value=False)
        ttk.Checkbutton(outer, text='Mostrar senha', variable=self.show_password,
                        command=lambda: self.password_entry.configure(show='' if self.show_password.get() else '*')).pack(anchor='w', pady=8)
        self.detect_button = ttk.Button(outer, text='Detectar Wi-Fi deste computador', command=self.detect_network)
        self.detect_button.pack(anchor='w', pady=(0, 4))
        self.wifi_hint = tk.StringVar(value='Consultando a conexão Wi-Fi do computador…')
        ttk.Label(outer, textvariable=self.wifi_hint, wraplength=430, font=('Segoe UI', 9)).pack(fill='x')
        self.profile = {}
        panel = ttk.LabelFrame(outer, text='Perfil opcional — pode ficar em branco', padding=12)
        panel.pack(fill='x', pady=12)
        for row, (key, label) in enumerate((('weight_kg', 'Peso (kg)'), ('step_length_m', 'Comprimento de um passo (m)'),
                                            ('activity_met', 'Intensidade da atividade (MET)'), ('athlete_id', 'ID do atleta no projeto'))):
            value = config.get(key)
            variable = tk.StringVar(value='' if value is None else str(value))
            self.profile[key] = variable
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=4)
            ttk.Entry(panel, textvariable=variable, width=13).grid(row=row, column=1, sticky='ew', pady=4)
        panel.columnconfigure(1, weight=1)
        ttk.Label(outer, text='Sem passo informado, distância fica indisponível.\nSem peso e MET, calorias ficam indisponíveis.',
                  font=('Segoe UI', 9)).pack(anchor='w')
        self.feedback = tk.StringVar(value='A senha será salva só na configuração local do laboratório.')
        ttk.Label(outer, textvariable=self.feedback, wraplength=430, font=('Segoe UI', 10)).pack(fill='x', pady=14)
        self.save_button = ttk.Button(outer, text='Salvar configuração', command=self.save)
        self.save_button.pack(fill='x', ipady=10)
        usb_row = ttk.Frame(outer)
        usb_row.pack(fill='x', pady=(12, 0))
        ports = device_ports()
        self.usb_port = tk.StringVar(value=ports[0] if len(ports) == 1 else '')
        ttk.Label(usb_row, text='Porta do M5').pack(side='left')
        ttk.Combobox(usb_row, textvariable=self.usb_port, values=ports, width=9).pack(side='left', padx=10)
        self.send_button = ttk.Button(usb_row, text='Enviar ao M5 por USB', command=self.send)
        self.send_button.pack(side='right', ipady=6)
        root.bind('<Return>', lambda event: self.save())
        self.poll_id = root.after(100, self.poll)
        root.after(150, self.detect_network)
        root.bind('<Destroy>', self.on_destroy, add='+')
        self.password_entry.focus_set()

    def on_destroy(self, event):
        if event.widget is self.root:
            self.closed = True
            self.root.after_cancel(self.poll_id)

    def detect_network(self):
        if self.closed or self.busy or self.detecting:
            return
        self.detecting = True
        self.detect_button.configure(state='disabled')
        self.send_button.configure(state='disabled')
        baseline = self.ssid.get(), self.password.get()
        def worker():
            self.events.put(('wifi', (baseline, detect_wifi())))
        threading.Thread(target=worker, daemon=True).start()

    def apply_network(self, baseline, result):
        self.wifi_hint.set(result['message'])
        detected = result.get('ssid')
        if detected and (self.ssid.get(), self.password.get()) == baseline:
            ssid, password = autofill(*baseline, detected)
            self.ssid.set(ssid)
            self.password.set(password)
            if detected != baseline[0]:
                self.wifi_hint.set('Nome do Wi-Fi preenchido automaticamente. Informe a senha dessa rede abaixo; ela deve estar disponível em 2,4 GHz.')
            else:
                self.wifi_hint.set('A rede salva é a mesma do computador. Nome e senha do projeto mantidos; confirme em Enviar ao M5 por USB.')

    def save(self):
        try:
            save_device_settings(self.folder, self.ssid.get(), self.password.get(),
                                 self.profile['weight_kg'].get(), self.profile['step_length_m'].get(),
                                 self.profile['activity_met'].get(), self.profile['athlete_id'].get())
        except (ValueError, OSError) as error:
            self.feedback.set(str(error) if isinstance(error, ValueError) else 'Não foi possível salvar nesta pasta.')
            return
        self.saved = True
        self.feedback.set('Configuração salva neste computador. Clique em Enviar ao M5 por USB para aplicá-la na placa.')

    def send(self):
        if self.busy or self.detecting:
            return
        self.saved = False
        self.save()
        if not self.saved:
            return
        if not self.usb_port.get():
            self.feedback.set('Conecte o M5 por USB e informe a porta, por exemplo COM4.')
            return
        self.busy = True
        self.save_button.configure(state='disabled')
        self.send_button.configure(state='disabled')
        self.detect_button.configure(state='disabled')
        self.feedback.set('Enviando ao M5. Aguarde a confirmação da placa…')
        port_name = self.usb_port.get()
        def worker():
            try:
                result = configure_and_check(self.folder, port_name,
                            progress=lambda message: self.events.put(('progress', message)))
                self.events.put(('done', result))
            except ValueError as error:
                self.events.put(('done', str(error)))
            except Exception:
                self.events.put(('done', 'Não foi possível concluir a configuração USB. Confira o cabo e feche outros monitores seriais.'))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            kind, message = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            if kind == 'wifi':
                self.apply_network(*message)
                self.detecting = False
                self.detect_button.configure(state='normal')
                self.send_button.configure(state='normal')
            elif kind == 'progress':
                self.feedback.set(message)
            else:
                self.busy = False
                self.save_button.configure(state='normal')
                self.send_button.configure(state='normal')
                self.detect_button.configure(state='normal')
                self.feedback.set(message)
        self.poll_id = self.root.after(100, self.poll)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pasta', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--ssid', default='')
    args = parser.parse_args()
    root = tk.Tk()
    ConfigWindow(root, args.pasta, args.ssid)
    root.mainloop()


if __name__ == '__main__':
    main()
