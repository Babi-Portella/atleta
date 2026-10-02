# Validação do laboratório — atualizada em 10 de setembro de 2026

**Resultado: as três configurações de servidor passaram nos testes locais.
O firmware 2.0.0 foi instalado no M5StickC Plus2 físico e 15 leituras reais foram
comparadas integralmente com seus registros MySQL. A instalação em outro
computador do laboratório ainda precisa ser verificada naquele ambiente.**

## Conferência atual para entrega

Em 10/09/2026, às 12:55 (America/Fortaleza), o Docker e os serviços locais estavam
parados e foram iniciados pelo controlador do painel. EMQX e MySQL ficaram
saudáveis; as **28 verificações de servidor passaram novamente**.

A consulta direta encontrou **2.136 registros físicos** de `m5-atleta-01`,
identificados com `source=device`. A última leitura foi recebida em
**09/09/2026 às 23:59:50**, e não avançou entre as consultas desta conferência.
O cliente M5 não estava conectado ao EMQX; nenhuma porta serial estava presente.
Portanto, a gravação de leituras reais já foi comprovada, mas o envio físico ao
vivo não estava ativo nesta conferência. O teste de servidor usou sua própria
conta e mensagens `source=test`.

[validacao-entrega-atual.json](validacao-entrega-atual.json) registra esses dados.
Os três requisitos de configuração do professor estão atendidos neste computador.
Para demonstrar ao vivo, ligue o M5 com acesso à rede configurada, mantenha o
laboratório iniciado e confirme novas leituras em **Ver dados do atleta**.
A instalação e a conexão com outro servidor ainda exigem validação naquele local.

O fluxo é **M5 → Wi-Fi/MQTT → EMQX → regra/ação → MySQL**. MySQL é o banco;
EMQX é o broker MQTT; SQL é a linguagem usada nas consultas. BPM, temperatura da
pele e GPS externos continuam pendentes e não são requisitos explícitos do
enunciado fornecido pelo professor.

## Ambiente efetivamente testado

### Migração — painel 1.4.0

[validacao-migracao.json](validacao-migracao.json) registra o teste de 10/09/2026
em containers separados, com portas e credenciais próprias. O EXE preparou uma
pasta vazia sem Python no PATH. Foram restaurados **2.313 registros**, incluindo
**2.307 leituras físicas** e **6 registros de teste**; todos os IDs, horários,
identidades e payloads foram conferidos. Uma falha simulada após inserir o
primeiro lote reverteu a transação inteira. Repetir Iniciar não duplicou dados,
e um registro conflitante foi recusado sem substituir o conteúdo existente.

As **28 verificações de persistência, autenticação e autorização** passaram
também no servidor restaurado. Novas mensagens de teste coexistiram com o
histórico. Os containers de teste foram parados, preservando seus volumes para
inspeção; a instalação principal não foi interrompida.

[testes-painel-140.log](testes-painel-140.log) registra **46 testes aprovados**.
O EXE inclui o suporte RSA necessário ao primeiro login MySQL em uma instalação
nova. Os testes das janelas do executável estão em
[validacao-painel-exe.json](validacao-painel-exe.json) e
[validacao-dados-atleta-exe.json](validacao-dados-atleta-exe.json).

Esta validação cobre uma instalação isolada neste PC. O Windows, Docker, USB e
a rede do computador de destino ainda dependem da execução naquele ambiente.

### Instalação principal

- EMQX 6.1.1 e MySQL 8.4.8 em containers Linux reais no Docker Desktop.
- Stack dedicada `atleta-lab`, com volumes persistentes.
- Testes iniciais em `127.0.0.1`; MQTT 18830, Dashboard 18084, MySQL 33070.
- Validação física posterior com servidor `192.168.0.67` nas mesmas portas,
  acesso MQTT pela rede habilitado e MySQL restrito a loopback. M5: `192.168.0.118`.
- Clientes Python/Paho em MQTT 5 e MQTT 3.1.1.
- Mensagens sintéticas com `source=test` e usuário `lab-teste-01`.
- Firmware Arduino C++ para M5StickC Plus2, usando M5Unified 0.2.21,
  M5GFX 0.2.28, ArduinoJson 7.4.2 e PubSubClient 2.8.
- PlatformIO Core 6.1.18, plataforma espressif32 6.10.0, flash configurada em 8 MB.

Nenhuma leitura sintética foi apresentada como medição do atleta. Os testes de
servidor originais usaram clientes Python; a validação física posterior está
registrada separadamente, com `source=device` e a identidade `m5-atleta-01`.

## M5 físico — firmware 2.0.0

[validacao-m5-fisico.json](validacao-m5-fisico.json), executado às 22:47 de
09/09/2026 no fuso America/Fortaleza (01:47 UTC de 10/09), comprova:

- Placa na COM4: ESP32-PICO-V3-02, flash de 8 MB e PSRAM de 2 MB.
- MPU6886 com identificação `0x19`, aceleração e rotação reais; leitura de bateria.
- Resposta do RTC interno em `0x51`; nenhum endereço I²C no Grove SDA32/SCL33.
  Isso não identifica sensores analógicos nem outros pinos.
- Wi-Fi conectado e cliente MQTT autenticado. **15 amostras USB com JSON idêntico
  ao armazenado no MySQL**, pareadas por `boot_id` e `sample_seq`.
- Pausa e retomada da sessão; duração e passos congelados durante a pausa.
- BLE ligado e desligado na placa. Comunicação com cliente remoto não testada.
- Oito autotestes de detecção e fórmulas aprovados, incluindo repouso, rotação,
  amostras inválidas, lacunas, picos regulares e perfil ausente. Os dados sintéticos
  do autoteste ficam isolados e não são publicados como telemetria real.

O relatório registra o SHA-256 do firmware; o manifesto marca a imagem como
testada fisicamente somente quando esse hash corresponde à imagem empacotada.
[amostras-m5-fisico.json](amostras-m5-fisico.json) preserva as leituras comparadas.
Foi salvo um backup privado completo de 8 MB antes da primeira gravação, fora do ZIP.

## Resultado dos testes de servidor

O arquivo [validacao-servidor.json](validacao-servidor.json) registra **28 verificações
aprovadas**, com versões, identificação das amostras e horário em UTC.

| Requisito | Evidência obtida |
| --- | --- |
| Persistência MQTT → MySQL | Conector e ação conectados; regra habilitada; mensagem recebida pelo assinante e gravada no banco com os valores, JSON, tópico e identidade corretos. |
| Autenticação MySQL | Login válido aceito; senha errada, conexão anônima, usuário desconhecido e Client ID diferente do cadastro recusados. |
| Autorização MySQL | Publicador limitado ao seu próprio tópico; assinante limitado aos tópicos de telemetria; publicação indevida, assinatura global e operações sem permissão bloqueadas. |
| Integridade das amostras | Reenvio não duplica a mesma amostra; mensagem incompleta não é gravada; publicação proibida não chega ao assinante nem ao banco. |
| Compatibilidade MQTT do firmware | MQTT 3.1.1 com QoS 0 gravado no MySQL; nova conexão retoma a persistência. O cliente desta verificação é Python, não a placa. |

As métricas agregadas da ação são uma fotografia do instante da consulta e podem
ter atualização posterior. As verificações de persistência consultaram diretamente
as linhas e os payloads do MySQL.

## Persistência após reinício

[validacao-reinicio.json](validacao-reinicio.json) registra a parada e a nova
inicialização dos dois containers dedicados. Os **3 registros** da execução
anterior permaneceram no banco, com os mesmos IDs e payloads. Os volumes não
foram excluídos.

## Firmware e entrega

[compilacao.log](compilacao.log) contém a saída da compilação final. O pacote inclui
os segmentos de bootloader, partições e aplicativo, além da imagem unificada.
O processo de empacotamento verifica no cabeçalho da imagem unificada a configuração
de flash de 8 MB e gera [manifest.json](../entrega/firmware/manifest.json) com
SHA-256 dos arquivos.

O ZIP usa uma lista explícita de arquivos e é verificado por integridade. A pasta
`runtime`, a configuração Wi-Fi local, o ambiente Python e os caches de compilação
ficam fora da entrega. O empacotamento procura também as credenciais geradas nos
arquivos selecionados, incluindo senhas Wi-Fi/MQTT dos arquivos locais, e falha
caso encontre alguma.

A API original `main.py` permaneceu com SHA-256:

```text
843A4481B5B9860BDA46F86DD94673860A4587F8843D0250D0837AEA336658A7
```

## O que ainda não foi comprovado

1. Precisão de passos em caminhada/corrida real, distância, calorias e autonomia.
2. Aparência física da tela e ergonomia dos botões observadas pelo usuário;
   a placa executou o firmware e comandos USB, mas não houve captura da sua tela.
3. Comunicação BLE com cliente remoto.
4. BPM, temperatura da pele e GPS externos: modelos, ligações e leituras pendentes.
5. Conectividade e configuração no outro computador do laboratório/professor.

O firmware envia pelo Wi-Fi usando MQTT/TCP sem TLS e QoS 0. Não implementa uma
fila persistente para amostras capturadas sem conexão; o contador da tela indica
envio local ao socket. A confirmação final exige consultar o banco.

Passos foram implementados como estimativa experimental. Distância e calorias
foram implementadas como cálculos e dependem dos parâmetros do perfil configurado
no M5; quando esses parâmetros faltam, são enviadas como `null`.
BPM, temperatura da pele e GPS permanecem `null`, com
estados explícitos de sensor não configurado. Consulte [FIRMWARE_M5.md](../docs/FIRMWARE_M5.md).

## Reproduzir

Na pasta que contém `laboratorio/`, com Docker funcionando:

```powershell
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py up
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py verify
# Com o M5 configurado e conectado por USB; pausa/retoma a sessão e testa BLE:
.\.venv-lab\Scripts\python.exe laboratorio\tools\verify_device.py --port COM4
# Apenas em perfil local e quando uma interrupção do laboratório for desejada:
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py verify-restart
.\.venv-lab\Scripts\python.exe laboratorio\tools\lab.py stop
```

`verify-restart` é restrito ao perfil local e interrompe somente a stack dedicada.
Os relatórios JSON são substituídos por cada nova execução.
