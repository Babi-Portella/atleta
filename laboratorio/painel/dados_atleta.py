"""Consulta somente leituras físicas no MySQL local e apresenta o histórico do M5."""
from datetime import timezone
import json
import math
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import pymysql
from rede import read_json, port

DEVICE = 'm5-atleta-01'
BG, WHITE, TEXT, MUTED = '#F3F5F7', '#FFFFFF', '#17212B', '#52616F'
GOOD, WARN, BAD = '#166448', '#865500', '#A52D36'
REFRESH_MS, RECENT_SECONDS = 2000, 10


class DataError(Exception):
    pass


def fetch_readings(folder, limit=120):
    """Usa a conta SELECT do kit; nunca conecta o MySQL pela rede do atleta."""
    folder = Path(folder)
    try:
        settings = read_json(folder / 'runtime/settings.json')
        secrets = read_json(folder / 'runtime/secrets.json')
        password = secrets.get('mysql_reader')
        db_port = port(settings.get('mysql_port'), None)
    except (OSError, ValueError):
        raise DataError('Não foi possível ler a configuração local do laboratório.') from None
    if not password or db_port is None:
        raise DataError('Inicie o laboratório neste computador antes de consultar os dados.')
    if type(limit) is not int or not 1 <= limit <= 120:
        raise ValueError('O histórico deve ter entre 1 e 120 leituras.')
    try:
        with pymysql.connect(host='127.0.0.1', port=db_port, user='lab_reader', password=password,
                             database='athlete_lab', charset='utf8mb4', autocommit=True,
                             connect_timeout=3, read_timeout=3, write_timeout=3,
                             init_command="SET time_zone = '+00:00'",
                             cursorclass=pymysql.cursors.DictCursor) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""SELECT id, received_at, payload,
                    TIMESTAMPDIFF(MICROSECOND, received_at, UTC_TIMESTAMP(3)) / 1000000 AS age_seconds
                    FROM telemetry WHERE mqtt_username=%s AND source=%s
                    ORDER BY received_at DESC, id DESC LIMIT %s""", (DEVICE, 'device', limit))
                rows = cursor.fetchall()
    except (pymysql.MySQLError, OSError):
        raise DataError('Não foi possível consultar o MySQL. Confira se o laboratório está iniciado neste computador.') from None
    try:
        for row in rows:
            row['payload'] = json.loads(row['payload'])
            if not isinstance(row['payload'], dict):
                raise ValueError('Formato inesperado')
            row['received_at'] = row['received_at'].replace(tzinfo=timezone.utc)
            row['age_seconds'] = max(0.0, float(row['age_seconds']))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise DataError('Uma leitura armazenada possui formato inválido.') from None
    return rows


def number(value, decimals=0, unit=''):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 'Indisponível'
    return f'{value:.{decimals}f}'.replace('.', ',') + unit


def duration(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return 'Indisponível'
    seconds = int(value)
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


def distance(value_km):
    if number(value_km) == 'Indisponível' or value_km < 0:
        return 'Indisponível'
    if value_km >= 1:
        return number(value_km, 3, ' km')
    meters = number(value_km * 1000, 3).rstrip('0').rstrip(',')
    return meters + ' m'


def metric_values(payload):
    lat, lon = payload.get('latitude'), payload.get('longitude')
    gps = 'Indisponível' if any(number(v) == 'Indisponível' for v in (lat, lon)) else f'{lat:.5f}, {lon:.5f}'
    return {
        'passos': number(payload.get('passos')),
        'tempo': duration(payload.get('duracao_s')),
        'bateria': number(payload.get('battery_percent_estimate'), unit='%'),
        'distancia': distance(payload.get('distancia_km')),
        'calorias': number(payload.get('calorias_kcal'), 1, ' kcal'),
        'ritmo': number(payload.get('ritmo_min_km'), 2, ' min/km'),
        'bpm': number(payload.get('bpm'), unit=' bpm'),
        'pele': number(payload.get('temperatura_pele_c'), 1, ' °C'),
        'gps': gps,
    }


def freshness(age):
    return ('Recebendo dados', GOOD) if age <= RECENT_SECONDS else ('Sem dados recentes — exibindo a última leitura salva', WARN)


class AthleteWindow:
    def __init__(self, root, folder):
        self.root, self.folder = root, Path(folder)
        self.rows, self.events = [], queue.Queue()
        self.busy, self.closed, self.error = False, False, None
        self.loaded_at, self.last_ids = 0.0, None
        self.auto = tk.BooleanVar(value=True)
        self.metrics = {key: tk.StringVar(value='Indisponível') for key in metric_values({})}
        self.status = tk.StringVar(value='Consultando dados salvos…')
        self.updated = tk.StringVar(value='Aguardando a primeira consulta ao laboratório.')
        self.identity = tk.StringVar(value=f'Dispositivo {DEVICE}')
        self.connection = tk.StringVar(value='')
        root.title('Atleta IP — dados do atleta')
        root.configure(bg=BG)
        root.geometry('930x750')
        root.minsize(800, 660)
        style = ttk.Style(root)
        style.configure('Athlete.Treeview', rowheight=26, font=('Segoe UI', 10))
        style.configure('Athlete.Treeview.Heading', font=('Segoe UI', 10, 'bold'))
        outer = tk.Frame(root, bg=BG, padx=22, pady=18)
        outer.pack(fill='both', expand=True)
        header = tk.Frame(outer, bg=BG)
        header.pack(fill='x')
        tk.Label(header, text='Dados do atleta', font=('Segoe UI', 21, 'bold'), fg=TEXT, bg=BG).pack(side='left')
        self.refresh_button = ttk.Button(header, text='Atualizar agora', command=self.refresh)
        self.refresh_button.pack(side='right', ipady=6)
        ttk.Checkbutton(header, text='Atualizar a cada 2 s', variable=self.auto).pack(side='right', padx=14)
        tk.Label(outer, textvariable=self.identity, bg=BG, fg=MUTED, font=('Segoe UI', 10), anchor='w').pack(fill='x', pady=(4, 10))
        self.status_label = tk.Label(outer, textvariable=self.status, bg=BG, fg=MUTED, font=('Segoe UI', 12, 'bold'), anchor='w')
        self.status_label.pack(fill='x')
        tk.Label(outer, textvariable=self.updated, bg=BG, fg=MUTED, font=('Segoe UI', 10), anchor='w', wraplength=850).pack(fill='x', pady=(4, 12))
        cards = tk.Frame(outer, bg=BG)
        cards.pack(fill='x')
        definitions = [('passos', 'PASSOS', 'Estimativa experimental'), ('tempo', 'TEMPO ATIVO', 'Tempo da sessão'),
                       ('bateria', 'BATERIA', 'Percentual estimado'), ('distancia', 'DISTÂNCIA', 'Estimativa por passos'),
                       ('calorias', 'CALORIAS', 'Estimativa por peso e MET'), ('ritmo', 'RITMO MÉDIO', 'Baseado na distância estimada'),
                       ('bpm', 'BATIMENTOS', 'Requer sensor de pulso'), ('pele', 'TEMPERATURA DA PELE', 'Requer sensor externo'),
                       ('gps', 'LOCALIZAÇÃO GPS', 'Requer módulo GPS')]
        self.cards = []
        for i, (key, label, note) in enumerate(definitions):
            card = tk.Frame(cards, bg=WHITE, padx=14, pady=7, highlightbackground='#DCE2E7', highlightthickness=1)
            card.grid(row=i // 3, column=i % 3, sticky='nsew', padx=(0, 10 if i % 3 < 2 else 0), pady=(0, 9))
            self.cards.append(card)
            tk.Label(card, text=label, bg=WHITE, fg=MUTED, font=('Segoe UI', 9), anchor='w').pack(fill='x')
            tk.Label(card, textvariable=self.metrics[key], bg=WHITE, fg=TEXT,
                     font=('Segoe UI', 17 if key != 'gps' else 12, 'bold'), anchor='w').pack(fill='x', pady=(3, 2))
            tk.Label(card, text=note, bg=WHITE, fg=MUTED, font=('Segoe UI', 9), anchor='w').pack(fill='x')
        for col in range(3):
            cards.columnconfigure(col, weight=1, uniform='cards')
        tk.Label(outer, textvariable=self.connection, bg=BG, fg=MUTED, font=('Segoe UI', 10), anchor='w', wraplength=850).pack(fill='x', pady=(0, 8))
        tk.Label(outer, text='Histórico recente • até 120 leituras salvas', bg=BG, fg=TEXT,
                 font=('Segoe UI', 11, 'bold'), anchor='w').pack(fill='x', pady=(0, 6))
        self.help_label = tk.Label(outer, text='Selecione uma leitura e pressione Enter para ver todos os campos. Horários de recebimento neste computador.',
                                  bg=BG, fg=MUTED, font=('Segoe UI', 9), anchor='w', justify='left', wraplength=740)
        self.help_label.pack(side='bottom', fill='x', pady=(8, 0))
        table = tk.Frame(outer, bg=BG)
        table.pack(fill='both', expand=True)
        columns = [('hora', 'Recebido (hora local)', 158), ('passos', 'Passos', 62), ('bateria', 'Bateria', 65),
                   ('x', 'X (g)', 73), ('y', 'Y (g)', 73), ('z', 'Z (g)', 73)]
        self.tree = ttk.Treeview(table, columns=[c[0] for c in columns], show='headings', height=5, style='Athlete.Treeview')
        for key, label, width in columns:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=width, anchor='w' if key == 'hora' else 'e')
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.bind('<Return>', self.show_reading)
        self.tree.bind('<Double-1>', self.show_reading)
        root.bind('<F5>', lambda event: self.refresh())
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Destroy>', self.on_destroy, add='+')
        self.poll_id = root.after(100, self.poll)
        self.tick_id = root.after(1000, self.tick)
        self.refresh()

    def refresh(self):
        if self.busy or self.closed:
            return
        self.busy = True
        self.refresh_button.state(['disabled'])
        def worker():
            try:
                self.events.put((fetch_readings(self.folder), None))
            except DataError as error:
                self.events.put((None, str(error)))
            except Exception:
                self.events.put((None, 'Não foi possível carregar as leituras. Tente atualizar novamente.'))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            rows, self.error = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.refresh_button.state(['!disabled'])
            if rows is not None:
                self.rows, self.loaded_at = rows, time.monotonic()
                self.render()
            self.render_status()
        self.poll_id = self.root.after(100, self.poll)

    def tick(self):
        if self.closed:
            return
        self.render_status()
        if self.auto.get() and time.monotonic() - self.loaded_at >= REFRESH_MS / 1000:
            self.refresh()
        self.tick_id = self.root.after(1000, self.tick)

    def render_status(self):
        if self.error:
            self.status.set('Consulta indisponível — os valores anteriores podem estar desatualizados')
            self.status_label.configure(fg=BAD)
            self.updated.set(self.error)
        elif self.rows:
            latest = self.rows[0]
            age = latest['age_seconds'] + max(0, time.monotonic() - self.loaded_at)
            label, color = freshness(age)
            if not self.auto.get():
                label, color = 'Atualização pausada — exibindo a última consulta', WARN
            self.status.set(label)
            self.status_label.configure(fg=color)
            stamp = latest['received_at'].astimezone().strftime('%d/%m/%Y às %H:%M:%S')
            self.updated.set(f'Última leitura salva: {stamp} • há {int(age)} s')
        elif not self.busy:
            self.status.set('Ainda não há leituras deste M5')
            self.status_label.configure(fg=WARN)
            self.updated.set('Inicie o laboratório e conecte o M5 ao Wi-Fi. As leituras aparecerão aqui quando forem salvas.')

    def render(self):
        latest = self.rows[0]['payload'] if self.rows else {}
        for key, value in metric_values(latest).items():
            self.metrics[key].set(value)
        athlete = latest.get('athlete_id')
        self.identity.set(f'Dispositivo {DEVICE} • ' + (f'Atleta ID {athlete}' if athlete is not None else 'ID do atleta não informado'))
        session = 'Ativa' if latest.get('sessao_ativa') is True else 'Pausada' if latest.get('sessao_ativa') is False else 'Indisponível'
        self.connection.set(f"Na última leitura: sessão {session.lower()} • Wi-Fi {latest.get('wifi', 'indisponível')} • Bluetooth {latest.get('bluetooth', 'indisponível')}")
        ids = tuple(str(row['id']) for row in self.rows)
        if ids == self.last_ids:
            return
        position, selection = self.tree.yview(), self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in self.rows:
            p = row['payload']
            self.tree.insert('', 'end', iid=str(row['id']), values=(row['received_at'].astimezone().strftime('%d/%m %H:%M:%S'),
                             number(p.get('passos')), number(p.get('battery_percent_estimate'), unit='%'),
                             *[number(p.get('accel_' + axis + '_g'), 3) for axis in 'xyz']))
        for item in selection:
            if self.tree.exists(item):
                self.tree.selection_add(item)
        if position:
            self.tree.yview_moveto(position[0])
        self.last_ids = ids

    def show_reading(self, event=None):
        selected = self.tree.selection()
        row = next((r for r in self.rows if selected and str(r['id']) == selected[0]), None)
        if row is None:
            return
        from tkinter.scrolledtext import ScrolledText
        window = tk.Toplevel(self.root)
        window.title('Leitura salva — todos os campos')
        window.geometry('680x620')
        content = ScrolledText(window, wrap='word', font=('Consolas', 11), padx=14, pady=14)
        content.pack(fill='both', expand=True)
        content.insert('1.0', json.dumps(row['payload'], ensure_ascii=False, indent=2))
        content.configure(state='disabled')

    def on_destroy(self, event):
        if event.widget == self.root:
            self.closed = True
            for callback in (self.poll_id, self.tick_id):
                self.root.after_cancel(callback)

    def close(self):
        self.closed = True
        for callback in (self.poll_id, self.tick_id):
            self.root.after_cancel(callback)
        self.root.destroy()
