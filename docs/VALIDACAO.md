# Validação da primeira entrega N1

Atualização: **02/10/2026**. Firmware atual: **2.1.7**; painel Windows: **1.5.0**.

## Caminho físico implementado

O M5StickC Plus2 publica pelo Wi-Fi no EMQX, que persiste as mensagens no MySQL
pela regra e ação da plataforma própria. O painel Windows consulta as leituras.
A GitPage apresenta os componentes e os downloads; ela não consulta o banco.

- O relatório de revisão de 02/10/2026 comparou seis mensagens do M5 com o JSON
  salvo no MySQL e registrou 58 testes do painel aprovados. Esse relatório foi
  feito antes da atualização do firmware e identifica a versão 2.1.3.
- Após gravar 2.1.7, STATUS confirmou Wi-Fi, MQTT e IMU ativos; SELFTEST aprovou
  os casos sintéticos. O hash da imagem gravada corresponde aos fontes atuais.
- A captura física 2.1.7 recebeu **12.113 amostras** pelo MQTT/MySQL, sem mudança
  de sessão, linhas malformadas ou amostras pausadas. Houve cinco lacunas acima
  de 60 ms, todas depois do último incremento de passos.
- No ensaio de vinte passos no espaço pequeno, foram registrados **dezessete**.
  Colocar e manusear o relógio acrescentou **zero** passos nesse ensaio.

Evidências: [contador 2.1.7](../laboratorio/evidencias/contador-passos-2.1.7.json)
e [revisão anterior à atualização](../laboratorio/evidencias/revisao-2026-10-02.json).
Para a publicação, as imagens 2.1.7 foram recompiladas em uma pasta neutra,
com os mesmos fontes e configuração, para remover caminhos locais. A imagem
recompilada não foi regravada ou retestada no M5; por isso, seu manifesto indica
`physical_device_tested: false`. O hash da imagem utilizada no ensaio físico
permanece no relatório separado acima. Esses testes não estabelecem precisão
geral do contador.

## Artefatos da N1

- Home, Plataforma, Dispositivos e Aplicativo no menu da GitPage.
- Código Arduino C++, PlatformIO, imagens e hashes da versão 2.1.7.
- EMQX 6.1.1 e MySQL 8.4.8 próprios, com autenticação e autorização por tópico.
- Diagrama do caminho implementado e das expansões futuras.
- Banner escolhido pela equipe, com a indicação de conteúdo conceitual na página.
- Esquema simplificado do circuito integrado ao M5 e sua pinagem.
- Interface Windows implementada e identificada na seção Aplicativo.

## Limites

MQTT usa QoS 0 e TCP sem TLS no laboratório. Não há fila persistente de amostras
offline. Passos são experimentais; distância e calorias dependem do perfil.
BPM, SpO₂, temperatura corporal, GPS e aplicativo móvel do banner são expansões
futuras. BLE tem serviço na placa, mas o cliente remoto ainda precisa de validação.
A integração da API FastAPI original à telemetria também é futura.
O circuito simplifica a placa pronta e não substitui o esquema do fabricante.

## Publicação e equipe

Repositório: https://github.com/Babi-Portella/atleta.
A publicação é feita pelo GitHub Pages. Verifique a implantação concluída e
abra a URL informada em Settings → Pages para confirmar o site online.
Integrantes confirmados: Babi-Portella, Emilio467 e jvBaracho.

A referência visual do enunciado ainda não foi fornecida. Os quatro nomes de
menu solicitados foram aplicados; a correspondência visual exata requer essa imagem.
