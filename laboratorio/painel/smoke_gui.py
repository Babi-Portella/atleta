"""Verifica a janela real e captura somente sua própria área. Requer Pillow no Python de teste."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk

from PIL import Image

from app import App
from rede import atomic_json, read_json


def capture_window(root, path):
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi.SelectObject.restype = wintypes.HGDIOBJ
    gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    hwnd = user.GetAncestor(root.winfo_id(), 2)
    rect = wintypes.RECT()
    user.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    dc = user.GetDC(hwnd)
    memory_dc = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
    previous = gdi.SelectObject(memory_dc, bitmap)
    try:
        if not user.PrintWindow(hwnd, memory_dc, 2):
            raise RuntimeError('PrintWindow falhou')
        class Header(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG), ('height', wintypes.LONG),
                        ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                        ('image_size', wintypes.DWORD), ('x', wintypes.LONG), ('y', wintypes.LONG),
                        ('colors', wintypes.DWORD), ('important', wintypes.DWORD)]
        header = Header(40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi.SelectObject(memory_dc, previous)
        if not gdi.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(header), 0):
            raise RuntimeError('GetDIBits falhou')
        Image.frombytes('RGB', (width, height), pixels.raw, 'raw', 'BGRX').save(path)
    finally:
        gdi.SelectObject(memory_dc, previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory_dc)
        user.ReleaseDC(hwnd, dc)


def wait(root, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('Janela não concluiu a operação no prazo')


def main():
    evidence = Path(__file__).resolve().parents[1] / 'evidencias'
    with tempfile.TemporaryDirectory(prefix='atleta-ip-ui-') as tmp:
        original = {'wifi_ssid': 'REDE_DE_TESTE', 'wifi_password': 'SENHA_DE_TESTE', 'device_id': 'm5-atleta-01'}
        atomic_json(Path(tmp) / 'config.local.json', original)
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        root = tk.Tk()
        try:
            app = App(root, tmp)
            wait(root, lambda: app.result is not None and not app.busy)
            assert read_json(Path(tmp) / 'config.local.json') == original, 'Abrir não deve gravar'
            app.refresh_button.invoke()
            assert app.busy and app.primary.instate(['disabled'])
            wait(root, lambda: app.saved is not None and not app.busy)
            assert app.last_error is None
            saved = read_json(Path(tmp) / 'config.local.json')
            assert saved['wifi_password'] == original['wifi_password']
            assert saved['mqtt_host'] == app.result['ip']
            app.copy_button.invoke()
            assert root.clipboard_get() == saved['mqtt_host']
            root.update_idletasks()
            capture_window(root, evidence / 'painel-ip.png')
            root.geometry(f'590x{root.winfo_height()}')
            root.update()
            assert app.primary.winfo_rootx() >= root.winfo_rootx()
            assert app.primary.winfo_rootx() + app.primary.winfo_width() <= root.winfo_rootx() + root.winfo_width()
            assert app.athlete_button.winfo_rootx() + app.athlete_button.winfo_width() <= root.winfo_rootx() + root.winfo_width()
            app.athlete_button.invoke()
            root.update()
            assert app.athlete_window.winfo_exists()
            first_window = app.athlete_window
            app.athlete_button.invoke()
            assert app.athlete_window is first_window
            app.athlete_window.destroy()
            report = {'passed': True, 'gui_toolkit': 'Tk', 'native_window_tested': True,
                      'ip': app.result['ip'], 'server_state': app.result['state'],
                      'startup_did_not_change_config': True, 'button_saved_ip': True,
                      'wifi_preserved': True, 'copy_button_verified': True,
                      'worker_did_not_block_window': True, 'minimum_width_checked': 590,
                      'athlete_button_opens_single_window': True,
                      'scope': 'Janela Python real, configuração temporária; sem acesso à placa'}
            atomic_json(evidence / 'validacao-painel-gui.json', report)
            print(json.dumps(report, ensure_ascii=False))
        finally:
            root.destroy()


if __name__ == '__main__':
    main()
