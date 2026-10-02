"""Compila e empacota a entrega portatil sem runtime, configuracao Wi-Fi ou credenciais."""
from __future__ import annotations
import hashlib
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-only', action='store_true', help='Gera somente as imagens antes do teste físico')
    args = parser.parse_args()
    version = re.search(r'constexpr char VERSION\[\] = "([0-9.]+)"',
                        (ROOT / 'firmware/src/main.cpp').read_text(encoding='utf-8')).group(1)
    evidence = ROOT / "evidencias"
    evidence.mkdir(exist_ok=True)
    result = subprocess.run([sys.executable, "-m", "platformio", "run"], cwd=ROOT / "firmware",
                            capture_output=True, text=True, errors="replace")
    (evidence / "compilacao.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("Compilacao falhou; consulte evidencias/compilacao.log")
    build = ROOT / "firmware/.pio/build/m5stickc-plus2"
    core = Path(os.environ.get("PLATFORMIO_CORE_DIR", Path.home() / ".platformio"))
    boot_app = core / "packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin"
    output = ROOT / "entrega/firmware"
    output.mkdir(parents=True, exist_ok=True)
    segments = []
    merge_args = []
    for offset, source in [("0x1000", build / "bootloader.bin"),
                           ("0x8000", build / "partitions.bin"),
                           ("0xe000", boot_app), ("0x10000", build / "firmware.bin")]:
        target = output / source.name
        shutil.copyfile(source, target)
        segments.append({"offset": offset, "file": target.name, "sha256": sha(target), "bytes": target.stat().st_size})
        merge_args.extend([offset, str(target)])
    merged = output / f"m5stickc-plus2-lab-{version}.bin"
    subprocess.run([sys.executable, "-m", "esptool", "--chip", "esp32", "merge_bin", "--flash_mode",
                    "dio", "--flash_freq", "40m", "--flash_size", "8MB", "-o", str(merged), *merge_args], check=True)
    # O nibble alto do quarto byte do header codifica a flash: 3 = 8 MB.
    flash_code = (merged.read_bytes()[0x1003] >> 4)
    if flash_code != 3:
        raise RuntimeError("A imagem final nao informa flash de 8MB")
    validation = ROOT / 'evidencias/validacao-m5-fisico.json'
    physical = json.loads(validation.read_text(encoding='utf-8')) if validation.exists() else {}
    tested = physical.get('passed') is True and physical.get('firmware_sha256') == sha(build / 'firmware.bin')
    manifest = {"version": version, "board": "M5StickC Plus2", "language": "Arduino C++",
                "compiled_at_utc": datetime.now(timezone.utc).isoformat(), "flash_mb": 8,
                "secrets_embedded": False, "physical_device_tested": tested,
                "source_sha256": sha(ROOT / "firmware/src/main.cpp"),
                "activity_header_sha256": sha(ROOT / "firmware/src/activity.h"),
                "platformio_ini_sha256": sha(ROOT / "firmware/platformio.ini"),
                "segments": segments, "merged": {"file": merged.name, "offset": "0x0",
                "sha256": sha(merged), "bytes": merged.stat().st_size}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if args.firmware_only:
        print(f'Firmware {version} e hashes preparados para teste físico.')
        return
    # Lista positiva: evita carregar segredos acidentalmente no ZIP.
    selected = [ROOT / name for name in ("README.md", "compose.yaml", "requirements.txt",
                "config.example.json", "preparar.ps1", ".gitignore")]
    for directory in ("sql", "emqx", "tools", "docs", "evidencias", "entrega/firmware"):
        selected.extend(p for p in (ROOT / directory).rglob("*")
                        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    selected += [ROOT / "firmware/platformio.ini", *list((ROOT / "firmware/src").glob('*'))]
    selected += list((ROOT / "firmware/tests").glob('*.cpp'))
    selected += [p for p in (ROOT / "painel").glob("*") if p.is_file() and p.suffix in (".py", ".txt")]
    selected += [ROOT / "entrega" / name for name in ("PainelIP.exe", "manifest-painel.json")
                 if (ROOT / "entrega" / name).exists()]
    private = ROOT / "runtime/secrets.json"
    tokens = list(json.loads(private.read_text(encoding="utf-8")).values()) if private.exists() else []
    for local in (ROOT / 'config.local.json', ROOT / 'runtime/device-config.json'):
        if local.exists():
            config = json.loads(local.read_text(encoding='utf-8-sig'))
            tokens.extend(config.get(key) for key in ('wifi_password', 'mqtt_password'))
    token_bytes = [value.encode() for value in tokens if isinstance(value, str) and value]
    for path in selected:
        content = path.read_bytes()
        if any(token in content for token in token_bytes):
            raise RuntimeError(f"Credencial encontrada em arquivo de entrega: {path.name}")
    archive = ROOT / "entrega/atleta-emqx-m5stickc-plus2.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(set(selected)):
            z.write(path, "laboratorio/" + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise RuntimeError("ZIP invalido")
    (ROOT / "entrega/SHA256SUMS.txt").write_text(
        f"{sha(archive)}  {archive.name}\n{sha(merged)}  firmware/{merged.name}\n", encoding="utf-8")
    print(f"Entrega: {archive.name} ({archive.stat().st_size} bytes). Segredos excluidos e ZIP validado.")


if __name__ == "__main__":
    main()
