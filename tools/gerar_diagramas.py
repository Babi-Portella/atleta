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
    W, H = 1800, 1420
    BG, PANEL, INK, MUTED = "#061a2f", "#102a40", "#eff7fb", "#b0c6d4"
    TEAL, LIME, VIOLET, BORDER = "#21a5b0", "#c4f545", "#bca1f5", "#36586c"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
             '<title id="title">ATLETA — arquitetura revisada para a N1</title>',
             '<desc id="desc">M5 e roteador conectados à plataforma local. EMQX e um único MySQL ficam no Docker; painel e configuração USB ficam no Windows. GitHub Pages e expansões aparecem em áreas próprias.</desc>',
             '<defs>']
    for name, color in (("data", TEAL), ("control", VIOLET)):
        parts.append(f'<marker id="{name}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8" fill="{color}"/></marker>')
    parts += ['</defs>', f'<rect width="{W}" height="{H}" fill="{BG}"/>']


    def text(x, y, value, size=18, color=INK, weight=400, anchor="start"):
        parts.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>')


    def rect(x, y, w, h, fill=PANEL, stroke=BORDER, dashed=False, radius=10):
        dash = ' stroke-dasharray="7 6"' if dashed else ""
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{dash}/>')


    def box(x, y, w, h, title, lines=(), color=BORDER, size=21, line_size=17, dashed=False):
        rect(x, y, w, h, stroke=color, dashed=dashed)
        text(x+18, y+32, title, size, weight=650)
        for i, value in enumerate(lines):
            text(x+18, y+61+i*24, value, line_size, MUTED)


    def path(d, control=False, both=False):
        kind, color = ("control", VIOLET) if control else ("data", TEAL)
        start = f' marker-start="url(#{kind})"' if both else ""
        parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" marker-end="url(#{kind})"{start}/>')


    def section(x, y, label, title):
        text(x, y, label, 16, LIME, 700)
        text(x, y+29, title, 23, weight=650)


    # Título e limites físicos de execução.
    text(40, 58, "ATLETA / ARQUITETURA DO PROJETO", 32, weight=700)
    text(40, 95, "Do movimento no pulso à leitura no computador — componentes e conexões da primeira versão", 21, MUTED)
    rect(1470, 32, 290, 43, fill="#183322", stroke=LIME)
    text(1615, 60, "ARQUITETURA REVISADA / N1", 17, LIME, 650, "middle")
    for x, width in ((40, 440), (510, 250), (790, 970)):
        rect(x, 140, width, 800, fill="#0a2237", stroke=BORDER)
    section(62, 174, "01 / DISPOSITIVO", "M5StickC Plus2")
    section(530, 174, "02 / REDE LOCAL", "Roteador / LAN")
    section(812, 174, "03 / PLATAFORMA PRÓPRIA", "Computador Windows / servidor local")

    # Entradas, processamento e saída local do M5.
    box(62, 250, 196, 112, "MPU6886", ["Aceleração + rotação", "Leitura a 50 Hz"], TEAL, size=21, line_size=16)
    box(278, 250, 180, 112, "Botões + bateria", ["Comandos da sessão", "Leitura da bateria"], size=18, line_size=15)
    box(62, 420, 396, 130, "Firmware Arduino C++ / 2.1.7", ["Detector de passos + sessão", "Telemetria JSON / source=device", "Wi-Fi e MQTT configuráveis"], LIME)
    path("M160 362 V420")
    path("M368 362 V420")
    text(160, 394, "I²C", 16, TEAL, anchor="middle")
    text(368, 394, "GPIO / ADC", 15, TEAL, anchor="middle")
    box(62, 630, 196, 112, "Configuração NVS", ["Wi-Fi / MQTT / perfil", "Persistência na placa"], size=18, line_size=16)
    box(278, 630, 180, 112, "Tela LCD", ["Passos e sessão", "Dados dos sensores"], size=21, line_size=16)
    path("M160 630 V550", control=True)
    path("M368 550 V630")
    text(160, 599, "Configuração", 15, VIOLET, anchor="middle")
    text(368, 599, "SPI / controle", 15, TEAL, anchor="middle")
    box(62, 820, 396, 92, "USB-C / UART0", ["Configuração → NVS  •  Gravação → ESP32"], VIOLET, line_size=16)
    path("M160 820 V742", control=True)
    path("M62 866 H51 V515 H62", control=True)

    # MQTT atravessa a rede; o roteador não é um broker.
    text(635, 291, "M5 pelo Wi-Fi 2,4 GHz", 17, MUTED, anchor="middle")
    text(635, 318, "PC pela rede Ethernet", 17, MUTED, anchor="middle")
    text(635, 359, "MQTT 3.1.1 / TCP", 18, TEAL, 650, "middle")
    text(635, 385, "1883 no perfil servidor", 16, MUTED, anchor="middle")
    box(530, 420, 210, 130, "Roteador / AP", ["Conecta M5 e servidor", "Wi-Fi + rede cabeada", "Encaminha o tráfego"], TEAL, size=21, line_size=16)
    path("M458 484 H530")
    path("M740 484 H845")
    text(494, 470, "Wi-Fi", 14, TEAL, anchor="middle")
    text(792, 470, "LAN", 14, TEAL, anchor="middle")
    rect(530, 592, 210, 179)
    text(548, 623, "TÓPICO MQTT", 15, LIME, 650)
    text(548, 653, "atletas/m5-atleta-01/", 15, MUTED)
    text(548, 676, "telemetria", 15, MUTED)
    text(548, 712, "JSON a cada 2 segundos", 16, INK)
    text(548, 742, "QoS 0 / sem fila offline", 15, MUTED)

    # Só os dois serviços do compose são containers Docker.
    rect(810, 238, 650, 472, fill="#082032", stroke=TEAL)
    text(830, 265, "DOCKER / DOIS CONTAINERS", 16, TEAL, 700)
    rect(830, 300, 260, 380, fill="#0c2438", stroke=BORDER)
    rect(1220, 300, 220, 380, fill="#0c2438", stroke=BORDER)
    text(848, 329, "CONTAINER EMQX", 16, MUTED, 650)
    text(1238, 329, "MYSQL 8.4.8", 18, MUTED, 650)
    rect(845, 354, 228, 49, stroke=VIOLET)
    text(959, 385, "Dashboard / HTTP 18083", 17, INK, 500, "middle")
    box(845, 420, 228, 130, "EMQX 6.1.1", ["Broker MQTT", "Cliente autenticado", "Permissões por tópico"], TEAL, line_size=16)
    box(845, 589, 228, 73, "Regra + ação SQL", ["Valida e grava a telemetria"], size=20, line_size=15)
    path("M959 550 V589")

    # Um único banco contém as três tabelas; a forma de cilindro evita duplicidade.
    parts.append('<path d="M1236 408 C1236 376 1424 376 1424 408 V630 C1424 662 1236 662 1236 630 Z" fill="#163747" stroke="#c4f545" stroke-width="1.5"/>')
    parts.append('<ellipse cx="1330" cy="408" rx="94" ry="23" fill="#214957" stroke="#c4f545" stroke-width="1.5"/>')
    text(1330, 414, "athlete_lab", 20, INK, 650, "middle")
    text(1330, 471, "mqtt_users", 18, INK, 650, "middle")
    text(1330, 496, "Login / bcrypt", 15, MUTED, anchor="middle")
    text(1330, 533, "mqtt_acl", 18, INK, 650, "middle")
    text(1330, 558, "Permissões / tópicos", 15, MUTED, anchor="middle")
    text(1330, 594, "telemetry", 18, LIME, 650, "middle")
    text(1330, 619, "JSON + identidade", 15, MUTED, anchor="middle")
    text(1330, 642, "Hora da recepção", 15, MUTED, anchor="middle")
    path("M1073 489 H1236", both=True)
    text(1154, 464, "Login / ACL", 16, TEAL, anchor="middle")
    text(1154, 517, "SQL / 3306", 15, MUTED, anchor="middle")
    path("M1073 626 H1236")
    text(1154, 601, "INSERT telemetry", 15, TEAL, anchor="middle")
    text(830, 701, "MySQL acessível pelo nome mysql:3306 entre os containers", 16, MUTED)

    # Programas nativos: leitura SQL, administração HTTP e configuração USB.
    text(1490, 265, "PROGRAMAS NO WINDOWS", 16, LIME, 700)
    box(1490, 300, 250, 90, "Navegador", ["Administração do EMQX", "Dashboard / HTTP 18083"], VIOLET, line_size=16)
    path("M1490 349 H1475 V280 H816 V378 H845", control=True, both=True)
    box(1490, 420, 250, 130, "Painel do atleta", ["Programa Windows", "Leituras e histórico", "Consulta com lab_reader"], LIME, line_size=16)
    path("M1330 653 V752 H1615 V550", both=True)
    text(1480, 786, "SQL local / 127.0.0.1:33070 / lab_reader", 16, TEAL, anchor="middle")
    box(1490, 820, 250, 92, "Configurar / gravar M5", ["Programa Windows / USB", "Wi-Fi, MQTT e firmware"], VIOLET, size=19, line_size=16)
    path("M1490 866 H458", control=True, both=True)
    text(970, 847, "USB / serial — configuração e gravação", 17, VIOLET, anchor="middle")

    # Material público é uma entrega separada da plataforma de telemetria.
    text(40, 984, "04 / APRESENTAÇÃO PÚBLICA", 16, LIME, 700)
    box(40, 1017, 430, 111, "Repositório GitHub", ["Fontes, documentação e diagramas", "Projeto da equipe"], line_size=18)
    box(610, 1017, 520, 111, "GitHub Pages", ["Home • Plataforma • Dispositivos • Aplicativo", "Apresentação estática e downloads"], TEAL, line_size=18)
    box(1280, 1017, 480, 111, "Equipe / visitante", ["Consulta a página do projeto", "Baixa código, diagramas e materiais"], line_size=18)
    path("M470 1075 H610")
    path("M1130 1075 H1280", both=True)
    text(540, 1055, "Publicação", 16, TEAL, anchor="middle")
    text(1205, 1055, "HTTPS", 16, TEAL, anchor="middle")
    text(40, 1162, "A GitPage apresenta o projeto; as leituras do M5 ficam na plataforma local.", 19, MUTED)

    # Planejamento, sem sugerir que os recursos já recebem telemetria.
    text(40, 1210, "05 / EXPANSÕES E INTEGRAÇÕES PENDENTES", 16, MUTED, 700)
    box(40, 1240, 405, 110, "Sensores externos", ["BPM / SpO₂ / pele / GNSS", "Modelos e ligações a definir"], dashed=True)
    box(478, 1240, 406, 110, "Cliente BLE", ["Resumo opcional já existe no M5", "Aplicativo remoto pendente"], dashed=True)
    box(917, 1240, 405, 110, "Integração FastAPI", ["Código original disponível", "Ligação à telemetria pendente"], dashed=True)
    box(1355, 1240, 405, 110, "Aplicativo móvel", ["Interface e integração", "Etapa futura do sistema"], dashed=True)
    parts.append(f'<path d="M40 1390 H82" stroke="{TEAL}" stroke-width="3"/>')
    text(95, 1396, "Dados implementados", 16, MUTED)
    parts.append(f'<path d="M335 1390 H377" stroke="{VIOLET}" stroke-width="3"/>')
    text(390, 1396, "Configuração / administração", 16, MUTED)
    text(760, 1396, "Tracejado: etapa futura • Portas indicadas: perfil servidor novo • Firmware atual: 2.1.7", 16, MUTED)
    parts.append('</svg>')

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "diagrama-projeto-v1.svg").write_text("\n".join(parts)+"\n", encoding="utf-8")


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
