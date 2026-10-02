"""Ferramentas locais do laboratório. Nunca imprime senhas ou tokens."""
from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
DEVICE = "m5-atleta-01"
TEST_DEVICE = "lab-teste-01"
OBSERVER = "lab-observer"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sql_literal(value):
    # Hex literal evita ambiguidades com apóstrofos e sql_mode do servidor.
    return "CONVERT(0x" + value.encode("utf-8").hex() + " USING utf8mb4)"


def load_secrets():
    path = RUNTIME / "secrets.json"
    if not path.exists():
        raise ValueError("Execute primeiro: python tools/lab.py init")
    return read_json(path)


def compose(*args, timeout=600):
    if not (RUNTIME / "compose.env").exists():
        raise ValueError("Execute primeiro: python tools/lab.py init")
    return subprocess.run(
        ["docker", "compose", "--env-file", str(RUNTIME / "compose.env"),
         "-f", str(ROOT / "compose.yaml"), *args], cwd=ROOT, check=True, timeout=timeout
    )


def render(secrets_data, mysql_server="mysql:3306"):
    for value in secrets_data.values():
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", value):
            raise ValueError("Credenciais geradas devem manter o formato token_urlsafe (20 a 128 caracteres).")
    schema = (ROOT / "sql/01-schema.sql").read_text(encoding="utf-8")
    statements = [schema]
    for username in (DEVICE, TEST_DEVICE, OBSERVER):
        password_hash = bcrypt.hashpw(secrets_data[username].encode(), bcrypt.gensalt(rounds=10)).decode()
        statements.append(
            "INSERT INTO mqtt_users(username, client_id, password_hash) VALUES "
            f"({sql_literal(username)}, {sql_literal(username)}, {sql_literal(password_hash)});"
        )
    for username in (DEVICE, TEST_DEVICE):
        statements.append(
            "INSERT INTO mqtt_acl(username, permission, action, topic) VALUES "
            f"({sql_literal(username)}, 'allow', 'publish', {sql_literal('atletas/' + username + '/telemetria')});"
        )
    statements.append(
        "INSERT INTO mqtt_acl(username, permission, action, topic) "
        "VALUES ('lab-observer', 'allow', 'subscribe', 'atletas/+/telemetria');"
    )
    for username, key in (("emqx_lab", "mysql_emqx"), ("lab_reader", "mysql_reader")):
        statements.append(f"CREATE USER IF NOT EXISTS '{username}'@'%' IDENTIFIED BY '{secrets_data[key]}';")
    statements.extend([
        "GRANT SELECT ON athlete_lab.mqtt_users TO 'emqx_lab'@'%';",
        "GRANT SELECT ON athlete_lab.mqtt_acl TO 'emqx_lab'@'%';",
        "GRANT INSERT, SELECT, UPDATE(id) ON athlete_lab.telemetry TO 'emqx_lab'@'%';",
        "GRANT SELECT ON athlete_lab.telemetry TO 'lab_reader'@'%';",
    ])
    (RUNTIME / "01-init.sql").write_text("\n\n".join(statements) + "\n", encoding="utf-8")

    common = dict(server=mysql_server, database="athlete_lab", username="emqx_lab",
                  password=secrets_data["mysql_emqx"], pool_size=2)
    sql = lambda name: (ROOT / "emqx" / name).read_text(encoding="utf-8").strip()
    authentication = dict(common, mechanism="password_based", backend="mysql", enable=True,
                          password_hash_algorithm={"name": "bcrypt"},
                          query=sql("authentication.sql"), query_timeout="5s")
    authorizer = dict(common, type="mysql", enable=True, query=sql("authorization.sql"))
    connector = dict(common, enable=True)
    action = {"enable": True, "connector": "lab_mysql",
              "parameters": {"sql": sql("insert.sql")},
              "resource_opts": {"batch_size": 1, "query_mode": "sync", "request_ttl": "10s"}}
    rule = {"enable": True, "sql": sql("rule.sql"), "actions": ["mysql:lab_save"],
            "description": "Laboratorio: telemetria real ou teste identificado para MySQL"}
    config = {
        "node": {"cookie": secrets_data["node_cookie"]},
        "dashboard": {"default_username": "admin", "default_password": secrets_data["dashboard"]},
        "listeners": {"tcp": {"default": {"bind": "0.0.0.0:1883"}},
                      "ws": {"default": {"enable": False}}, "wss": {"default": {"enable": False}},
                      "ssl": {"default": {"enable": False}}},
        "authentication": [authentication],
        "authorization": {"no_match": "deny", "deny_action": "ignore", "cache": {"enable": False},
                          "sources": [authorizer]},
        "connectors": {"mysql": {"lab_mysql": connector}},
        "actions": {"mysql": {"lab_save": action}},
        "rule_engine": {"rules": {"lab_telemetry": rule}},
        "log": {"console": {"enable": True, "level": "warning"}},
    }
    # HOCON aceita a sintaxe JSON, inclusive os placeholders SQL dentro de strings.
    write_json(RUNTIME / "base.hocon", config)
    api_dir = RUNTIME / "emqx-api"
    api_dir.mkdir(exist_ok=True)
    for name, content in {
        "connector.json": dict(connector, type="mysql", name="lab_mysql"),
        "action.json": dict(action, type="mysql", name="lab_save"),
        "rule.json": dict(rule, id="lab_telemetry"),
        "authentication.json": authentication,
        "authorization.json": config["authorization"],
    }.items():
        write_json(api_dir / name, content)


def init(profile):
    RUNTIME.mkdir(exist_ok=True)
    existing = RUNTIME / "settings.json"
    if existing.exists() and read_json(existing)["profile"] != profile:
        raise ValueError("Perfil ja inicializado. Use outra copia do kit para o servidor; preserve este ambiente.")
    secret_path = RUNTIME / "secrets.json"
    if secret_path.exists():
        data = read_json(secret_path)
        if "node_cookie" not in data:
            data["node_cookie"] = secrets.token_urlsafe(24)
            write_json(secret_path, data)
    else:
        data = {key: secrets.token_urlsafe(24) for key in
                ("mysql_root", "mysql_emqx", "mysql_reader", "dashboard", "node_cookie", DEVICE, TEST_DEVICE, OBSERVER)}
        write_json(secret_path, data)
    settings = {"profile": profile, "bind": "127.0.0.1" if profile == "local" else "0.0.0.0",
                "mqtt_port": 18830 if profile == "local" else 1883,
                "dashboard_port": 18084 if profile == "local" else 18083, "mysql_port": 33070}
    if existing.exists():
        settings.update(read_json(existing))
    write_json(existing, settings)
    env = f"MYSQL_ROOT_PASSWORD={data['mysql_root']}\nBIND_ADDRESS={settings['bind']}\n"
    env += f"MQTT_PORT={settings['mqtt_port']}\nDASHBOARD_PORT={settings['dashboard_port']}\nMYSQL_PORT={settings['mysql_port']}\n"
    (RUNTIME / "compose.env").write_text(env, encoding="utf-8")
    render(data)
    local_config = ROOT / "config.local.json"
    if not local_config.exists():
        local_config.write_bytes((ROOT / "config.example.json").read_bytes())
    print(f"Preparado perfil {profile}. Credenciais locais em runtime/secrets.json (nao publicar).")
    print("IP e Wi-Fi podem ser preenchidos depois em config.local.json. Nenhuma senha foi impressa.")


def provision(port, config_path=None):
    import serial
    config = read_json(config_path or ROOT / "config.local.json")
    if config["device_id"] != DEVICE:
        raise ValueError("Este kit provisiona m5-atleta-01. Outro ID exige cadastro e ACL correspondentes.")
    if not config["wifi_ssid"] or not config["mqtt_host"]:
        raise ValueError("Preencha wifi_ssid e mqtt_host em config.local.json quando estiverem disponiveis.")
    host = config["mqtt_host"]
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or "://" in host:
        raise ValueError("mqtt_host deve ser o IP/domainio do servidor acessivel pela placa, sem http://.")
    if not isinstance(config["mqtt_port"], int) or not 1 <= config["mqtt_port"] <= 65535:
        raise ValueError("Porta MQTT invalida.")
    device_password = config.get("mqtt_password") or load_secrets()[DEVICE]
    payload = dict(config, mqtt_username=DEVICE, mqtt_password=device_password)
    encoded = ("CONFIG " + json.dumps(payload, separators=(",", ":")) + "\n").encode()
    if len(encoded) > 2048:
        raise ValueError("Configuracao excede o limite serial.")
    with serial.Serial(port, 115200, timeout=1, write_timeout=3) as connection:
        # Algumas interfaces reiniciam ao abrir a porta. Aguarde a inicializacao.
        time.sleep(3)
        connection.reset_input_buffer()
        connection.write(encoded)
        connection.flush()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            line = connection.readline().decode(errors="replace").strip()
            if line == "CONFIG_OK":
                print("Configuracao gravada no M5. Ele reiniciara e tentara conectar.")
                return
            if line.startswith("CONFIG_ERROR"):
                raise ValueError(line)
    raise ValueError("Sem confirmacao CONFIG_OK. Confira porta, cabo de dados e firmware.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="Gera banco, configuracao EMQX e credenciais uma vez")
    p.add_argument("--profile", choices=("local", "server"), default="local")
    sub.add_parser("up", help="Inicia somente a stack dedicada atleta-lab")
    sub.add_parser("stop", help="Para a stack sem excluir dados")
    sub.add_parser("status", help="Mostra estado dos containers do laboratorio")
    sub.add_parser("verify-restart", help="Testa persistencia apos parar/iniciar somente a stack local")
    p = sub.add_parser("render", help="Regenera arquivos privados sem alterar o servidor")
    p.add_argument("--mysql-server", default="mysql:3306")
    p = sub.add_parser("configure-device", help="Envia configuracao por USB, sem recompilar")
    p.add_argument("--port", required=True)
    p.add_argument("--config", help="Configuracao exportada pelo servidor (credencial somente do dispositivo)")
    sub.add_parser("export-device-config", help="Exporta apenas a configuracao do M5 para transferencia privada")
    p = sub.add_parser("verify", help="Testa EMQX/MySQL com dados identificados como teste")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--mqtt-port", type=int)
    p.add_argument("--mysql-port", type=int)
    p.add_argument("--dashboard-port", type=int)
    args = parser.parse_args()
    if args.command == "init": init(args.profile)
    elif args.command == "up": compose("up", "-d", "--wait", "--wait-timeout", "180")
    elif args.command == "stop": compose("stop")
    elif args.command == "status": compose("ps")
    elif args.command == "verify-restart":
        from verify import verify_restart
        verify_restart()
    elif args.command == "render":
        render(load_secrets(), args.mysql_server)
        print("Arquivos privados regenerados. Nenhuma alteracao aplicada ao servidor.")
    elif args.command == "configure-device": provision(args.port, args.config)
    elif args.command == "export-device-config":
        data = read_json(ROOT / "config.local.json")
        data.update(mqtt_username=DEVICE, mqtt_password=load_secrets()[DEVICE])
        write_json(RUNTIME / "device-config.json", data)
        print("Exportado runtime/device-config.json. Contem somente a credencial MQTT da placa e sua configuracao.")
    elif args.command == "verify":
        from verify import run
        settings = read_json(RUNTIME / "settings.json")
        run(args.host, args.mqtt_port or settings["mqtt_port"],
            args.mysql_port or settings["mysql_port"], args.dashboard_port or settings["dashboard_port"])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"ERRO: {error}", file=sys.stderr)
        sys.exit(1)
