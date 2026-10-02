# M5StickC Plus2 — firmware 2.1.7

O programa da placa está em [main.cpp](../firmware/src/main.cpp), com o detector
de passos e as fórmulas em [activity.h](../firmware/src/activity.h). Os recursos
disponíveis funcionam por USB e na tela mesmo sem conexão de rede.

O detector 2.1.1 ignora picos separados por menos de 320 ms e exige quatro picos
com cadência plausível antes de confirmar uma caminhada. Ao confirmar, inclui os
quatro picos iniciais no total. A tolerância de intervalo passou de ±30% para ±50%
da cadência filtrada, para não descartar sequências durante partida ou mudança
moderada de ritmo. Um teste de oito picos com intervalo de 500 para 720 ms contava
cinco na versão 2.1.0 e conta oito na 2.1.1. Isso é uma regressão sintética; a
precisão da caminhada no pulso ainda precisa ser medida.

Uma tentativa de leitura
do IMU sem amostra nova não zera a sequência; só uma ausência prolongada ou uma
leitura inválida a interrompe. Essas mudanças reduzem contagens por batidas
isoladas e picos duplos, mas movimentos rítmicos do braço ainda podem parecer
passos para um único acelerômetro no pulso.

As versões 2.1.2/2.1.3 acrescentam diagnóstico por USB e Wi-Fi; a 2.1.4 amplia
a gravação para dez minutos e identifica o instante inicial. Nessas versões,
o detector é o mesmo da 2.1.1. O teste no pulso
relatou 7 registros para 5 passos e ausência de registros em outros movimentos.

A 2.1.5 suaviza a aceleração com coeficiente 0,25, ignora picos precoces sem
substituir a referência de cadência e, durante uma sequência já confirmada,
reduz o limiar de 0,12 g para 0,06 g. Depois de uma parada superior a 1,5 s,
o limiar inicial volta a ser exigido. Os limites de intervalo e a confirmação
de quatro picos continuam em vigor.

No reprocessamento C++ de 12.918 amostras reais, o detector anterior registrou
8 passos ao colocar/digitar com o relógio, zero na caminhada relatada de dez
passos e 6 no manuseio sem caminhada. A 2.1.5 produziu respectivamente 0, 7 e 0.
Isso mostra uma melhora nesses dados e três passos ainda perdidos; não estabelece
precisão geral. O teste físico posterior está descrito a seguir. Veja
[o relatório da alteração](../evidencias/contador-passos-2.1.5.json).

No teste físico posterior, a 2.1.5 registrou 13 dos 20 passos curtos relatados,
sem acrescentar passos ao colocar ou manusear o relógio. A tentativa 2.1.6
reduziu o limiar inicial para 0,11 g e estendeu o intervalo de sequências lentas
até 1,8 s. Foi rejeitada no teste seguinte: registrou nove passos ao colocar
o relógio no pulso, antes de começar a caminhada. Veja
[seu relatório](../evidencias/contador-passos-2.1.6.json).

A 2.1.7 mantém o limiar inicial de 0,11 g e restaura o intervalo máximo de 1,5 s
para todas as sequências. Usa também o giroscópio: rotação resultante acima de
400 graus/s interrompe a sequência e exige 1,2 s sem outro movimento desse tipo
antes de retomar a detecção. Leituras inválidas também iniciam essa espera.
Essa proteção pode descartar passos durante rotações rápidas do pulso; o M5
não possui um sensor configurado para verificar se está sendo usado no pulso.

No reprocessamento C++, a 2.1.7 produziu 7 registros para a caminhada de dez
passos, 22 para a caminhada de vinte passos curtos e zero nos trechos de
preparação/manuseio das três capturas, incluindo o trecho que havia produzido
nove falsos registros. Esses dados foram usados para ajustar o detector e não
constituem validação independente.

Na nova captura física com a 2.1.7, o contador ficou em zero ao colocar o relógio
no pulso, registrou 17 dos 20 passos no espaço pequeno e permaneceu em 17 após
retirar e balançar o aparelho sem caminhar. Foram três passos a menos (erro de
−15% nesse teste), com zero registros falsos na preparação e no manuseio.
É uma única caminhada; não estabelece precisão geral. A captura contém 12.113
amostras, sem mudança de sessão ou linha malformada. As cinco lacunas acima de
60 ms ocorreram depois do último incremento registrado. Veja
[as evidências da 2.1.7](../evidencias/contador-passos-2.1.7.json).

## Recursos e origem dos valores

| Recurso | Implementação | Limite |
| --- | --- | --- |
| Aceleração e rotação | MPU6886 interno, leituras a 50 Hz. | A montagem no pulso influencia o movimento medido. |
| Passos | Detector experimental de picos com filtragem, intervalo mínimo de 320 ms e confirmação de quatro picos com tolerância de ±50% na cadência. | Menos de quatro picos não confirmam caminhada. Movimentos rítmicos do braço ainda podem ser confundidos com passos; a precisão física não foi calibrada. |
| Sessão | Tempo ativo, pausa, retomada e nova sessão. | Reiniciar a placa inicia outra sessão. |
| Distância | Passos × comprimento informado de um passo. | Estimativa; fica `null` sem comprimento informado. |
| Calorias | MET informado × peso em kg × horas ativas. | Estimativa de energia bruta; o sensor não mede MET nem calorias. Fica `null` sem peso e MET. |
| Ritmo | Minutos ativos / distância estimada. | Média da sessão; fica `null` sem distância positiva. |
| Bateria | Tensão interna em mV e percentual estimado pela biblioteca M5Unified. | Percentual baseado em tensão; durante carga pode variar. |
| Wi-Fi | Rede de 2,4 GHz, RSSI e reconexão. | SSID diferencia maiúsculas de minúsculas. |
| MQTT | Cliente autenticado publica no tópico permitido pelo MySQL/ACL. | QoS 0; a fila mantém somente a leitura mais recente. |
| Bluetooth | Serviço BLE próprio com leitura/notificação de resumo de passos, duração e bateria. | Desligado ao iniciar; ativação pela placa ou comando USB. Cliente remoto ainda precisa de teste. |
| BPM | Campo e estado de disponibilidade definidos. | Nenhum sensor de pulso foi identificado/configurado; valor `null`. |
| Temperatura da pele | Campo e estado de disponibilidade definidos. | Exige sensor externo adequado; valor `null`. |
| GPS | Latitude, longitude e estado definidos. | Exige módulo GNSS externo; coordenadas `null`. |

A temperatura interna da eletrônica não é usada como temperatura da pele.
O módulo HW-827 da foto não informa seu modelo por USB; sua alimentação e
pinagem devem ser confirmadas visualmente antes de implementar a leitura.

## Botões do M5

- **A curto:** pausar ou retomar a sessão.
- **A por 1,2 segundo:** começar outra sessão e zerar os contadores da sessão.
- **B curto:** alternar entre atividade, sensores internos e módulos externos.
- **B por 1,2 segundo:** ligar ou desligar o Bluetooth.

O botão de energia mantém o comportamento do hardware. A configuração da rede
fica salva na memória NVS; mudar IP, Wi-Fi ou perfil não exige recompilar.

## Configurar pelo programa Windows

1. Inicie o laboratório pelo `PainelIP.exe` com **Permitir conexão do M5 pela rede**.
2. Clique em **Configurar Wi-Fi e perfil do M5 por USB**.
3. Preencha o nome exato da rede e a senha. A senha fica mascarada e é salva localmente.
4. O perfil é opcional: peso, comprimento de um passo em metros, intensidade MET e ID do atleta.
5. Clique em **Salvar configuração** e depois em **Enviar ao M5 por USB**.
6. A confirmação `CONFIG_OK` significa que a placa salvou os parâmetros e vai reiniciar.

O campo MET representa uma intensidade informada para a atividade. Consulte a
[definição de MET do Compêndio de Atividades Físicas](https://pacompendium.com/)
e a [tabela de caminhada](https://pacompendium.com/walking/) ao escolher esse parâmetro.
Como referência, o Compêndio lista 3,8 MET para caminhada moderada em terreno plano,
entre 2,8 e 3,4 mph. O programa deixa os parâmetros em branco até serem informados.

A janela envia configurações a um M5 que já esteja com este firmware. Ela não
substitui o procedimento de gravação da imagem.

## Gravar a imagem em outra placa

O kit contém os segmentos e um manifesto de checksums em `entrega/firmware/`.
O comando abaixo confere os hashes e grava os segmentos do aplicativo, bootloader
e partições, preservando a configuração em NVS. Para a placa original foi salvo
um backup privado completo de 8 MB antes da primeira gravação, em `runtime/backups/`.

```powershell
.\.venv-lab\Scripts\python.exe laboratorio\tools\flash.py --port COM4
```

A porta é específica de cada computador. O backup inclui o conteúdo da memória
da placa e pode conter configurações privadas; ele não é incluído na entrega.

## Comandos USB

Porta serial a 115200 baud, com comandos terminados por nova linha. Algumas
interfaces reiniciam ao abrir a porta; aguarde três segundos antes do primeiro comando.

| Comando | Resposta / efeito |
| --- | --- |
| `STATUS` | Versão, configuração presente, estados Wi-Fi/MQTT/IMU/BLE e contadores. |
| `INVENTORY` | Chip, memória, identificação do MPU6886, resposta do RTC e estado da rede. |
| `SCAN_I2C` | Consulta endereços no Grove SDA32/SCL33; não identifica sensores analógicos ou outros pinos. |
| `SCAN_WIFI` | Busca redes de 2,4 GHz; mostra somente correspondências ao nome configurado, ignorando caixa para sugerir o nome exato. Interrompe a associação momentaneamente e retoma após a busca. |
| `SELFTEST` | Testa o detector e as fórmulas em instâncias separadas, sem alterar os passos reais nem publicar dados sintéticos. |
| `SESSION START` | Nova sessão. |
| `SESSION PAUSE` / `SESSION RESUME` | Pausa / retomada. |
| `BLE ON` / `BLE OFF` | Ativar / desativar comunicação Bluetooth. |
| `CONFIG {json}` | Validar e salvar configuração; nunca devolve a senha. |

O fluxo contínuo `TELEMETRY {json}` contém as leituras reais a cada dois segundos.
Os diagnósticos usam prefixos próprios para não serem confundidos com telemetria.

## Telemetria e MySQL

O tópico é `atletas/m5-atleta-01/telemetria`. A autenticação usa a conta MQTT do
dispositivo; a ACL permite publicar somente nesse tópico. O Dashboard tem outra conta.

O contrato mantém `schema_version: 1`, `source: "device"`, `boot_id`, `sample_seq`
e os três campos de aceleração exigidos pela regra existente. A extensão adiciona
os campos do projeto: `athlete_id`, `sessao`, `duracao_s`, `passos`, `distancia_km`,
`calorias_kcal`, `ritmo_min_km`, `accel_g`, `bpm`, `latitude`, `longitude`, `gps`,
`wifi`, `bluetooth`, `temperatura_pele_c`, `gyro_dps` e bateria.

`measurement_status` informa quais campos são estimados ou indisponíveis.
O JSON completo é salvo na coluna `athlete_lab.telemetry.payload`, preservando
os campos adicionais sem alterar as tabelas existentes. Uma confirmação de envio
MQTT local não comprova persistência; a validação compara o JSON recebido por USB
com o JSON efetivamente armazenado para o mesmo `boot_id` e `sample_seq`.

O caminho do laboratório é **M5 → Wi-Fi/MQTT → EMQX → regra MySQL → telemetry**.
A API HTTP original da raiz não participa desse caminho e ainda exige adaptação
dos campos opcionais antes de receber medições com sensores indisponíveis.

## Bluetooth

- Nome anunciado: `Atleta-M5`.
- Serviço: `747e1000-7e91-4e27-a560-697562673001`.
- Característica de leitura/notificação: `747e1001-7e91-4e27-a560-697562673001`.
- Pacote de 16 bytes, inteiros little-endian: byte 0 versão (1), byte 1 flags
  (bits 0 sessão ativa, 1 IMU, 2 Wi-Fi, 3 MQTT), bytes 2–5 passos, bytes 6–9 duração
  em segundos, bytes 10–11 bateria em mV (`65535` se ausente), byte 12 percentual
  estimado (`255` se ausente); bytes 13–15 reservados.

O serviço não oferece escrita de configurações e não transporta senhas. Ele deve
ser ativado pela pessoa que opera a placa; iniciar o M5 deixa o Bluetooth desligado.

## Validar a placa

```powershell
.\.venv-lab\Scripts\python.exe laboratorio\tools\verify_device.py --port COM4
```

Esse teste consulta sensores, executa autotestes, pausa/retoma a sessão e liga/desliga
o BLE. Confere amostras reais no MySQL e salva as evidências. Use durante validação,
pois altera momentaneamente a sessão. Não avalia precisão esportiva ou médica.

Para medir a precisão do contador, use o M5 no mesmo pulso durante três caminhadas
de 100 passos contados manualmente, em ritmo habitual. Anote o valor inicial e o
final da tela em cada caminhada, sem reiniciar a placa entre as duas leituras.
Compare cada diferença com 100; o autoteste sintético não substitui essa medição.

Regressões nativas em `firmware/tests/step_counter_native.cpp` cobrem mudança de
cadência na partida e durante caminhada, repouso, rotação, sinal fraco, picos
duplos e batidas irregulares. O arquivo mantém os `assert`s ativos mesmo quando
o compilador define `NDEBUG` em otimização. O comando USB `SELFTEST` também inclui
`short_walk_variable_cadence` e `variable_cadence_steps` (esperado: 8).

## Capturar sinais para calibrar o contador

1. Inicie o laboratório no PC com conexão do M5 pela rede permitida.
2. Configure no M5 uma rede de 2,4 GHz do mesmo roteador do PC. O PC pode usar
   cabo Ethernet. Confirme uma leitura nova no MySQL antes da captura.
3. No modo Wi-Fi, USB só inicia o registro. Aguarde `CAPTURE_READY`, que confirma
   a chegada das amostras ao banco; remova o cabo, coloque o M5 no pulso e fique
   parado por cinco segundos. Anote o contador depois dessa preparação.
4. Conte passos manualmente e depois pare. Registre também repouso e movimentos
   do braço sem caminhar em capturas separadas, com contagem manual zero.

```powershell
python laboratorio/tools/capture_steps.py --port COM3 --wifi --seconds 580
```

O diagnóstico habilitado por `TRACE_MQTT ON` transmite lotes de até cinco leituras
no tópico autenticado normal, aproximadamente a cada 100 ms. Ele expira em 600
segundos na 2.1.4 (120 segundos nas versões anteriores). A ferramenta rejeita uma
duração maior que a suportada pelo firmware. Os payloads continuam identificados como `source=device`, com uma
coluna `imu_trace` adicional no JSON; o histórico anterior é preservado.

Para cabo sem limitação de movimento, omita `--wifi`; esse modo usa `TRACE_IMU ON`.
`TRACE_IMU OFF` encerra ambos os modos. A captura salva `imu.csv` e `summary.json`
em `runtime/calibracao`, incluindo intervalos de amostragem, perdas, pausas,
contagem manual e decisões do detector. Abrir USB pode reiniciar a placa; nunca
use o total de outra sessão como valor inicial. O programa espera a reconexão.
No Wi-Fi, também salva `packets.jsonl` com os identificadores de sessão e boot.
Uma mudança de sessão invalida a comparação do total, mesmo se o contador não
diminuir. Para um teste que inclui colocar/retirar o relógio, compare trechos
identificados e os valores anotados; o total do arquivo inclui esses movimentos.
`--expected-steps` só se aplica quando toda a captura corresponde ao teste manual.
Com `--stop-file CAMINHO`, criar esse arquivo finaliza e salva a captura do PC.
Isso não envia um comando ao M5; sem USB, o diagnóstico da placa termina pelo
limite automático de dez minutos.

No CSV, a ordem é: ms, ax/ay/az em g, gx/gy/gz em graus/s, aceleração filtrada
em g, cadência em ms, picos pendentes, evento, passos e sessão ativa (0/1).
No MQTT (`imu_trace_schema=2`), aceleração/filtro são inteiros em 0,0001 g,
giroscópio em 0,01 graus/s; a ferramenta converte essas unidades ao salvar o CSV.

Eventos: 0 amostra, 1 primeiro pico, 2 pico próximo demais, 3 reinício após
intervalo longo, 4 reinício por cadência, 5 candidato, 6 confirmação (inclui os
quatro picos), 7 passo adicional, 8 amostra inválida, 9 início/lacuna de amostras,
10 pico antecipado em relação à cadência confirmada (ignorado),
11 rotação rápida ou espera de recuperação após artefato de movimento.
O reprocessador `firmware/tests/step_counter_replay.cpp` permite experimentar o
detector sobre as mesmas leituras, sem repetir a caminhada para cada ajuste.
Verifique as perdas de amostras antes de usar uma captura para calibrar.

O plano de calibração é avaliar picos completos e sua amplitude, adaptar a
sensibilidade ao sinal medido e estudar aceleração por eixo junto com giroscópio.
Valide os ajustes em outra caminhada e em gestos sem passos. A
[referência da Analog Devices](https://www.analog.com/en/resources/analog-dialogue/articles/pedometer-design-3-axis-digital-acceler.html)
descreve detecção por eixo e limiar dinâmico; ela não calibra este M5 no pulso.

Referências de hardware: [M5StickC Plus2](https://docs.m5stack.com/en/core/M5StickC%20PLUS2)
e [exemplo BLE da Espressif](https://github.com/espressif/arduino-esp32/tree/2.0.17/libraries/BLE/examples/BLE_notify).
