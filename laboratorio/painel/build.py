"""Gera o executável Windows portátil e um ZIP sem arquivos privados."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

from servidor import TEMPLATES
from app import VERSION

ROOT = Path(__file__).resolve().parent
LAB = ROOT.parent


def create_icon(path):
    size = 32
    pixels = bytearray()
    glyphs = ['1110110', '0100101', '0100110', '0100100', '1110100']
    for y in reversed(range(size)):
        for x in range(size):
            gx, gy = (x - 5) // 3, (y - 8) // 3
            white = 0 <= gx < 7 and 0 <= gy < 5 and glyphs[gy][gx] == '1'
            r, g, b = (255, 255, 255) if white else (23, 100, 83)
            pixels.extend((b, g, r, 255))
    bitmap = struct.pack('<IIIHHIIIIII', 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    bitmap += pixels + bytes(size * 4)
    path.write_bytes(struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', size, size, 0, 0, 1, 32, len(bitmap), 22) + bitmap)


def main():
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    icon = build / 'painel.ico'
    create_icon(icon)
    output = LAB / 'entrega'
    output.mkdir(exist_ok=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
               '--noupx', '--name', 'PainelIP', '--icon', str(icon), '--distpath', str(output),
               '--workpath', str(build / 'pyinstaller'), '--specpath', str(build),
               '--paths', str(LAB / 'tools'), '--exclude-module', 'verify',
               '--add-data', str(icon) + os.pathsep + '.']
    for name in TEMPLATES:
        command += ['--add-data', str(LAB / name) + os.pathsep + 'kit/' + Path(name).parent.as_posix()]
    command += [str(ROOT / 'app.py')]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, errors='replace')
    (LAB / 'evidencias/compilacao-painel.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Compilação falhou; consulte evidencias/compilacao-painel.log')
    exe = output / 'PainelIP.exe'
    archive = output / 'painel-ip-portatil.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as package:
        package.write(exe, exe.name)
        package.write(ROOT / 'LEIAME.txt', 'LEIAME.txt')
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
    source_files = [ROOT / name for name in ('app.py', 'rede.py', 'servidor.py', 'build.py', 'requirements-build.txt',
                                            'configurar_m5.py', 'm5_serial.py', 'dados_atleta.py', 'migracao.py',
                                            'wifi_pc.py', 'conexao_m5.py')]
    source_files += [LAB / 'tools/lab.py']
    manifest = {'version': VERSION, 'target': 'Windows x64', 'python': sys.version.split()[0],
                'pyinstaller': subprocess.check_output([sys.executable, '-m', 'PyInstaller', '--version'], text=True).strip(),
                'files': {file.name: {'bytes': file.stat().st_size,
                         'sha256': hashlib.sha256(file.read_bytes()).hexdigest()} for file in (exe, archive, *source_files)},
                'credentials_bundled': False}
    (output / 'manifest-painel.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'PainelIP.exe: {exe.stat().st_size / 1024 / 1024:.2f} MiB. ZIP portátil e hashes gerados.')


if __name__ == '__main__':
    main()
