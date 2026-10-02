"""Testes reais de EMQX/MySQL. As mensagens sintéticas usam source=test."""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import pymysql
import requests

from lab import ROOT, RUNTIME, DEVICE, TEST_DEVICE, OBSERVER, load_secrets, write_json, read_json, compose


def code(reason):
    return getattr(reason, "value", reason)


class Probe:
    def __init__(self, host, port, username, password, client_id=None, protocol=mqtt.MQTTv5):
        self.connected = threading.Event()
        self.messages = queue.Queue()
        self.pubacks = queue.Queue()
        self.subacks = queue.Queue()
        self.connect_code = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=client_id or username, protocol=protocol,
                                  reconnect_on_failure=False)
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self.on_connect
        self.client.on_message = lambda c, u, m: self.messages.put((m.topic, m.payload))
        self.client.on_publish = lambda c, u, mid, reason, props: self.pubacks.put((mid, code(reason)))
        self.client.on_subscribe = lambda c, u, mid, reasons, props: self.subacks.put((mid, [code(r) for r in reasons]))
        self.client.connect(host, port, keepalive=20)
        self.client.loop_start()
        if not self.connected.wait(10):
            self.close()
            raise AssertionError("Sem CONNACK do broker em 10 segundos")

    def on_connect(self, client, userdata, flags, reason, properties):
        self.connect_code = code(reason)
        self.connected.set()

    def subscribe(self, topic):
        result, mid = self.client.subscribe(topic, qos=1)
        assert result == mqtt.MQTT_ERR_SUCCESS
        received_mid, reasons = self.subacks.get(timeout=10)
        assert received_mid == mid
        return reasons

    def publish(self, topic, payload, qos=1):
        info = self.client.publish(topic, payload, qos=qos, retain=False)
        assert info.rc == mqtt.MQTT_ERR_SUCCESS
        mid, reason = self.pubacks.get(timeout=10)
        assert mid == info.mid
        return reason

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()


def run(host, mqtt_port, mysql_port, dashboard_port):
    secret = load_secrets()
    results = []
    probes = []
    database = None
    report = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": {"host": host, "mqtt_port": mqtt_port, "mysql_port": mysql_port,
                   "dashboard_port": dashboard_port},
        "scope": "Broker EMQX e MySQL reais; cliente MQTT de teste no computador",
        "physical_device_tested": False,
        "sensor_values": "Sinteticos; todas as mensagens validas de teste usam source=test",
        "checks": results,
    }

    def check(name, condition, detail=""):
        result = {"name": name, "passed": bool(condition)}
        if detail: result["detail"] = detail
        results.append(result)
        print(("PASS " if condition else "FAIL ") + name)
        assert condition, name

    def probe(username, password=None, **kwargs):
        p = Probe(host, mqtt_port, username, password if password is not None else secret.get(username), **kwargs)
        probes.append(p)
        return p

    try:
        base = f"http://{host}:{dashboard_port}/api/v5"
        session = requests.Session()
        session.trust_env = False
        response = session.post(base + "/login", json={"username": "admin", "password": secret["dashboard"]}, timeout=10)
        check("Dashboard acessivel com conta administrativa", response.status_code == 200)
        session.headers["Authorization"] = "Bearer " + response.json()["token"]

        def api(path):
            res = session.get(base + path, timeout=10)
            assert res.status_code == 200, f"Consulta API falhou: {path}, HTTP {res.status_code}"
            return res.json()

        nodes = api("/nodes")
        report["emqx_versions"] = [n.get("version") for n in nodes]
        connector = api("/connectors/mysql:lab_mysql")
        check("Conector MySQL conectado", connector.get("status") == "connected")
        action = api("/actions/mysql:lab_save")
        check("Acao MySQL conectada", action.get("status") == "connected")
        check("Regra de persistencia habilitada", api("/rules/lab_telemetry").get("enable") is True)
        authn = api("/authentication")
        check("Autenticacao Password-Based MySQL ativa",
              any(a.get("backend") == "mysql" and a.get("enable") for a in authn))
        authz = api("/authorization/sources")
        check("Fonte de autorizacao MySQL ativa",
              any(a.get("type") == "mysql" and a.get("enable") for a in authz["sources"]))

        database = pymysql.connect(host=host, port=mysql_port, user="lab_reader",
                                   password=secret["mysql_reader"], database="athlete_lab",
                                   autocommit=True, connect_timeout=8,
                                   cursorclass=pymysql.cursors.DictCursor)
        with database.cursor() as cursor:
            cursor.execute("SELECT VERSION() AS version")
            report["mysql_version"] = cursor.fetchone()["version"]

        for name, username, password, cid in [
            ("Senha incorreta recusada", TEST_DEVICE, "senha-incorreta-do-teste", TEST_DEVICE),
            ("Usuario inexistente recusado", "nao-cadastrado", "senha-de-teste", "nao-cadastrado"),
            ("Conexao anonima recusada", "", "", "anonimo-teste"),
            ("Client ID diferente do cadastro recusado", TEST_DEVICE, secret[TEST_DEVICE], "id-forjado"),
        ]:
            bad = probe(username, password, client_id=cid)
            check(name, bad.connect_code >= 128, f"CONNACK={bad.connect_code}")
            bad.close()

        observer = probe(OBSERVER)
        check("Observador conecta com credenciais validas", observer.connect_code == 0)
        check("Observador pode assinar telemetria", observer.subscribe("atletas/+/telemetria") == [1])
        check("Assinatura global # bloqueada", all(r >= 128 for r in observer.subscribe("#")))
        publisher = probe(TEST_DEVICE)
        check("Publicador conecta com credenciais validas", publisher.connect_code == 0)
        check("Publicador nao pode assinar topicos", all(r >= 128 for r in publisher.subscribe("atletas/+/telemetria")))

        boot_id = uuid.uuid4().hex
        report["test_boot_id"] = boot_id
        topic = f"atletas/{TEST_DEVICE}/telemetria"
        sample = {"schema_version": 1, "source": "test", "boot_id": boot_id,
                  "sample_seq": 0, "uptime_ms": 2000, "accel_x_g": 0.125,
                  "accel_y_g": -0.25, "accel_z_g": 0.98, "battery_mv": None,
                  "wifi_rssi_dbm": None}

        def rows(seq=None, topic_filter=None):
            query = "SELECT * FROM telemetry WHERE boot_id=%s"
            params = [boot_id]
            if seq is not None:
                query += " AND sample_seq=%s"
                params.append(seq)
            if topic_filter is not None:
                query += " AND topic=%s"
                params.append(topic_filter)
            with database.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()

        def await_rows(seq):
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                found = rows(seq)
                if found: return found
                time.sleep(0.2)
            return []

        def await_message(expected_topic, expected_payload, timeout=10):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try: found_topic, body = observer.messages.get(timeout=0.3)
                except queue.Empty: continue
                if found_topic == expected_topic and body == expected_payload.encode(): return True
            return False

        body = json.dumps(sample, separators=(",", ":"))
        check("Publicacao autorizada recebe PUBACK de sucesso", publisher.publish(topic, body) < 128)
        check("Observador recebe a mensagem publicada", await_message(topic, body))
        saved = await_rows(0)
        check("Mensagem MQTT gravada no MySQL", len(saved) == 1)
        row = saved[0]
        check("Valores e identidade preservados",
              row["mqtt_username"] == TEST_DEVICE and row["client_id"] == TEST_DEVICE
              and row["topic"] == topic and row["source"] == "test"
              and row["accel_x_g"] == sample["accel_x_g"]
              and row["accel_y_g"] == sample["accel_y_g"]
              and row["accel_z_g"] == sample["accel_z_g"]
              and json.loads(row["payload"]) == sample)
        publisher.publish(topic, body)
        time.sleep(1)
        check("Reenvio da mesma amostra nao duplica o registro", len(rows(0)) == 1)
        while not observer.messages.empty(): observer.messages.get_nowait()

        forbidden = f"atletas/{DEVICE}/telemetria"
        denied_code = publisher.publish(forbidden, body)
        check("Publicacao no topico de outro dispositivo bloqueada", denied_code >= 128,
              f"PUBACK={denied_code}")
        # A telemetria legitima do M5 pode continuar chegando durante o teste de ACL.
        check("Publicacao bloqueada nao chega ao observador", not await_message(forbidden, body, timeout=0.5))
        check("Publicacao bloqueada nao e persistida", len(rows(topic_filter=forbidden)) == 0)
        check("Observador nao pode publicar", observer.publish(topic, body) >= 128)

        invalid = dict(sample, sample_seq=2)
        invalid.pop("accel_z_g")
        publisher.publish(topic, json.dumps(invalid))
        time.sleep(1)
        check("Mensagem sem os campos obrigatorios nao e gravada", len(rows(2)) == 0)
        publisher.close()

        # Mesmo protocolo e QoS usados pelo firmware PubSubClient.
        firmware_protocol = probe(TEST_DEVICE, protocol=mqtt.MQTTv311)
        check("MQTT 3.1.1 aceito com autenticacao", firmware_protocol.connect_code == 0)
        sample["sample_seq"] = 1
        firmware_protocol.publish(topic, json.dumps(sample), qos=0)
        check("MQTT 3.1.1 QoS 0 gravado no banco", len(await_rows(1)) == 1)
        firmware_protocol.close()
        reconnect = probe(TEST_DEVICE, protocol=mqtt.MQTTv311)
        sample["sample_seq"] = 3
        reconnect.publish(topic, json.dumps(sample), qos=0)
        check("Nova conexao retoma a persistencia", len(await_rows(3)) == 1)
        report["persisted_test_row_ids"] = [r["id"] for r in rows()]
        report["action_metrics"] = api("/actions/mysql:lab_save/metrics")
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        # Excecoes podem conter contexto de bibliotecas. Nao registrar tokens/credenciais.
        report["error_type"] = type(exc).__name__
        print(f"Falha na validacao: {type(exc).__name__}. Consulte o ultimo teste.")
        raise
    finally:
        for p in probes:
            p.close()
        if database: database.close()
        evidence = ROOT / "evidencias"
        evidence.mkdir(exist_ok=True)
        write_json(evidence / "validacao-servidor.json", report)
        print("Relatorio: laboratorio/evidencias/validacao-servidor.json")


def verify_restart():
    settings = read_json(RUNTIME / "settings.json")
    if settings["profile"] != "local":
        raise ValueError("O teste automatico de reinicio e restrito ao ambiente local dedicado.")
    previous = read_json(ROOT / "evidencias/validacao-servidor.json")
    if not previous.get("passed"):
        raise ValueError("Execute verify com sucesso antes do teste de reinicio.")
    secret = load_secrets()
    def read_rows():
        with pymysql.connect(host="127.0.0.1", port=settings["mysql_port"], user="lab_reader",
                             password=secret["mysql_reader"], database="athlete_lab",
                             connect_timeout=8) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, payload FROM telemetry WHERE boot_id=%s ORDER BY id",
                               (previous["test_boot_id"],))
                return cursor.fetchall()
    before = read_rows()
    assert before, "Nao ha amostras da verificacao anterior"
    compose("stop")
    compose("up", "-d", "--wait", "--wait-timeout", "180")
    after = read_rows()
    report = {"executed_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Reinicio dos containers dedicados atleta-lab; volumes preservados",
              "test_boot_id": previous["test_boot_id"], "rows_before": len(before),
              "rows_after": len(after), "passed": before == after,
              "physical_device_tested": False}
    write_json(ROOT / "evidencias/validacao-reinicio.json", report)
    assert report["passed"], "Registros diferentes apos o reinicio"
    print(f"PASS Reinicio preservou {len(after)} registros e seus payloads.")
