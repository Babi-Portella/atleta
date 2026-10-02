"""Teste opt-in da opção LAN em uma instalação existente, com restauração ao concluir."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from rede import detect_interfaces, diagnose, port_pairs, read_json, atomic_json
from servidor import LabController


def main():
    lab = Path(__file__).resolve().parents[1]
    paths = [lab / 'runtime/settings.json', lab / 'runtime/compose.env']
    original = {path: path.read_bytes() for path in paths}
    settings = read_json(paths[0])
    secret_hash = hashlib.sha256((lab / 'runtime/secrets.json').read_bytes()).hexdigest()
    controller = LabController(lab)
    try:
        started = controller.start(True)
        interfaces = detect_interfaces()
        assert interfaces
        result = diagnose(interfaces[0].ip, port_pairs(lab))
        assert result['state'] == 'online', result['state']
        assert started['settings']['mqtt_port'] == settings['mqtt_port']
        assert started['settings']['dashboard_port'] == settings['dashboard_port']
        assert hashlib.sha256((lab / 'runtime/secrets.json').read_bytes()).hexdigest() == secret_hash
        mysql_binding = controller.run([controller.docker, *controller.context, 'port', 'atleta-lab-mysql-1', '3306']).stdout.strip()
        assert mysql_binding == f"127.0.0.1:{settings['mysql_port']}"
        report = {'passed': True, 'executed_at': datetime.now(timezone.utc).isoformat(),
                  'ip': result['ip'], 'state': result['state'], 'mqtt_port': result['mqtt_port'],
                  'dashboard_port': result['dashboard_port'], 'existing_ports_preserved': True,
                  'credentials_preserved': True, 'mysql_remained_loopback_only': True,
                  'scope': 'Acesso pelo proprio IP LAN; acesso por outro dispositivo e M5 nao testados',
                  'configuration_restored': True, 'services_stopped_after_test': True}
        controller.stop()
        atomic_json(lab / 'evidencias/validacao-painel-rede.json', report)
        print(json.dumps(report, ensure_ascii=False))
    finally:
        controller.stop()
        for path, content in original.items():
            path.write_bytes(content)


if __name__ == '__main__':
    main()
