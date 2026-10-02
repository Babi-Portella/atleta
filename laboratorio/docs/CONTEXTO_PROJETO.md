# Contexto do projeto de monitoramento de atleta

## Decisões confirmadas

- Placa: [M5StickC Plus2 com pulseira](https://shop.m5stack.com/products/m5stickc-plus2-with-watch-accessories), confirmada pelo usuário.
- O servidor EMQX ficará em outro computador da rede local. O IP será informado depois.
- Em 09/09/2026 o usuário disponibilizou este PC com Docker e o M5 por USB.
  Firmware 2.0.0 instalado e transmissão real M5 → Wi-Fi → EMQX → MySQL confirmada
  aqui. Isso não valida a instalação em outro computador do laboratório.
- O objetivo imediato é o laboratório descrito no [README](../README.md).
- O projeto ampliado deseja BPM, passos, distância, calorias, Wi-Fi, Bluetooth,
  bateria, temperatura da pele e GPS. Cardio significa BPM; ECG não foi solicitado.

## Foto recebida em 09/09/2026

A foto `WhatsApp Image 2026-09-09 at 00.02.10.jpeg` mostrou o dispositivo M5,
um módulo circular marcado HW-827, uma peça branca com placa perfurada, fios
e uma barra de três pinos. O link posterior confirmou a versão Plus2.

O HW-827 tem aparência de sensor óptico de pulso. Sua pinagem, alimentação e
qualidade da leitura ainda precisam ser confirmadas; ele não foi usado no firmware
do primeiro laboratório. A peça branca parece um HAT de prototipagem, sem modelo
confirmado. Não foi identificado GPS ou termômetro externo na foto.

## Recursos implementados e expansões pendentes

| Recurso | Caminho possível | Situação |
| --- | --- | --- |
| BPM | Avaliar HW-827 e processar o sinal óptico. | Hardware e qualidade em movimento pendentes. |
| Passos | Detector experimental com MPU6886 interno. | Implementado e autotestado; precisão física ainda não calibrada. |
| Distância | Passos × comprimento de um passo informado. | Implementada como estimativa; perfil não preenchido, resultado indisponível. |
| Calorias | MET × peso × horas ativas. | Implementada como estimativa; peso e MET não preenchidos, resultado indisponível. |
| Temperatura da pele | Sensor externo e montagem térmica adequada. | Sensor e posição pendentes. |
| GPS | Módulo GNSS externo. | Módulo e ligação não identificados; coordenadas indisponíveis. |
| Bluetooth | Serviço BLE com passos, duração e bateria. | Ligar/desligar confirmado na placa; cliente remoto ainda não testado. |
| Bateria | Tensão e percentual estimado pela M5Unified. | Leitura física confirmada; autonomia não medida. |

Temperatura interna da eletrônica não substitui medição da pele. Sensores
indisponíveis não devem gerar zeros que aparentem uma leitura válida.
O inventário da placa confirmou MPU6886 e resposta do RTC. A consulta ao Grove
SDA32/SCL33 não encontrou endereços I²C externos; ela não identifica componentes
analógicos nem módulos conectados em outros pinos. Veja [o guia do firmware](FIRMWARE_M5.md).

## API existente

O `main.py` da raiz usa FastAPI e SQLAlchemy, recebe medições por HTTP e cadastra
atletas. Seu esquema inclui BPM, sessão, duração, passos, distância, calorias,
ritmo, aceleração, localização e estados GPS/Wi-Fi.

Esse arquivo não foi alterado. O laboratório usa o banco `athlete_lab` e a tabela
`telemetry`, sem exigir cadastro de atleta ou migração da API. Uma integração
futura deverá mapear os campos e tratar leituras indisponíveis.
