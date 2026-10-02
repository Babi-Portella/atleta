# Diagrama completo — primeira versão revisada

![Arquitetura](../site/assets/diagrama-projeto-v1.svg)

O M5 publica pela rede local; o EMQX recebe, valida e envia a telemetria para o MySQL.
Os dois serviços rodam em containers Docker no computador servidor. O painel do atleta,
o navegador de administração e o programa de configuração USB rodam no Windows,
fora dos containers. Um único MySQL contém as tabelas `mqtt_users`, `mqtt_acl` e `telemetry`.

A GitPage é a apresentação estática do projeto, com documentação e downloads.
A API FastAPI do código original está separada do laboratório; sua ligação à telemetria
ainda é uma etapa futura. O cliente BLE, o aplicativo móvel e os sensores externos
também ficam identificados como expansões ou integrações pendentes.

```mermaid
flowchart LR
  subgraph PLACA[Dispositivo M5StickC Plus2]
    IMU[MPU6886: aceleração e rotação] -->|I²C / leitura a 50 Hz| FW[Firmware Arduino C++ 2.1.7]
    BAT[Botões e leitura da bateria] -->|GPIO / ADC| FW
    FW -->|SPI e controle| LCD[Tela: passos, sessão e sensores]
    NVS[Wi-Fi, MQTT e perfil em NVS] --> FW
    USB[USB-C / UART0] -->|Configuração| NVS
    USB -->|Gravação do firmware| FW
  end
  FW -->|Wi-Fi 2,4 GHz / MQTT 3.1.1 / QoS 0 / JSON a cada 2 s| LAN[Roteador / rede local]
  LAN -->|Rede cabeada / MQTT TCP 1883| EMQX
  subgraph SERVIDOR[Computador Windows / plataforma própria]
    subgraph DOCKER[Docker: dois containers]
      subgraph BROKER[Container EMQX]
        EMQX[Broker EMQX 6.1.1] --> RULE[Regra de validação e ação MySQL]
        DASH[Dashboard EMQX]
      end
      DB[(MySQL 8.4.8 / athlete_lab<br/>mqtt_users / mqtt_acl / telemetry)]
      EMQX <-->|SQL mysql:3306 / login bcrypt e ACL| DB
      RULE -->|SQL mysql:3306 / INSERT telemetry| DB
    end
    subgraph WINDOWS[Programas no Windows]
      PANEL[Painel do atleta: leituras e histórico]
      BROWSER[Navegador de administração]
      CONFIG[Programa de configuração e gravação do M5]
    end
    PANEL <-->|SQL local 127.0.0.1:33070 / lab_reader| DB
    BROWSER <-->|HTTP 18083| DASH
  end
  CONFIG <-->|USB / serial| USB
  subgraph PUBLICO[Apresentação pública]
    REPO[Repositório GitHub: fontes e documentação] -->|Publicação| PAGE[GitHub Pages: apresentação e downloads]
    PAGE <-->|HTTPS| VISITOR[Equipe / visitante]
  end
  subgraph FUTURO[Expansões e integrações pendentes]
    BLE[Cliente BLE: resumo opcional no M5, aplicativo remoto pendente]
    EXT[Sensores externos: BPM / SpO₂ / pele / GNSS]
    API[API FastAPI original: ligação à telemetria pendente]
    MOBILE[Aplicativo móvel: etapa futura]
  end
  FW -.->|Cliente remoto pendente| BLE
  EXT -.->|Hardware e ligações a definir| FW
  DB -.->|Integração pendente| API
  API -.->|Integração pendente| MOBILE
```

Na imagem, setas verdes representam o fluxo de dados implementado e setas lilás
representam configuração ou administração. As caixas tracejadas mostram etapas futuras.
A publicação MQTT indicada corresponde ao modo normal; a captura diagnóstica de IMU
usa mensagens adicionais quando ativada.

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
