"""Detecção local, diagnóstico MQTT/EMQX e atualização restrita do endereço."""
from __future__ import annotations

import concurrent.futures
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Interface:
    ip: str
    name: str
    gateway: bool = False
    metric: int = 9999
    virtual: bool = False


def valid_ip(value):
    try:
        ip = ipaddress.IPv4Address(value)
        return not (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast
                    or value == '255.255.255.255')
    except (ipaddress.AddressValueError, TypeError):
        return False


def parse_interfaces(records):
    if isinstance(records, dict):
        records = [records]
    result = {}
    for record in records or []:
        ip = str(record.get('ip', ''))
        if not valid_ip(ip):
            continue
        name = str(record.get('name') or 'Rede local')
        virtual = any(x in name.lower() for x in ('vethernet', 'virtual', 'wsl', 'docker', 'vpn', 'tailscale', 'zerotier'))
        result[ip] = Interface(ip, name, bool(record.get('gateway')),
                               int(record.get('metric') or 9999), virtual)
    return sorted(result.values(), key=lambda item: (item.virtual, not item.gateway, item.metric, item.name, item.ip))


def detect_interfaces():
    if os.name == 'nt':
        # Consulta apenas a configuração do Windows. Não envia tráfego à Internet.
        command = """$ErrorActionPreference='Stop';
[Console]::OutputEncoding=[Text.UTF8Encoding]::new();
@(Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq 'Up' } | ForEach-Object {
  $entry=$_;
  foreach($address in $entry.IPv4Address) {
    [PSCustomObject]@{ip=$address.IPAddress;name=$entry.InterfaceAlias;
      gateway=([bool]$entry.IPv4DefaultGateway);metric=$entry.NetIPv4Interface.InterfaceMetric}
  }
}) | ConvertTo-Json -Compress"""
        try:
            output = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                                     '-Command', command], capture_output=True, encoding='utf-8',
                                    timeout=15, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            found = parse_interfaces(json.loads(output.stdout.strip() or '[]'))
            if found:
                return found
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    # Fallback sem depender dos módulos PowerShell de rede.
    try:
        return parse_interfaces([{'ip': item[4][0], 'name': 'Rede local'}
                                 for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)])
    except OSError:
        return []


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return {} if default is None else default.copy()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError(f'{path.name} precisa conter um objeto JSON.')
    return data


def port(value, fallback):
    return value if type(value) is int and 1 <= value <= 65535 else fallback


def port_pairs(folder):
    settings = read_json(Path(folder) / 'runtime/settings.json')
    config = read_json(Path(folder) / 'config.local.json')
    preferred = (port(settings.get('mqtt_port'), port(config.get('mqtt_port'), 1883)),
                 port(settings.get('dashboard_port'), 18083))
    return list(dict.fromkeys([preferred, (1883, 18083), (18830, 18084)]))


def mqtt_probe(host, mqtt_port, timeout=1.2):
    # Identidade efêmera; não usa a identidade da placa, não publica nem assina.
    # CONNACK de recusa de login também comprova que um broker MQTT respondeu.
    client_id = ('atleta-ip-' + uuid.uuid4().hex[:12]).encode('ascii')
    body = b'\x00\x04MQTT\x04\x02\x00\x0a' + len(client_id).to_bytes(2, 'big') + client_id
    packet = bytes([0x10, len(body)]) + body
    try:
        with socket.create_connection((host, mqtt_port), timeout=timeout) as connection:
            connection.sendall(packet)
            answer = b''
            while len(answer) < 4:
                data = connection.recv(4 - len(answer))
                if not data:
                    break
                answer += data
            valid = len(answer) == 4 and answer[:2] == b'\x20\x02' and answer[2] in (0, 1) and answer[3] in range(6)
            if valid and answer[3] == 0:
                connection.sendall(b'\xe0\x00')
            return {'online': valid, 'connack': answer[3] if valid else None}
    except OSError:
        return {'online': False, 'connack': None}


def dashboard_probe(host, dashboard_port, timeout=1.2):
    connection = http.client.HTTPConnection(host, dashboard_port, timeout=timeout)
    try:
        connection.request('GET', '/status', headers={'Connection': 'close'})
        response = connection.getresponse()
        body = response.read(4096).decode('utf-8', errors='replace').lower()
        return response.status == 200 and 'node' in body and 'emqx' in body and 'is started' in body
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def inspect_pair(host, pair):
    mqtt_result = mqtt_probe(host, pair[0])
    dashboard = dashboard_probe(host, pair[1])
    return {'host': host, 'mqtt_port': pair[0], 'dashboard_port': pair[1],
            'mqtt_online': mqtt_result['online'], 'connack': mqtt_result['connack'],
            'dashboard_online': dashboard}


def diagnose(ip, pairs):
    if not valid_ip(ip):
        raise ValueError('Nenhum IPv4 de rede válido foi detectado.')
    targets = [(host, pair) for host in (ip, '127.0.0.1') for pair in pairs]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda args: inspect_pair(*args), targets))
    rank = lambda row: (bool(row['mqtt_online']), bool(row['dashboard_online']))
    lan = max((item for item in results if item['host'] == ip), key=rank)
    loopback = max((item for item in results if item['host'] == '127.0.0.1'), key=rank)
    chosen = lan if lan['mqtt_online'] else loopback if loopback['mqtt_online'] else lan
    if lan['mqtt_online'] and lan['dashboard_online']:
        state = 'online'
    elif lan['mqtt_online']:
        state = 'mqtt_only'
    elif loopback['mqtt_online']:
        state = 'local_only'
    else:
        state = 'offline'
    dashboard_target = next((row for row in (lan, loopback, *results) if row['dashboard_online']), None)
    return {'ip': ip, 'state': state, 'mqtt_port': chosen['mqtt_port'],
            'dashboard_port': chosen['dashboard_port'], 'lan': lan, 'loopback': loopback,
            'dashboard_url': f"http://{dashboard_target['host']}:{dashboard_target['dashboard_port']}/" if dashboard_target else '',
            'checked_at': datetime.now(timezone.utc).isoformat()}


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False) as file:
            temp_name = file.name
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.write('\n')
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def diagnose_local(pairs):
    """Permite abrir o Dashboard em localhost mesmo sem uma interface de rede."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda pair: inspect_pair('127.0.0.1', pair), pairs))
    best = max(results, key=lambda row: (row['mqtt_online'], row['dashboard_online']))
    return {'ip': '', 'state': 'local_only' if best['mqtt_online'] else 'offline',
            'mqtt_port': best['mqtt_port'], 'dashboard_port': best['dashboard_port'],
            'dashboard_url': f"http://127.0.0.1:{best['dashboard_port']}/" if best['dashboard_online'] else '',
            'checked_at': datetime.now(timezone.utc).isoformat(), 'loopback': best}


def save_address(folder, diagnosis):
    folder = Path(folder)
    ip = diagnosis['ip']
    mqtt_port = diagnosis['mqtt_port']
    if not valid_ip(ip) or port(mqtt_port, None) is None:
        raise ValueError('IP ou porta inválidos. Nenhuma configuração foi salva.')
    config_path = folder / 'config.local.json'
    config = read_json(config_path, {'wifi_ssid': '', 'wifi_password': '', 'device_id': 'm5-atleta-01'})
    config.update(mqtt_host=ip, mqtt_port=mqtt_port)
    device_path = folder / 'runtime/device-config.json'
    # Prepara todos os dados antes de gravar. Preserva rede e credenciais existentes.
    device_config = read_json(device_path) if device_path.exists() else None
    if device_config is not None:
        device_config.update(mqtt_host=ip, mqtt_port=mqtt_port)
    public = {key: diagnosis[key] for key in ('ip', 'mqtt_port', 'dashboard_port', 'state', 'checked_at')}
    public['dashboard_url'] = f"http://{ip}:{diagnosis['dashboard_port']}/"
    public['observacao'] = 'Endereço deste PC; o status não comprova acesso pela placa nem persistência MySQL.'
    atomic_json(config_path, config)
    if device_config is not None:
        atomic_json(device_path, device_config)
    atomic_json(folder / 'endereco-servidor.json', public)
    return config_path


def find_folder(executable):
    base = Path(executable).resolve().parent
    for candidate in (base, base / 'laboratorio', *base.parents):
        if (candidate / 'compose.yaml').is_file() and (candidate / 'config.example.json').is_file():
            return candidate
    return base
