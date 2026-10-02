"""Abre o EXE sem Python no PATH e verifica sua janela nativa. Não altera configurações."""
import argparse
import ctypes
import hashlib
import json
from ctypes import wintypes
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

from rede import atomic_json
from smoke_gui import capture_window


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dados-atleta', action='store_true')
    args = parser.parse_args()
    expected_title = 'Atleta IP — dados do atleta' if args.dados_atleta else 'Atleta IP — servidor do laboratório'
    evidence_name = 'dados-atleta-exe' if args.dados_atleta else 'painel-ip-exe'
    report_name = 'validacao-dados-atleta-exe' if args.dados_atleta else 'validacao-painel-exe'
    lab = Path(__file__).resolve().parents[1]
    exe = lab / 'entrega/PainelIP.exe'
    user = ctypes.windll.user32
    kernel = ctypes.windll.kernel32
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsHungAppWindow.argtypes = [wintypes.HWND]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    window = []
    owned = set()
    def collect_owned():
        command = '@(Get-CimInstance Win32_Process -Filter "Name = \'PainelIP.exe\'" | Select-Object ProcessId,ParentProcessId) | ConvertTo-Json -Compress'
        raw = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                      creationflags=subprocess.CREATE_NO_WINDOW, timeout=10, text=True)
        records = json.loads(raw or '[]')
        if isinstance(records, dict):
            records = [records]
        owned.add(process.pid)
        for _ in range(3):
            owned.update(p['ProcessId'] for p in records if p['ParentProcessId'] in owned)
    @callback_type
    def visit(hwnd, unused):
        title = ctypes.create_unicode_buffer(256)
        user.GetWindowTextW(hwnd, title, 256)
        if title.value != expected_title:
            return True
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in owned:
            return True
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                name = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(name))
                if kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)) and Path(name.value).resolve() == exe.resolve():
                    window.append(hwnd)
            finally:
                kernel.CloseHandle(handle)
        return True
    env = dict(os.environ)
    win = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    env['PATH'] = ';'.join(str(x) for x in (win, win / 'System32', win / 'System32/WindowsPowerShell/v1.0'))
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    process = subprocess.Popen([str(exe)] + (['--dados-atleta'] if args.dados_atleta else []),
                               env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not window:
            collect_owned()
            user.EnumWindows(visit, 0)
            time.sleep(0.2)
        assert window, 'EXE não abriu a janela esperada'
        hwnd = window[0]
        # Dá tempo para a consulta de interfaces e os timeouts locais.
        for _ in range(75):
            assert process.poll() is None
            assert not user.IsHungAppWindow(hwnd)
            time.sleep(0.2)
        assert user.IsWindowVisible(hwnd)
        capture_window(SimpleNamespace(winfo_id=lambda: hwnd), lab / f'evidencias/{evidence_name}.png')
        report = {'passed': True, 'executed_at': datetime.now(timezone.utc).isoformat(),
                  'exe_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
                  'packaged_executable': True, 'python_removed_from_path': True,
                  'native_window_visible': True, 'window_responsive': True,
                  'configuration_changed': False, 'athlete_data_window': args.dados_atleta}
        atomic_json(lab / f'evidencias/{report_name}.json', report)
        print('PASS EXE abriu janela nativa e permaneceu responsivo sem Python no PATH')
    finally:
        for hwnd in window:
            user.PostMessageW(hwnd, 0x0010, 0, 0)
        try:
            process.wait(5)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        # Algumas falhas de inicialização deixam o filho onefile aberto mesmo após o pai sair.
        for pid in owned - {process.pid}:
            handle = kernel.OpenProcess(0x1001, False, pid)
            if handle:
                try:
                    name = ctypes.create_unicode_buffer(32768)
                    size = wintypes.DWORD(len(name))
                    if kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)) and Path(name.value).resolve() == exe.resolve():
                        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
                        kernel.TerminateProcess(handle, 0)
                finally:
                    kernel.CloseHandle(handle)


if __name__ == '__main__':
    main()
