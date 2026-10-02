# Diagrama completo — primeira versão

![Arquitetura](../site/assets/diagrama-projeto-v1.svg)

O caminho implementado termina no painel Windows do atleta. A GitPage é a apresentação
estática do projeto e não acessa o banco nem o broker. A API FastAPI do código original
está separada do laboratório; a ligação da telemetria à API ainda é uma etapa futura.

```mermaid
flowchart LR
  subgraph PLACA[Dispositivo M5StickC Plus2]
    IMU[MPU6886 interno: aceleração e rotação] --> FW[Firmware Arduino C++ 2.1.7]
    BAT[Bateria interna e botões] --> FW
    FW --> LCD[Tela: sessão e sensores]
    NVS[Configuração Wi-Fi, MQTT e perfil em NVS] --> FW
  end
  USB[PC: configuração e gravação por USB] --> NVS
  FW -->|Wi-Fi 2,4 GHz / MQTT 3.1.1 / QoS 0 / JSON a cada 2 s| EMQX
  subgraph SERVIDOR[Plataforma própria: Docker no servidor]
    EMQX[EMQX 6.1.1] --> RULE[Regra de telemetria e ação MySQL]
    RULE --> DB[(MySQL 8.4.8: athlete_lab.telemetry)]
    EMQX <-->|Login bcrypt e ACL por usuário/tópico| AUTH[(mqtt_users e mqtt_acl)]
    DB -->|Consulta com usuário lab_reader| PANEL[Painel Windows: dados do atleta]
  end
  EMQX --> DASH[Dashboard EMQX: administração]
  FW -.->|BLE opcional: cliente remoto pendente| BLE[Aplicativo BLE futuro]
  EXT[BPM / temperatura da pele / GNSS: hardware pendente] -.-> FW
  DB -.->|Integração ainda não implementada| API[API FastAPI original]
  PAGE[GitHub Pages: apresentação e downloads]
```

## Contrato de dados

Tópico de produção: `atletas/m5-atleta-01/telemetria`.
Campos obrigatórios da regra: `schema_version=1`, `source=device` ou `test`,
`boot_id`, `sample_seq` inteiro não negativo e aceleração X/Y/Z numérica.
O broker fornece a identidade autenticada, o Client ID e o tópico ao banco.
A chave única é `(mqtt_username, boot_id, sample_seq)`.
`received_at` é a recepção no banco; `uptime_ms` é o tempo desde o boot da placa.

## Modelo de dados

```mermaid
erDiagram
  mqtt_users ||--o{ mqtt_acl : autoriza
  mqtt_users ||--o{ telemetry : publica
  mqtt_users {
    varchar username PK
    varchar client_id UK
    varchar password_hash
    boolean enabled
  }
  mqtt_acl {
    bigint id PK
    varchar username FK
    enum permission
    enum action
    varchar topic
  }
  telemetry {
    bigint id PK
    timestamp received_at
    varchar mqtt_username FK
    varchar client_id
    varchar topic
    varchar boot_id
    bigint sample_seq
    enum source
    double accel_x_g
    double accel_y_g
    double accel_z_g
    json payload
  }
```

Portas no perfil servidor novo: MQTT `1883`, Dashboard `18083` e MySQL
`127.0.0.1:33070`; entre containers, MySQL `mysql:3306`.
O endereço real é configurável e não é fixado nos diagramas.
Referência: [integração MySQL do EMQX](https://docs.emqx.com/en/emqx/latest/develop/data-integration/data-bridge-mysql.html).
