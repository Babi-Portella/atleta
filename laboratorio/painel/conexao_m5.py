"""Confere USB, Wi-Fi, MQTT e uma leitura nova no MySQL, sem publicar dados de teste."""
from pathlib import Path
import json
import re
import time
from datetime import datetime, timezone

from dados_atleta import fetch_readings, DataError
from m5_serial import open_serial, send_configuration
from rede import read_json, atomic_json, detect_interfaces, inspect_pair, save_address


def prepare_target(folder):
    folder = Path(folder)
    settings = read_json(folder / 'runtime/settings.json', {})
    if not all(settings.get(key) for key in ('mqtt_port', 'dashboard_port')):
        raise ValueError('Clique primeiro em Iniciar laboratório no painel principal.')
    if settings.get('bind') == '127.0.0.1':
        raise ValueError('Marque Permitir conexão do M5 pela rede e clique em Iniciar laboratório.')
    interfaces = [i for i in detect_interfaces() if not i.virtual]
    if not interfaces:
        raise ValueError('O computador está sem IP de rede disponível. Conecte-o à rede e tente novamente.')
    previous = read_json(folder / 'config.local.json', {}).get('mqtt_host')
    chosen = next((i for i in interfaces if i.ip == previous), interfaces[0])
    pair = settings['mqtt_port'], settings['dashboard_port']
    status = inspect_pair(chosen.ip, pair)
    if not status['mqtt_online'] or not status['dashboard_online']:
        raise ValueError('O servidor do laboratório não respondeu no IP deste PC. Clique em Iniciar laboratório e confira o IP selecionado no painel.')
    status.update(ip=chosen.ip, state='online', checked_at=datetime.now(timezone.utc).isoformat())
    save_address(folder, status)
    return {'host': chosen.ip, 'port': pair[0]}


def observe(line, state):
    if line.startswith('STATUS '):
        values = dict(re.findall(r'(\w+)=([^\s]+)', line))
        for key in ('configured', 'wifi', 'mqtt', 'imu'):
            if values.get(key) in ('0', '1'):
                state[key] = values[key] == '1'
        state['usb_response'] = True
    elif line.startswith('INVENTORY '):
        try:
            data = json.loads(line[10:])
            for key in ('wifi_status_code', 'wifi_disconnect_reason', 'wifi_ip', 'mqtt_host', 'mqtt_port'):
                if type(data.get(key)) in (str, int):
                    state[key] = data[key]
            if type(data.get('wifi_status_code')) is int:
                state['wifi'] = data['wifi_status_code'] == 3
            state['usb_response'] = True
        except (ValueError, TypeError, AttributeError):
            pass
    elif line.startswith('MQTT_ERROR code='):
        try: state['mqtt_error'] = int(line.split('=', 1)[1])
        except ValueError: pass
    elif line == 'MQTT_CONNECTED':
        state.update(mqtt=True, mqtt_error=0, usb_response=True)
    elif line.startswith('TELEMETRY '):
        try:
            data = json.loads(line[10:])
            if (data.get('source') == 'device' and isinstance(data.get('boot_id'), str)
                    and type(data.get('sample_seq')) is int):
                state['samples'].add((data['boot_id'], data['sample_seq']))
                state['usb_response'] = True
                if type(data.get('mqtt_connected')) is bool:
                    state['mqtt'] = data['mqtt_connected']
        except (ValueError, TypeError, AttributeError):
            pass


def persisted_match(rows, samples):
    for row in rows:
        payload = row.get('payload', {})
        if (payload.get('source') == 'device' and row.get('age_seconds', 999999) <= 10
                and (payload.get('boot_id'), payload.get('sample_seq')) in samples):
            return row['id']
    return None


def conclusion(state, target):
    if state.get('mysql_row_id') is not None:
        return 'Conexão confirmada: M5 no Wi-Fi, leitura nova gravada no MySQL. Abra Ver dados do atleta.'
    if not state.get('usb_response'):
        return 'A configuração foi enviada, mas o M5 não respondeu à conferência. Confira a porta USB e tente novamente.'
    if state.get('wifi') is False:
        return 'M5 respondeu por USB, mas não entrou no Wi-Fi. Confira o nome exato, a senha e a disponibilidade da rede em 2,4 GHz.'
    if state.get('wifi') is not True:
        return 'O M5 respondeu, mas não foi possível confirmar o Wi-Fi. Tente enviar novamente e aguarde a conferência.'
    if state.get('mqtt_host') and (state['mqtt_host'] != target['host'] or state.get('mqtt_port') != target['port']):
        return 'O M5 ainda informa outro endereço de servidor. Atualize o IP no painel e envie novamente por USB.'
    if not state.get('mqtt'):
        if state.get('mqtt_error') in (4, 5):
            return 'M5 entrou no Wi-Fi, mas o EMQX recusou o login. Inicie o laboratório desta pasta e envie novamente a configuração por USB.'
        return f"M5 entrou no Wi-Fi, mas não conectou ao servidor {target['host']}:{target['port']}. Confira acesso entre as redes, IP e firewall do PC."
    if state.get('database_error'):
        return 'M5 conectado ao Wi-Fi e MQTT, mas a consulta ao MySQL falhou. Confira se o laboratório está iniciado e veja os detalhes.'
    return 'M5 conectado ao Wi-Fi e MQTT, mas nenhuma leitura nova foi confirmada no MySQL. Confira a regra de persistência e os detalhes do servidor.'


def verify_connection(folder, port, target, progress=None, timeout=30):
    progress = progress or (lambda message: None)
    state = {'usb_response': False, 'samples': set()}
    progress('Configuração enviada. Conferindo Wi-Fi, MQTT e uma leitura nova no banco…')
    with open_serial(port) as connection:
        time.sleep(3)
        connection.reset_input_buffer()
        deadline = time.monotonic() + timeout
        next_query = next_db = 0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_query:
                connection.write(b'STATUS\nINVENTORY\n')
                connection.flush()
                next_query = now + 3
            line = connection.readline().decode('utf-8', errors='replace').strip()
            observe(line, state)
            if state['samples'] and now >= next_db:
                next_db = now + 2
                try:
                    match = persisted_match(fetch_readings(folder, 20), state['samples'])
                    state['database_error'] = False
                    if match is not None:
                        state['mysql_row_id'] = match
                        break
                except DataError:
                    state['database_error'] = True
    result = conclusion(state, target)
    safe = {key: value for key, value in state.items() if key != 'samples'}
    safe.update(checked_at_utc=datetime.now(timezone.utc).isoformat(), target=target,
                usb_samples_observed=len(state['samples']), message=result,
                live_data_confirmed=state.get('mysql_row_id') is not None)
    atomic_json(Path(folder) / 'runtime/diagnostico-conexao-m5.json', safe)
    from servidor import LabController
    LabController(folder).log('Diagnóstico do M5: ' + json.dumps(safe, ensure_ascii=False))
    return result


def configure_and_check(folder, port, progress=None):
    progress = progress or (lambda message: None)
    progress('Conferindo o IP e o servidor deste computador…')
    target = prepare_target(folder)
    progress('Enviando rede, perfil e endereço ao M5 por USB…')
    send_configuration(folder, port)
    try:
        return verify_connection(folder, port, target, progress)
    except OSError:
        return 'Configuração enviada, mas a porta USB ficou indisponível após o reinício. Reconecte o cabo e tente novamente.'
