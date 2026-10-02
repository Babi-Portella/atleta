"""Grava apenas os segmentos do firmware; nao apaga toda a flash nem escreve configuracao."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Porta da placa, por exemplo COM5 ou /dev/ttyUSB0")
    args = parser.parse_args()
    directory = ROOT / "entrega/firmware"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    segments = []
    for segment in manifest["segments"]:
        file = directory / segment["file"]
        if hashlib.sha256(file.read_bytes()).hexdigest() != segment["sha256"]:
            raise ValueError(f"Checksum diferente: {file.name}")
        segments.extend([segment["offset"], str(file)])
    print("Gravando aplicativo do laboratorio no M5StickC Plus2. Configuracao NVS preservada.")
    subprocess.run([sys.executable, "-m", "esptool", "--chip", "esp32", "--port", args.port,
                    "--baud", "460800", "write_flash", "--flash_mode", "dio", "--flash_freq",
                    "40m", "--flash_size", "8MB", *segments], check=True)


if __name__ == "__main__":
    main()
