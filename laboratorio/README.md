# Laboratório — M5StickC Plus2 → EMQX → MySQL

**O IP pode ser informado depois.** O firmware recebe rede Wi-Fi, IP/domínio,
porta e credencial MQTT por USB e salva a configuração na placa. Não é necessário
recompilar quando o endereço do servidor mudar.

**Painel simples para Windows:** abra [`PainelIP.exe`](entrega/PainelIP.exe) e
clique em **Iniciar laboratório e abrir Dashboard**. Ele prepara os arquivos,
inicia o Docker Desktop instalado, sobe EMQX/MySQL e salva o IP. Inclui um botão
para parar sem apagar dados. Veja [as instruções do painel](docs/PAINEL_IP.md).
Na versão **1.2.0**, o botão **Configurar Wi-Fi e perfil do M5 por USB** também
envia rede, endereço e perfil opcional para uma placa com este firmware.
Na versão **1.3.0**, clique em **Ver dados do atleta** para acompanhar as leituras
reais salvas no MySQL. A janela inclui cartões, atualização automática, aviso de
leitura antiga e histórico recente. Veja [Dados do atleta](docs/DADOS_ATLETA.md).
Na versão **1.4.0**, o pacote privado de migração também restaura automaticamente
o histórico em outro computador, com conferência integral e sem duplicar registros.
Veja [o primeiro uso em outro PC](docs/PRIMEIRO_USO_OUTRO_PC.txt).

## Escopo e estado real

Entrega para o enunciado do professor: primeiras leituras reais de um sensor,
persistência MySQL, autenticação dos clientes e autorização de tópicos.

| Parte | Implementação | Validação |
| --- | --- | --- |
| Firmware 2.1.7 | M5StickC Plus2, MPU6886, bateria, sessão, contador experimental com filtro suavizado, proteção contra picos precoces e rotações rápidas e sensibilidade durante marcha confirmada; diagnóstico de dez minutos por Wi-Fi. | Compilado e gravado na COM3, com Wi-Fi/MQTT ativos e autotestes aprovados. No novo teste físico, registrou 17 de 20 passos no espaço pequeno, com zero passos falsos ao colocar e manusear o relógio. Ainda perdeu três passos; uma única caminhada não estabelece precisão geral. Veja [as evidências da 2.1.7](evidencias/contador-passos-2.1.7.json). |
| Persistência | Conector, regra e ação MySQL; identidade MQTT e JSON da leitura. | 15 amostras reais do M5 comparadas integralmente com os registros MySQL, além dos testes anteriores com dados sintéticos. |
| Autenticação | MySQL com hash bcrypt; usuário e Client ID vinculados. | Credenciais válidas aceitas; senha incorreta, anônimo, usuário desconhecido e Client ID indevido recusados. |
| Autorização | ACL MySQL; ausência de permissão resulta em bloqueio. | Publicação e assinatura autorizadas e proibidas verificadas. |
| Reinício | Volumes persistentes de EMQX e MySQL. | Registros e payloads preservados após reiniciar os containers de teste. |
| Outro servidor do laboratório | Kit e guia disponíveis; este PC já recebe o M5 pela rede. | A instalação e conectividade em outro computador ainda precisam ser verificadas lá. |

Consulte [o relatório](evidencias/VALIDACAO.md),
[a validação física](evidencias/validacao-m5-fisico.json),
[os testes de servidor](evidencias/validacao-servidor.json) e
[a compilação](evidencias/compilacao.log).

## Hardware e primeira mensagem

Modelo confirmado: [M5StickC Plus2 com pulseira](https://shop.m5stack.com/products/m5stickc-plus2-with-watch-accessories).
O firmware usa o acelerômetro MPU6886 interno, sem ligações externas para o
primeiro laboratório. Mantém HOLD no GPIO4 e apresenta leitura e conexão na tela.
O projeto é **Arduino C++**, compilado com PlatformIO e M5Unified; não é C puro.
Recursos, botões, estimativas e limitações estão no [guia do firmware](docs/FIRMWARE_M5.md).
O [contexto do projeto](docs/CONTEXTO_PROJETO.md) registra as expansões de hardware pendentes.

Publicação a cada 2 segundos em `atletas/m5-atleta-01/telemetria`. Sem uma leitura
válida, o firmware informa erro e não publica valores inventados. Sem configuração
de rede, continua mostrando e imprimindo as leituras reais do acelerômetro.

Exemplo **sintético** do formato; no firmware a origem é `source: "device"`:

```json
{
  "schema_version": 1,
  "source": "test",
  "boot_id": "exemplo-sintetico",
  "sample_seq": 0,
  "uptime_ms": 2000,
  "accel_x_g": 0.125,
  "accel_y_g": -0.25,
  "accel_z_g": 0.98,
  "battery_mv": null,
  "wifi_rssi_dbm": null
}
```

O MySQL define o horário de recepção e armazena tópico e identidade autenticada.
`uptime_ms` é tempo desde a inicialização. Usuário + boot_id + sample_seq formam
a chave de deduplicação de uma mesma amostra.

## Arquivos

- `firmware/src/main.cpp`: código da placa.
- `entrega/firmware/`: imagem compilada, segmentos e checksums.
- `sql/01-schema.sql`: tabelas, separadas da API existente.
- `emqx/*.sql`: regra, inserção, consulta de autenticação e consulta de ACL.
- `compose.yaml`: stack dedicada com versões e digests fixados.
- `tools/lab.py`: preparação, inicialização, configuração USB e testes.
- `docs/DASHBOARD.md`: configuração pelo painel.
- `runtime/`: credenciais e configurações locais, excluídas do ZIP e do Git.

## Preparação no Windows

Requer Python 3.10+ e Docker com containers Linux. Execute os comandos na pasta
que contém `laboratorio/`:

```powershell
# Dependências, credenciais e arquivos; ainda não precisa do IP.
.\laboratorio\preparar.ps1

# Ambiente de teste local; Docker precisa estar funcionando.
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py up
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py verify
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py status

# Para apenas o laboratório, preservando os volumes.
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py stop
```

Uma nova instalação com perfil local publica apenas em `127.0.0.1`: Dashboard
`18084`, MQTT `18830` e MySQL `33070`. Neste PC o acesso pela rede foi habilitado
preservando essas portas: servidor `192.168.0.67`, M5 `192.168.0.118`, no teste de
09/09/2026. IPs podem mudar. Os containers não iniciam automaticamente com o Docker.

## Instância dedicada no servidor

Se o professor já possui EMQX, use [o guia manual](docs/DASHBOARD.md). O Compose
destina-se a uma instância dedicada e não substitui um broker compartilhado.
Portas já ocupadas precisam ser resolvidas antes de iniciar outra instância.

Em uma **nova cópia do pacote**, no servidor Windows:

```powershell
.\laboratorio\preparar.ps1 -Perfil server -Iniciar
```

No Linux, na pasta que contém `laboratorio/`:

```bash
python3 -m venv .venv-lab
.venv-lab/bin/python -m pip install -r laboratorio/requirements.txt
.venv-lab/bin/python laboratorio/tools/lab.py init --profile server
.venv-lab/bin/python laboratorio/tools/lab.py up
.venv-lab/bin/python laboratorio/tools/lab.py verify --mqtt-port 1883 --dashboard-port 18083
```

Em uma instalação nova com perfil servidor, MQTT `1883` e Dashboard `18083`
ficam acessíveis pela rede. Ao mudar a opção de rede pelo painel em uma instalação
existente, as portas anteriores são preservadas; confira os valores exibidos.
O MySQL é publicado apenas em `127.0.0.1:33070` do servidor. Entre containers,
o conector usa `mysql:3306`. A rede/firewall deve permitir acesso da placa ao MQTT.
O perfil é guardado e não muda por engano ao executar `init` novamente.
Credenciais existentes são preservadas.

Versões testadas: EMQX **6.1.1**, MySQL **8.4.8**. Em outro EMQX, conferir versão
e disponibilidade da integração MySQL antes de aplicar os arquivos.

## Quando o IP estiver disponível

No servidor, preencher `laboratorio/config.local.json`:

```json
{
  "wifi_ssid": "NOME_DA_REDE_2_4_GHZ",
  "wifi_password": "SENHA_DA_REDE",
  "mqtt_host": "IP_OU_DOMINIO_DO_SERVIDOR",
  "mqtt_port": 1883,
  "device_id": "m5-atleta-01"
}
```

Não usar `localhost` ou `http://` no host MQTT da placa. Esta versão usa MQTT/TCP
na rede do laboratório; TLS não está implementado.

Cada instalação gera suas próprias credenciais. Para configurar a placa em outro
computador, exporte apenas a configuração do dispositivo no servidor:

```powershell
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py export-device-config
```

Transfira `laboratorio/runtime/device-config.json` de forma privada para o PC que
grava a placa. Ele contém somente a credencial MQTT da placa e a configuração
Wi-Fi preenchida, sem senhas administrativas. Se tudo for configurado no mesmo
ambiente que gerou o banco, pode usar `config.local.json` diretamente.

## Gravar e configurar a placa

Conecte o M5 por cabo USB de dados. Troque `COM5` pela porta real:

```powershell
.\.venv-lab\Scripts\python.exe -m platformio device list
.\.venv-lab\Scripts\python.exe laboratorio\tools\flash.py --port COM5

# Configuração exportada pelo servidor:
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py configure-device --port COM5 --config laboratorio\runtime\device-config.json

# Alternativa: credenciais e configuração deste próprio ambiente:
# .\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py configure-device --port COM5

.\.venv-lab\Scripts\python.exe -m platformio device monitor --port COM5 --baud 115200
```

Feche o monitor serial antes de gravar ou configurar. `flash.py` verifica os
hashes e grava os segmentos de bootloader, partições e aplicativo, sem apagar
toda a flash. Esse comando preserva a região NVS usada pela configuração do
laboratório e substitui o aplicativo atual da placa.

A imagem unificada em `entrega/firmware/` usa offset `0x0`; por preencher os
intervalos entre segmentos, sua gravação também reinicializa a região de
configuração. Prefira `flash.py` para preservar a configuração entre atualizações.

Esperado no serial: `CONFIG_OK`, reinício, `MQTT_CONNECTED` e `TELEMETRY` com
`source: "device"`. Senhas não são impressas.

O firmware publica com **MQTT 3.1.1 / QoS 0**. O contador da tela confirma envio
local ao socket, não a gravação no banco. Amostras durante desconexão não são
guardadas para reenvio; confirme a persistência no servidor.

## Conferência física final

1. Conferir `m5-atleta-01` conectado em Monitoring → Clients.
2. Mover a placa e observar mudanças nos eixos.
3. Consultar o MySQL:

```sql
SELECT received_at, mqtt_username, accel_x_g, accel_y_g, accel_z_g, source
FROM athlete_lab.telemetry
WHERE mqtt_username = 'm5-atleta-01' AND source = 'device'
ORDER BY id DESC LIMIT 10;
```

4. Executar `verify` no servidor para testar senha e ACL. Ele usa `lab-teste-01`,
   sem desconectar a placa `m5-atleta-01`, e identifica os dados como teste.
5. Registrar cliente conectado, regra/ação com sucesso e resultado da consulta.
   A transmissão física foi comprovada neste PC; veja [o relatório físico](evidencias/validacao-m5-fisico.json).
   Para repetir o teste da placa, execute `tools/verify_device.py --port COM4`
   com o Python do laboratório. Ele pausa/retoma a sessão e liga/desliga BLE.

As senhas geradas estão em `runtime/secrets.json`: Dashboard (`admin`), MySQL e
MQTT. Nesta stack a senha administrativa é gerada; não é `public`.
O SQL de inicialização roda automaticamente **somente no primeiro volume vazio**
do MySQL. Editá-lo depois não migra o banco existente.

## Recompilar e empacotar

```powershell
.\.venv-lab\Scripts\python.exe laboratorio\tools\release.py
```

O pacote usa uma lista explícita de arquivos e verifica que as credenciais
geradas não apareçam na entrega. A API `main.py` original permanece independente.

## Referências

- [Hardware Plus2](https://docs.m5stack.com/en/core/M5StickC%20PLUS2)
- [M5Unified](https://github.com/m5stack/M5Unified)
- [Persistência MySQL](https://docs.emqx.com/en/emqx/latest/data-integration/data-bridge-mysql.html)
- [Autenticação MySQL](https://docs.emqx.com/en/emqx/latest/access-control/authn/mysql.html)
- [Autorização MySQL](https://docs.emqx.com/en/emqx/latest/access-control/authz/mysql.html)
