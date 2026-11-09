"""Janela do recomendador de peças de PC (visual Fluent / Windows 11). Execute: python app.py

O usuário escolhe só a peça e a finalidade; o hardware é lido automaticamente ao abrir.
"""
import json
import platform
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, FluentIcon, FluentWindow, IconWidget,
    IndeterminateProgressRing, InfoBar, InfoBarIcon, InfoBarPosition, MessageBox,
    PrimaryPushButton, SimpleCardWidget, SmoothScrollArea, StrongBodyLabel,
    Theme, TitleLabel, setCustomStyleSheet, setTheme, setThemeColor,
)

from recomendador import CATALOGO_PADRAO, USOS, carregar_catalogo
from scanner import FalhaLeitura, escanear, interpretar, ler_hardware_bruto
from upgrade import PECAS, recomendar_peca

# Identidade visual Blasync Technology (cores medidas no banner e no logo oficiais)
COR_FUNDO = "#07001F"      # azul-marinho quase preto
COR_CARTAO = "#120A2E"
COR_BORDA = "#2B1766"
COR_ROXO = "#8000F8"       # roxo neon: cor principal (botões, seleção)
COR_DOURADO = "#FBDD00"    # dourado do triângulo do logo: destaques
COR_AVISO = "#2A2108"      # fundo dos avisos, dourado escurecido
NOME_MARCA = "Blasync Technology"
SLOGAN = ("Conectando tecnologias, ", "impulsionando o amanhã")

ASSETS = Path(__file__).parent / "assets"

ICONES_PECAS = {
    "memoria": FluentIcon.IOT,
    "armazenamento": FluentIcon.SAVE,
    "processador": FluentIcon.DEVELOPER_TOOLS,
    "video": FluentIcon.VIDEO,
    "placa_mae": FluentIcon.TILES,
    "fonte": FluentIcon.POWER_BUTTON,
}


def descrever_computador(hw):
    nome = " ".join(filter(None, [hw["fabricante"], hw["modelo"]])) or "Computador"
    return f"{nome} ({hw['tipo']})"


def limpar_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            # Esconde já; o deleteLater só remove no próximo ciclo da janela.
            item.widget().hide()
            item.widget().deleteLater()


def rotulo(texto, classe=BodyLabel):
    label = classe(texto)
    label.setWordWrap(True)
    return label


def icone_dourado(icone):
    return icone.colored(QColor(COR_DOURADO), QColor(COR_DOURADO))


class CartaoMarca(SimpleCardWidget):
    """Cartão no padrão Blasync: fundo marinho e borda roxa discreta."""

    def _normalBackgroundColor(self):
        return QColor(COR_CARTAO)

    def paintEvent(self, e):
        pintor = QPainter(self)
        pintor.setRenderHints(QPainter.Antialiasing)
        pintor.setBrush(self.backgroundColor)
        pintor.setPen(QColor(COR_BORDA))
        r = self.borderRadius
        pintor.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), r, r)


class FaixaMarca(QWidget):
    """Banner da Blasync no topo, acompanhando a largura da janela."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.imagem = QPixmap(str(ASSETS / "faixa_blasync.jpg"))
        self.proporcao = self.imagem.height() / self.imagem.width() if not self.imagem.isNull() else 0
        self.setFixedHeight(140)
        if self.imagem.isNull():
            self.hide()  # sem o arquivo da marca, a janela segue funcionando sem a faixa

    def resizeEvent(self, e):
        self.setFixedHeight(max(110, min(200, int(self.width() * self.proporcao))))
        super().resizeEvent(e)

    def paintEvent(self, e):
        pintor = QPainter(self)
        pintor.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        contorno = QPainterPath()
        contorno.addRoundedRect(self.rect(), 10, 10)
        pintor.setClipPath(contorno)
        # Preenche a largura e corta o excesso de altura pelo centro (modo "cover")
        escalada = self.imagem.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (escalada.width() - self.width()) // 2
        y = (escalada.height() - self.height()) // 2
        pintor.drawPixmap(0, 0, escalada, x, y, self.width(), self.height())


def rodape_marca(com_slogan=True):
    texto = f"<span style='color:#B9B3D6'>{NOME_MARCA}</span>"
    if com_slogan:  # a página com o banner já mostra o slogan
        texto = (f"<span style='color:#B9B3D6'>{SLOGAN[0]}</span>"
                 f"<span style='color:{COR_DOURADO}'>{SLOGAN[1]}</span>"
                 f"<span style='color:#B9B3D6'> · {NOME_MARCA}</span>")
    label = CaptionLabel(texto)
    label.setTextFormat(Qt.RichText)
    label.setAlignment(Qt.AlignCenter)
    return label


class Cartao(CartaoMarca):
    """Cartão com ícone + título e uma linha por item."""

    def __init__(self, icone, titulo, linhas, icone_linha=None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        cabecalho = QHBoxLayout()
        icone_w = IconWidget(icone)
        icone_w.setFixedSize(18, 18)
        cabecalho.addWidget(icone_w)
        cabecalho.addWidget(rotulo(titulo, StrongBodyLabel), 1)
        cabecalho.addStretch()
        layout.addLayout(cabecalho)

        for texto in linhas:
            linha = QHBoxLayout()
            linha.setSpacing(10)
            if icone_linha:
                marcador = IconWidget(icone_linha)
                marcador.setFixedSize(14, 14)
                linha.addWidget(marcador, 0, Qt.AlignTop)
            else:
                linha.addSpacing(4)
            texto_linha = rotulo(texto)
            # Selecionável para copiar referências e termos de busca
            texto_linha.setTextInteractionFlags(Qt.TextSelectableByMouse)
            linha.addWidget(texto_linha, 1)
            layout.addLayout(linha)


class Pagina(SmoothScrollArea):
    """Página rolável com título; o conteúdo vai em `self.corpo`."""

    def __init__(self, nome_objeto, titulo, parent=None, com_faixa=False):
        super().__init__(parent)
        self.setObjectName(nome_objeto)  # o FluentWindow exige objectName nas páginas
        self.setWidgetResizable(True)
        # Sem rolagem lateral: o conteúdo acompanha a largura da janela e o texto quebra linha.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        conteudo = QWidget()
        conteudo.setStyleSheet("background: transparent;")
        self.corpo = QVBoxLayout(conteudo)
        self.corpo.setContentsMargins(36, 28, 36, 20)
        self.corpo.setSpacing(14)
        self.com_faixa = com_faixa
        if com_faixa:
            self.corpo.addWidget(FaixaMarca())
        self.corpo.addWidget(rotulo(titulo, TitleLabel))
        self.setWidget(conteudo)

    def finalizar(self):
        """Empurra o conteúdo para o topo e fecha a página com o slogan da marca."""
        self.corpo.addStretch(1)
        self.corpo.addSpacing(12)
        self.corpo.addWidget(rodape_marca(com_slogan=not self.com_faixa))


class LeitorHardware(QThread):
    """Lê o hardware fora da thread da interface (o PowerShell leva alguns segundos)."""
    concluido = Signal(object, str)

    def run(self):
        try:
            self.concluido.emit(escanear(), "")
        except FalhaLeitura as erro:
            self.concluido.emit(None, str(erro))
        except Exception as erro:  # qualquer falha inesperada vira mensagem na tela
            self.concluido.emit(None, f"Erro inesperado: {erro!r}")


class PaginaRecomendar(Pagina):
    def __init__(self, categorias, parent=None):
        super().__init__("paginaRecomendar", "Qual peça comprar?", parent, com_faixa=True)
        self.categorias = categorias
        self.hw = None

        # Cartão do computador detectado
        cartao_pc = CartaoMarca()
        linha_pc = QHBoxLayout(cartao_pc)
        linha_pc.setContentsMargins(20, 16, 20, 16)
        linha_pc.setSpacing(14)
        self.anel = IndeterminateProgressRing()
        self.anel.setFixedSize(28, 28)
        self.icone_pc = IconWidget(icone_dourado(FluentIcon.IOT))
        self.icone_pc.setFixedSize(28, 28)
        self.icone_pc.hide()
        linha_pc.addWidget(self.anel)
        linha_pc.addWidget(self.icone_pc)
        textos_pc = QVBoxLayout()
        textos_pc.setSpacing(2)
        self.lbl_pc = rotulo("Lendo as peças deste computador...", StrongBodyLabel)
        self.lbl_origem = rotulo("Isso leva alguns segundos.", CaptionLabel)
        textos_pc.addWidget(self.lbl_pc)
        textos_pc.addWidget(self.lbl_origem)
        linha_pc.addLayout(textos_pc, 1)
        self.corpo.addWidget(cartao_pc)

        # Cartão de escolha: peça + finalidade
        cartao_escolha = CartaoMarca()
        grade = QHBoxLayout(cartao_escolha)
        grade.setContentsMargins(20, 16, 20, 16)
        grade.setSpacing(16)

        self.combo_peca = ComboBox()
        for chave, (nome, _) in PECAS.items():
            self.combo_peca.addItem(nome, icon=ICONES_PECAS[chave], userData=chave)
        self.combo_uso = ComboBox()
        for chave, nome in USOS.items():
            self.combo_uso.addItem(nome, userData=chave)
        for texto, combo in (("Peça que quer comprar", self.combo_peca), ("Finalidade", self.combo_uso)):
            coluna = QVBoxLayout()
            coluna.setSpacing(6)
            coluna.addWidget(CaptionLabel(texto))
            combo.setMinimumWidth(230)
            coluna.addWidget(combo)
            grade.addLayout(coluna)

        branco = QColor("#FFFFFF")
        self.botao = PrimaryPushButton(FluentIcon.SEARCH.colored(branco, branco), "Recomendar")
        # No tema escuro a biblioteca usa texto preto no botão principal; no roxo da marca, branco lê melhor
        qss_botao = "PrimaryPushButton { color: #FFFFFF; } PrimaryPushButton:disabled { color: rgba(255,255,255,0.45); }"
        setCustomStyleSheet(self.botao, qss_botao, qss_botao)
        self.botao.setEnabled(False)
        self.botao.clicked.connect(self.recomendar)
        grade.addStretch()
        grade.addWidget(self.botao, 0, Qt.AlignBottom)
        self.corpo.addWidget(cartao_escolha)

        # Área de resultado
        self.resultado = QVBoxLayout()
        self.resultado.setSpacing(14)
        self.corpo.addLayout(self.resultado)
        self.finalizar()
        self.resultado.addWidget(rotulo("Escolha a peça e a finalidade e clique em Recomendar.", CaptionLabel))

    def definir_hardware(self, hw):
        self.hw = hw
        self.anel.hide()
        self.icone_pc.show()
        self.lbl_pc.setText(f"Seu computador: {descrever_computador(hw)}")
        self.lbl_origem.setText(f"Tipo identificado pelo {hw['origem_tipo']}.")
        self.botao.setEnabled(True)

    def mostrar_erro(self, erro):
        self.anel.hide()
        self.icone_pc.setIcon(icone_dourado(FluentIcon.INFO))
        self.icone_pc.show()
        self.lbl_pc.setText("Não foi possível ler as peças deste computador.")
        self.lbl_origem.setText(erro)

    def recomendar(self):
        if not self.hw:
            return
        peca = self.combo_peca.currentData()
        uso = self.combo_uso.currentData()
        secao = recomendar_peca(self.hw, self.categorias, peca, uso)

        limpar_layout(self.resultado)
        if secao["instalado"]:
            self.resultado.addWidget(Cartao(icone_dourado(ICONES_PECAS[peca]), "O que você tem hoje",
                                            secao["instalado"]))
        if secao["recomendacoes"]:
            self.resultado.addWidget(Cartao(icone_dourado(FluentIcon.ACCEPT), "Recomendação",
                                            secao["recomendacoes"],
                                            icone_linha=icone_dourado(FluentIcon.CHEVRON_RIGHT)))
        for aviso in secao["avisos"]:
            barra = InfoBar(InfoBarIcon.WARNING, "Atenção", aviso, orient=Qt.Vertical, isClosable=False,
                            duration=-1, position=InfoBarPosition.NONE)
            barra.setCustomBackgroundColor(COR_AVISO, COR_AVISO)
            self.resultado.addWidget(barra)


class PaginaMeuComputador(Pagina):
    def __init__(self, categorias, parent=None):
        super().__init__("paginaMeuComputador", "Meu computador", parent)
        self.categorias = categorias
        self.lista = QVBoxLayout()
        self.lista.setSpacing(14)
        self.corpo.addLayout(self.lista)
        self.finalizar()
        self.lista.addWidget(rotulo("Lendo as peças deste computador...", CaptionLabel))

    def definir_hardware(self, hw):
        limpar_layout(self.lista)
        self.lista.addWidget(rotulo(f"{descrever_computador(hw)}, identificado pelo {hw['origem_tipo']}.",
                                    CaptionLabel))
        for chave, (nome, _) in PECAS.items():
            instalado = recomendar_peca(hw, self.categorias, chave, "escritorio")["instalado"]
            if instalado:
                self.lista.addWidget(Cartao(icone_dourado(ICONES_PECAS[chave]), nome, instalado))


def aplicar_tema_marca():
    # A Blasync é uma marca escura: o tema fica escuro mesmo com o Windows no claro.
    setTheme(Theme.DARK)
    setThemeColor(COR_ROXO)


class App(FluentWindow):
    def __init__(self, categorias, escanear_ao_abrir=True):
        aplicar_tema_marca()
        super().__init__()
        self.setWindowTitle(f"Qual peça comprar? · {NOME_MARCA}")
        self.setWindowIcon(QIcon(str(ASSETS / "blasync.ico")))
        # Fundo da marca no lugar do Mica (o translúcido do Windows 11 mudaria a cor)
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor(QColor(COR_FUNDO), QColor(COR_FUNDO))
        self.resize(1000, 760)
        self.setMinimumSize(720, 520)

        self.pagina_recomendar = PaginaRecomendar(categorias, self)
        self.pagina_pc = PaginaMeuComputador(categorias, self)
        self.addSubInterface(self.pagina_recomendar, FluentIcon.SEARCH, "Recomendar")
        self.addSubInterface(self.pagina_pc, FluentIcon.IOT, "Meu computador")

        if escanear_ao_abrir:
            self.leitor = LeitorHardware(self)
            self.leitor.concluido.connect(self._leitura_concluida)
            self.leitor.start()

    def _leitura_concluida(self, hw, erro):
        if erro:
            self.pagina_recomendar.mostrar_erro(erro)
            return
        self.definir_hardware(hw)

    def definir_hardware(self, hw):
        self.pagina_recomendar.definir_hardware(hw)
        self.pagina_pc.definir_hardware(hw)


def gerar_diagnostico():
    """Grava num .txt o que o Windows informou do hardware, para quem está testando mandar de volta."""
    linhas = [f"Windows: {platform.platform()}", f"Programa: {'executável' if getattr(sys, 'frozen', False) else 'Python'}", ""]
    try:
        bruto = ler_hardware_bruto()
        linhas += ["== Leitura do Windows ==", json.dumps(bruto, ensure_ascii=False, indent=2), "",
                   "== Interpretação ==", json.dumps(interpretar(bruto), ensure_ascii=False, indent=2)]
    except Exception as erro:  # o diagnóstico existe justamente para registrar falhas
        linhas.append(f"Falha na leitura: {erro!r}")
    texto = "\n".join(linhas)

    pasta = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    for destino in (pasta / "diagnostico.txt", Path.home() / "diagnostico.txt"):
        try:
            destino.write_text(texto, encoding="utf-8")
            return destino
        except OSError:  # pasta sem permissão de escrita: tenta a pasta do usuário
            continue
    return None


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ASSETS / "blasync.ico")))
    aplicar_tema_marca()
    if "--diagnostico" in sys.argv:
        destino = gerar_diagnostico()
        mensagem = (f"Diagnóstico salvo em:\n{destino}\n\nEnvie esse arquivo para quem pediu o teste."
                    if destino else "Não foi possível gravar o arquivo de diagnóstico.")
        caixa = MessageBox("Diagnóstico", mensagem, None)
        caixa.cancelButton.hide()
        caixa.exec()
        return
    try:
        categorias = carregar_catalogo(CATALOGO_PADRAO)
    except Exception as erro:  # mostra o problema do catálogo em vez de fechar em silêncio
        caixa = MessageBox("Erro no catálogo", f"Não foi possível abrir {CATALOGO_PADRAO}:\n\n{erro}", None)
        caixa.cancelButton.hide()
        caixa.exec()
        return
    janela = App(categorias)
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
