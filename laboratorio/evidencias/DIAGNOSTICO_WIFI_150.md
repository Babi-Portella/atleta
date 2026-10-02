# Rede automática e diagnóstico do M5 — 12/09/2026

**Sintoma informado:** no outro computador, a configuração não mostrou erro,
mas os dados não chegaram ao vivo. Não foram fornecidos o status USB/Wi-Fi/MQTT
nem logs daquela máquina. A causa da falha remota continua não confirmada.

**Constatação no código 1.4.0:** a tela carregava somente o SSID salvo na cópia
do projeto. Não consultava a rede atual do Windows. O envio encerrava ao receber
CONFIG_OK, que confirma gravação na placa antes de ela reiniciar e tentar Wi-Fi.
Isso não comprovava a conexão nem a chegada de dados ao MySQL.

**Implementação solicitada, versão 1.5.0:** consulta da conexão Wi-Fi ativa via
Windows.Networking.Connectivity; preenchimento automático do SSID; senha do
projeto reutilizada somente para SSID idêntico; preenchimento manual preservado
para cabo, consulta negada e múltiplas redes. Respostas assíncronas não substituem
campos que o usuário já editou.

Antes do envio, o IP atual é conferido nas portas da instalação e gravado na
configuração. Após o envio, STATUS/INVENTORY e amostras USB são observados e
comparados com as leituras MySQL. Uma amostra só comprova envio atual quando
o boot_id e sample_seq coincidem e o registro tem até 10 segundos de idade.
O diagnóstico diferencia falha Wi-Fi, recusa MQTT, servidor inacessível e
ausência de persistência; IP/firewall não são alterados sem evidência de falha.

**Evidência:** testes-painel-150.log contém 58 testes OK. A janela Tk foi
verificada com rede e USB simulados em validacao-configuracao-m5-gui.json.
A consulta real ao Windows deste PC retornou nenhuma conexão Wi-Fi ativa;
nenhuma porta USB M5 estava presente. A identificação de SSID com Wi-Fi ativo
e o envio físico precisam ser confirmados no computador de destino.

**Regressão:** painel/test_wifi_auto.py cobre senha de outra rede, SSID com
acentos, rede desconectada, múltiplas redes, falha na consulta Windows, troca
de IP, configuração sem acesso de rede e rejeição de histórico antigo como
sucesso ao vivo. O teste de GUI cobre a preservação de edição manual durante
a consulta automática. O firmware e os dados existentes não foram alterados.

**Status: DONE_WITH_CONCERNS.** Automação implementada e testada localmente;
causa da ausência de dados no outro PC ainda exige o novo diagnóstico.

Referência de API:
[GetConnectedSsid](https://learn.microsoft.com/en-us/uwp/api/windows.networking.connectivity.wlanconnectionprofiledetails.getconnectedssid).
