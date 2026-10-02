"""Gera SVGs editáveis a partir do circuito confirmado e da arquitetura do projeto."""
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site/assets"


class Drawing:
    def __init__(self, width, height, dark=False, title=""):
        self.ink = "#eff7fb" if dark else "#061a2f"
        self.muted = "#b0c6d4" if dark else "#4b6070"
        self.line = "#688494" if dark else "#657d8c"
        self.panel = "#102a40" if dark else "#f3f7f9"
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
                      f'<title id="title">{escape(title)}</title><desc id="desc">Diagrama do projeto ATLETA, primeira entrega N1, atualizado em outubro de 2026.</desc>',
                      '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8" fill="#21a5b0"/></marker></defs>',
                      f'<rect width="{width}" height="{height}" fill="{"#061a2f" if dark else "#ffffff"}"/>']

    def text(self, x, y, content, size=18, fill=None, weight=400, anchor="start"):
        self.parts.append(f'<text x="{x}" y="{y}" fill="{fill or self.ink}" font-family="Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{escape(content)}</text>')

    def rect(self, x, y, width, height, fill=None, stroke=None, dashed=False, radius=8):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{fill or self.panel}" stroke="{stroke or self.line}" stroke-width="1.5" {"stroke-dasharray=\"7 6\"" if dashed else ""}/>')

    def path(self, d, arrow=False, dashed=False, color=None, width=2.5):
        self.parts.append(f'<path d="{d}" fill="none" stroke="{color or self.line}" stroke-width="{width}" {"marker-end=\"url(#arrow)\"" if arrow else ""} {"stroke-dasharray=\"7 6\"" if dashed else ""}/>')

    def box(self, x, y, w, h, title, lines=(), dashed=False, color=None):
        self.rect(x, y, w, h, stroke=color, dashed=dashed)
        self.text(x+20, y+32, title, 21, weight=650)
        for i, line in enumerate(lines):
            self.text(x+20, y+61+i*24, line, 17, self.muted)

    def ground(self, x, y):
        self.path(f'M{x} {y} v10 M{x-14} {y+10} h28 M{x-9} {y+16} h18 M{x-4} {y+22} h8', width=2)

    def resistor(self, x, y, horizontal=False):
        if horizontal:
            self.path(f'M{x} {y} h12 l5 -7 l10 14 l10 -14 l10 14 l10 -14 l5 7 h12', width=2)
        else:
            self.path(f'M{x} {y} v12 l-7 5 l14 10 l-14 10 l14 10 l-14 10 l7 5 v12', width=2)

    def save(self, name):
        (OUT / name).write_text("\n".join(self.parts)+"\n</svg>\n", encoding="utf-8")


def architecture():
    s = Drawing(1440, 940, True, "ATLETA — arquitetura completa da primeira versão")
    s.text(50, 57, "ATLETA / ARQUITETURA DO PROJETO", 30, weight=700)
    s.text(50, 91, "Sensores → firmware → MQTT → EMQX → MySQL → painel", 20, s.muted)
    s.rect(50, 130, 350, 585, fill="#0a2237", stroke="#2c4b60")
    s.rect(440, 130, 300, 585, fill="#0a2237", stroke="#2c4b60")
    s.rect(780, 130, 610, 585, fill="#0a2237", stroke="#2c4b60")
    for x, a, b in [(70,"01 / DISPOSITIVO","M5StickC Plus2"),(460,"02 / COMUNICAÇÃO","Rede do laboratório"),(800,"03 / PLATAFORMA PRÓPRIA","Docker no computador servidor")]:
        s.text(x, 159, a, 16, "#c4f545", 700)
        s.text(x, 186, b, 17, s.muted)
    s.box(70, 212, 310, 94, "MPU6886 interno", ["Aceleração + rotação / 50 Hz"], color="#21a5b0")
    s.box(70, 339, 310, 125, "Firmware 2.1.7", ["Arduino C++ / sessão / passos", "JSON com source=device"], color="#c4f545")
    s.box(70, 498, 310, 84, "Configuração em NVS", ["Wi-Fi / MQTT / perfil por USB"])
    s.box(70, 615, 310, 80, "Tela, botões e bateria", ["Operação local da sessão"])
    s.path('M225 306 V339', True, color="#21a5b0")
    s.path('M225 498 V464', True, color="#21a5b0")
    s.path('M90 464 V598 H225 V615', True, color="#21a5b0")
    s.box(460, 339, 260, 125, "Wi-Fi 2,4 GHz", ["MQTT 3.1.1 / TCP / QoS 0", "Publicação a cada 2 segundos"], color="#21a5b0")
    s.box(460, 503, 260, 155, "Tópico de telemetria", ["atletas/m5-atleta-01/", "telemetria", "Sem fila persistente offline"])
    s.text(460, 258, "Host e porta configuráveis", 18, s.muted)
    s.text(460, 285, "IP do servidor alcançável pelo M5", 16, s.muted)
    s.path('M380 400 H460', True, color="#21a5b0")
    s.box(800, 236, 265, 108, "Broker EMQX 6.1.1", ["Recebe e identifica o cliente", "MQTT 1883 no perfil servidor"], color="#21a5b0")
    s.box(1110, 236, 260, 108, "MySQL / acesso", ["mqtt_users: login bcrypt", "mqtt_acl: permissão por tópico"])
    s.path('M1065 284 H1110', True, color="#21a5b0")
    s.path('M1110 315 H1065', True, color="#21a5b0")
    s.path('M720 400 H755 V290 H800', True, color="#21a5b0")
    s.box(800, 402, 265, 108, "Regra + ação MySQL", ["Valida campos obrigatórios", "Conector mysql:3306"])
    s.box(1110, 402, 260, 108, "MySQL 8.4.8", ["athlete_lab.telemetry", "JSON + identidade + horário"], color="#c4f545")
    s.path('M932 344 V402', True, color="#21a5b0")
    s.path('M1065 456 H1110', True, color="#21a5b0")
    s.box(800, 573, 265, 100, "Dashboard EMQX", ["Administração do broker", "Porta 18083 no perfil servidor"])
    s.box(1110, 573, 260, 100, "Painel do atleta", ["Windows: leituras e histórico", "Consulta com lab_reader"])
    s.path('M1240 510 V573', True, color="#21a5b0")
    s.path('M800 300 H791 V551 H933 V573', True, color="#21a5b0", width=2)
    s.text(50, 765, "EXPANSÕES E OUTROS ARTEFATOS", 17, "#c4f545", 700)
    s.box(50, 791, 350, 101, "Sensores externos", ["BPM / pele / GNSS: pendentes", "Modelos e ligações a confirmar"], True)
    s.box(440, 791, 300, 101, "Bluetooth BLE", ["Resumo opcional no M5", "Cliente remoto ainda pendente"], True)
    s.box(780, 791, 290, 101, "API FastAPI original", ["Integração com a telemetria", "ainda não implementada"], True)
    s.box(1110, 791, 280, 101, "GitHub Pages", ["Apresentação estática", "Documentação e downloads"])
    s.path('M225 791 V745 H420 V360 H380', True, True, "#688494", 2)
    s.path('M380 430 H410 V735 H590 V791', True, True, "#688494", 2)
    s.path('M1370 470 H1380 V743 H925 V791', True, True, "#688494", 2)
    s.text(50, 925, "Contínuo: caminho implementado   /   Tracejado: expansão ou integração pendente   /   Portas de uma instalação nova em perfil server", 16, s.muted)
    s.save("diagrama-projeto-v1.svg")


def circuit():
    s = Drawing(1440, 1080, False, "ATLETA — esquema eletrônico simplificado do M5StickC Plus2")
    s.text(50, 57, "ATLETA / CIRCUITO ELETRÔNICO V1", 30, weight=700)
    s.text(50, 90, "M5StickC Plus2 · sinais usados pelo firmware · componentes já integrados à placa", 20, s.muted)
    s.rect(35, 117, 1370, 805, fill="#fff", stroke="#b6c8d2", dashed=True)
    s.text(55, 146, "LIMITE DA PLACA PRONTA", 15, s.muted, 650)
    s.box(60, 177, 290, 84, "USB-C / 5 V", ["Cabo de dados + alimentação"])
    s.box(60, 316, 290, 108, "Carga e regulação", ["Subsistema interno da placa", "Alimentação da lógica: 3,3 V"])
    s.path('M205 261 V316')
    s.text(220, 295, "VBUS", 16, s.muted)
    s.path('M350 370 H460 V210 H525')
    s.text(388, 202, "+3,3 V", 18, "#087581", 650)
    s.rect(525, 190, 340, 460, fill="#edf3f6", stroke="#061a2f")
    s.text(695, 237, "ESP32-PICO-V3-02", 25, weight=700, anchor="middle")
    s.text(695, 270, "M5StickC Plus2", 20, s.muted, anchor="middle")
    s.text(550, 320, "GPIO21 / SDA", 18)
    s.text(550, 370, "GPIO22 / SCL", 18)
    s.text(550, 430, "GPIO15, 13, 14, 12, 5, 27", 17)
    s.text(550, 480, "GPIO37 / botão A", 18)
    s.text(550, 530, "GPIO39 / botão B", 18)
    s.text(550, 580, "GPIO4 / HOLD = 1", 18)
    s.text(550, 623, "GPIO38 / leitura de bateria", 17)
    s.box(1120, 235, 250, 155, "U / MPU6886", ["Acelerômetro + giroscópio", "VCC 3,3 V / GND comum", "I²C interno"])
    s.path('M865 313 H1120', color="#087581")
    s.path('M865 363 H1120', color="#087581")
    s.text(1002, 302, "SDA", 16, "#087581")
    s.text(1020, 352, "SCL", 16, "#087581")
    s.path('M960 218 H1040 M960 218 V233 M1040 218 V233')
    s.text(1000, 203, "+3,3 V", 18, "#087581", 650, "middle")
    s.resistor(960, 233)
    s.resistor(1040, 233)
    s.path('M960 307 V313 M1040 307 V363')
    s.text(942, 272, "2k2", 15, s.muted, anchor="end")
    s.text(1090, 272, "2k2", 15, s.muted, anchor="middle")
    s.text(943, 410, "Pull-ups já presentes na placa", 16, s.muted)
    s.box(1085, 452, 285, 120, "Tela / ST7789V2", ["MOSI15 / CLK13 / DC14", "RST12 / CS5 / BL27"])
    s.path('M865 427 H1018 V488 H1085')
    s.text(897, 445, "SPI + controle", 16, s.muted)
    s.box(60, 623, 320, 103, "Ponte USB / CH9102F", ["USB D+ e D− → UART0", "ESP32 TX GPIO1 / RX GPIO3"])
    s.path('M60 219 H45 V676 H60')
    s.path('M380 673 H450 V690 H595 V650')
    s.text(463, 711, "Serial / 115200 baud", 16, s.muted)
    # Botões e resistores de pull-up pertencem ao circuito integrado à placa.
    s.path('M865 477 H1000 V760 H1090')
    s.path('M865 527 H970 V810 H1240 V760 H1310')
    for x, label in ((1070, "A / GPIO37"), (1290, "B / GPIO39")):
        y = 760
        s.text(x-70, y-7, label, 17, weight=650)
        s.resistor(x, y-118)
        s.path(f'M{x} {y-44} V{y} H{x+20} M{x} {y-118} V{y-130}')
        s.text(x+34, y-87, "10 kΩ", 16, s.muted)
        s.text(x, y-139, "+3,3 V", 16, "#087581", anchor="middle")
        s.path(f'M{x+20} {y} l32 -17 M{x+60} {y} H{x+90} V{y+20}')
        s.ground(x+90, y+20)
    s.path('M525 576 H425 V399 H350')
    s.text(439, 473, "HOLD", 16, s.muted)
    s.box(60, 464, 290, 111, "Bateria interna", ["Li-ion / 3,7 V / 200 mAh", "Medição pelo circuito interno"])
    s.path('M205 464 V424')
    # Símbolo elétrico da bateria, já integrada.
    s.path('M325 506 V498 M311 498 H339 M317 490 H333 M325 490 V477', width=2)
    s.ground(205, 575)
    s.ground(740, 730)
    s.path('M740 650 V730')
    s.text(761, 755, "GND comum", 16, s.muted)
    s.box(60, 799, 690, 94, "Grove HY2.0-4P / sem conexão nesta versão", ["Preto: GND  ·  Vermelho: 5 V  ·  Amarelo: GPIO32  ·  Branco: GPIO33"], True)
    s.text(800, 850, "Wi-Fi 2,4 GHz → servidor EMQX", 22, "#087581", 650)
    s.text(800, 880, "Transmissão sem ligação elétrica ao servidor", 17, s.muted)
    s.text(50, 962, "Sem sensores externos na V1. BPM, temperatura da pele e GNSS dependem de modelos e ligações confirmados.", 18, s.muted)
    s.text(50, 997, "Esquema simplificado: omite componentes não usados e detalhes de carga/regulação. Não substitui o esquema completo.", 17, s.muted)
    s.text(50, 1032, "Fonte: M5Stack / StickC-Plus2 / esquema oficial v0.5 e PinMap, consultados em 28/09/2026. Lógica do ESP32: 3,3 V.", 17, s.muted)
    s.save("circuito-v1.svg")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    architecture()
    circuit()
    print("Diagramas SVG gerados.")
