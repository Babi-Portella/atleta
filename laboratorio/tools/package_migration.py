"""Cria o ZIP PRIVADO para outro PC: histórico consistente e configuração do atleta."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'painel'))
from migracao import export_history, load_history
from rede import atomic_json, read_json


def main():
    public = ROOT / 'entrega/atleta-emqx-m5stickc-plus2.zip'
    if not public.is_file():
        raise RuntimeError('Gere primeiro a entrega pública atualizada com release.py.')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    staging = ROOT / 'runtime' / ('pacote-migracao-' + stamp)
    staging.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(public) as package:
        if package.testzip() is not None:
            raise RuntimeError('Pacote base corrompido.')
        for entry in package.infolist():
            relative = Path(entry.filename)
            if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'laboratorio':
                raise RuntimeError('Caminho inesperado no pacote base.')
        package.extractall(staging)
    folder = staging / 'laboratorio'
    # O EXE na raiz encontra laboratorio/; também mantemos a cópia no kit completo.
    shutil.copy2(folder / 'entrega/PainelIP.exe', staging / 'ABRIR PAINEL.exe')
    shutil.copy2(ROOT / 'docs/PRIMEIRO_USO_OUTRO_PC.txt', staging / 'LEIA PRIMEIRO.txt')
    original = ROOT.parent / 'main.py'
    if original.is_file():
        (staging / 'codigo-original').mkdir()
        shutil.copy2(original, staging / 'codigo-original/main.py')
        (staging / 'codigo-original/LEIAME.txt').write_text(
            'API HTTP original preservada como referência. O laboratório atual usa M5, EMQX, MySQL e o painel; '
            'esta API não é iniciada pelo painel. Ambientes Python e credenciais da API antiga não são copiados.\n', encoding='utf-8')
    profile = read_json(ROOT / 'config.local.json')
    exported = {key: profile.get(key) for key in
                ('wifi_ssid', 'wifi_password', 'device_id', 'weight_kg', 'step_length_m', 'activity_met', 'athlete_id')}
    exported.update(mqtt_host='', mqtt_port=1883)
    atomic_json(folder / 'config.local.json', exported)
    snapshot = export_history(ROOT, folder / 'migracao')
    load_history(folder)
    info = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'private_package': True, 'contains_wifi_configuration': True,
            'contains_athlete_profile': True, 'contains_telemetry_history': True,
            'server_credentials': 'Geradas no primeiro início no destino; enviar ao M5 por USB.',
            'rows': snapshot['rows'], 'physical_rows': snapshot['physical_rows'],
            'test_rows': snapshot['test_rows'], 'source_content_sha256': snapshot['content_sha256'],
            'snapshot_sha256': snapshot['sha256'], 'docker_installer_included': False,
            'docker_images_included': False,
            'files': {p.relative_to(staging).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in staging.rglob('*') if p.is_file()}}
    atomic_json(staging / 'MANIFESTO-MIGRACAO.json', info)
    # Só config.local.json pode conter a senha Wi-Fi. Credenciais de servidor não viajam.
    server_tokens = [v.encode() for v in read_json(ROOT / 'runtime/secrets.json').values() if isinstance(v, str) and v]
    wifi = (profile.get('wifi_password') or '').encode()
    for path in staging.rglob('*'):
        if path.is_file():
            content = path.read_bytes()
            if any(v in content for v in server_tokens):
                raise RuntimeError('Credencial do servidor de origem encontrada no pacote.')
            if wifi and wifi in content and path != folder / 'config.local.json':
                raise RuntimeError('Senha Wi-Fi encontrada fora da configuração privada.')
    output = ROOT / 'entrega/Atleta-Migracao-PRIVADO.zip'
    temporary = output.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as package:
        for path in sorted(staging.rglob('*')):
            if path.is_file():
                package.write(path, 'Atleta - outro PC/' + path.relative_to(staging).as_posix())
    with zipfile.ZipFile(temporary) as package:
        if package.testzip() is not None:
            raise RuntimeError('Falha de integridade do ZIP de migração.')
    temporary.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.sha256.txt').write_text(digest + '  ' + output.name + '\n', encoding='utf-8')
    atomic_json(ROOT / 'runtime/ultimo-pacote-migracao.json', {'staging': str(staging), 'archive': str(output),
                'sha256': digest, 'bytes': output.stat().st_size, 'rows': snapshot['rows'],
                'physical_rows': snapshot['physical_rows'], 'snapshot': snapshot})
    print(f'ZIP privado preparado: {output.name}; {snapshot["rows"]} registros ({snapshot["physical_rows"]} físicos).')
    print(f'Tamanho: {output.stat().st_size} bytes. Integridade validada. Senhas não impressas.')


if __name__ == '__main__':
    main()
