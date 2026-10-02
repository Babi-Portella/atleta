"""Consulta somente o nome da conexão Wi-Fi ativa; não lê senhas do Windows."""
import json
import os
from pathlib import Path
import subprocess


def select_wifi(records):
    if isinstance(records, dict):
        records = [records]
    names = sorted({r['ssid'] for r in records or [] if isinstance(r, dict)
                    and r.get('connected') is True and isinstance(r.get('ssid'), str)
                    and 0 < len(r['ssid'].encode('utf-8')) <= 32})
    if len(names) == 1:
        return {'state': 'connected', 'ssid': names[0],
                'message': 'Wi-Fi do computador detectado. O M5 precisa de acesso a essa rede em 2,4 GHz.'}
    if len(names) > 1:
        return {'state': 'multiple', 'ssid': None,
                'message': 'Há mais de uma conexão Wi-Fi ativa. Informe abaixo a rede que o M5 deve usar.'}
    return {'state': 'no_wifi', 'ssid': None,
            'message': 'Nenhuma conexão Wi-Fi ativa foi detectada neste PC. Se ele usa cabo, informe abaixo a rede Wi-Fi do M5.'}


def detect_wifi():
    if os.name != 'nt':
        return {'state': 'unavailable', 'ssid': None, 'message': 'Informe a rede Wi-Fi do M5 abaixo.'}
    command = """[Console]::OutputEncoding=[Text.UTF8Encoding]::new();
$ErrorActionPreference='Stop';
$wifiProfiles=[Windows.Networking.Connectivity.NetworkInformation,Windows,ContentType=WindowsRuntime]::GetConnectionProfiles();
@($wifiProfiles | Where-Object { $_.IsWlanConnectionProfile -and $_.GetNetworkConnectivityLevel().ToString() -ne 'None' } |
ForEach-Object { [PSCustomObject]@{ssid=$_.WlanConnectionProfileDetails.GetConnectedSsid();connected=$true} }) | ConvertTo-Json -Compress
"""
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, encoding='utf-8', errors='strict', timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW, check=True)
        return select_wifi(json.loads(result.stdout.strip() or '[]'))
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return {'state': 'unavailable', 'ssid': None,
                'message': 'O Windows não permitiu consultar o Wi-Fi. Você pode preencher a rede manualmente; confira também as permissões de localização do Windows.'}


def autofill(saved_ssid, saved_password, detected_ssid):
    """Uma senha do projeto só é reutilizada para exatamente o mesmo SSID."""
    if not detected_ssid:
        return saved_ssid, saved_password
    return detected_ssid, saved_password if detected_ssid == saved_ssid else ''
