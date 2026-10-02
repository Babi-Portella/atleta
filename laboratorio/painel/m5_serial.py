"""Comunicação USB com o firmware do laboratório; não grava imagens nem imprime senhas."""
import json
from pathlib import Path
import time

import serial
from serial.tools import list_ports
from rede import read_json, port as valid_port


def device_ports():
    return [item.device for item in list_ports.comports()
            if item.vid == 0x1A86 and item.pid == 0x55D4]


def open_serial(port):
    return serial.Serial(port, baudrate=115200, timeout=0.5, write_timeout=3)


def configuration_payload(folder):
    folder = Path(folder)
    config = read_json(folder / 'config.local.json')
    if config.get('device_id') != 'm5-atleta-01':
        raise ValueError('O ID deste laboratório deve ser m5-atleta-01.')
    if not config.get('wifi_ssid'):
        raise ValueError('Salve primeiro o nome e a senha da rede Wi-Fi.')
    host = config.get('mqtt_host', '')
    if not host or host in ('localhost', '127.0.0.1', '0.0.0.0') or any(c in host for c in '/ :\r\n'):
        raise ValueError('Inicie o laboratório ou atualize o IP antes de enviar ao M5.')
    if valid_port(config.get('mqtt_port'), None) is None:
        raise ValueError('A porta MQTT é inválida.')
    password = config.get('mqtt_password')
    if not password:
        password = read_json(folder / 'runtime/secrets.json').get('m5-atleta-01')
    if not password:
        raise ValueError('A credencial MQTT do M5 ainda não foi preparada.')
    config.update(mqtt_username='m5-atleta-01', mqtt_password=password)
    encoded = ('CONFIG ' + json.dumps(config, separators=(',', ':')) + '\n').encode('utf-8')
    if len(encoded) > 2048:
        raise ValueError('A configuração excede o limite da placa.')
    return encoded


def send_configuration(folder, port):
    encoded = configuration_payload(folder)
    with open_serial(port) as connection:
        time.sleep(3)
        connection.reset_input_buffer()
        connection.write(encoded)
        connection.flush()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            line = connection.readline().decode('utf-8', errors='replace').strip()
            if line == 'CONFIG_OK':
                return 'Configuração enviada. O M5 está reiniciando para conectar ao Wi-Fi e ao servidor.'
            if line.startswith('CONFIG_ERROR'):
                raise ValueError('A placa recusou a configuração: ' + line)
    raise ValueError('O firmware do laboratório não confirmou o recebimento. Confira a porta e o programa gravado no M5.')
