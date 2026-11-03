"""Janela do recomendador de peças de PC (visual Fluent / Windows 11). Execute: python app.py

O usuário escolhe só a peça e a finalidade; o hardware é lido automaticamente ao abrir.
"""
import sys

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, FluentIcon, FluentWindow, IconWidget,
    IndeterminateProgressRing, InfoBar, InfoBarIcon, InfoBarPosition, MessageBox,
    PrimaryPushButton, SimpleCardWidget, SmoothScrollArea, StrongBodyLabel,
    Theme, TitleLabel, setTheme,
)

from recomendador import CATALOGO_PADRAO, USOS, carregar_catalogo
from scanner import FalhaLeitura, escanear
from upgrade import PECAS, recomendar_peca

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


class Cartao(SimpleCardWidget):
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
            linha.addWidget(rotulo(texto), 1)
            layout.addLayout(linha)


class Pagina(SmoothScrollArea):
    """Página rolável com título; o conteúdo vai em `self.corpo`."""

    def __init__(self, nome_objeto, titulo, parent=None):
        super().__init__(parent)
        self.setObjectName(nome_objeto)  # o FluentWindow exige objectName nas páginas
        self.setWidgetResizable(True)
        # Sem rolagem lateral: o conteúdo acompanha a largura da janela e o texto quebra linha.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        conteudo = QWidget()
        conteudo.setStyleSheet("background: transparent;")
        self.corpo = QVBoxLayout(conteudo)
        self.corpo.setContentsMargins(36, 28, 36, 28)
        self.corpo.setSpacing(14)
        self.corpo.addWidget(rotulo(titulo, TitleLabel))
        self.setWidget(conteudo)


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
        super().__init__("paginaRecomendar", "Qual peça comprar?", parent)
        self.categorias = categorias
        self.hw = None

        # Cartão do computador detectado
        cartao_pc = SimpleCardWidget()
        linha_pc = QHBoxLayout(cartao_pc)
        linha_pc.setContentsMargins(20, 16, 20, 16)
        linha_pc.setSpacing(14)
        self.anel = IndeterminateProgressRing()
        self.anel.setFixedSize(28, 28)
        self.icone_pc = IconWidget(FluentIcon.IOT)
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
        cartao_escolha = SimpleCardWidget()
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

        self.botao = PrimaryPushButton(FluentIcon.SEARCH, "Recomendar")
        self.botao.setEnabled(False)
        self.botao.clicked.connect(self.recomendar)
        grade.addStretch()
        grade.addWidget(self.botao, 0, Qt.AlignBottom)
        self.corpo.addWidget(cartao_escolha)

        # Área de resultado
        self.resultado = QVBoxLayout()
        self.resultado.setSpacing(14)
        self.corpo.addLayout(self.resultado)
        self.corpo.addStretch(1)  # mantém o conteúdo no topo quando sobra espaço
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
        self.icone_pc.setIcon(FluentIcon.INFO)
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
            self.resultado.addWidget(Cartao(ICONES_PECAS[peca], "O que você tem hoje", secao["instalado"]))
        if secao["recomendacoes"]:
            self.resultado.addWidget(Cartao(FluentIcon.ACCEPT, "Recomendação", secao["recomendacoes"],
                                            icone_linha=FluentIcon.CHEVRON_RIGHT))
        for aviso in secao["avisos"]:
            self.resultado.addWidget(InfoBar(
                InfoBarIcon.WARNING, "Atenção", aviso, orient=Qt.Vertical, isClosable=False,
                duration=-1, position=InfoBarPosition.NONE))


class PaginaMeuComputador(Pagina):
    def __init__(self, categorias, parent=None):
        super().__init__("paginaMeuComputador", "Meu computador", parent)
        self.categorias = categorias
        self.lista = QVBoxLayout()
        self.lista.setSpacing(14)
        self.corpo.addLayout(self.lista)
        self.corpo.addStretch(1)  # mantém o conteúdo no topo quando sobra espaço
        self.lista.addWidget(rotulo("Lendo as peças deste computador...", CaptionLabel))

    def definir_hardware(self, hw):
        limpar_layout(self.lista)
        self.lista.addWidget(rotulo(f"{descrever_computador(hw)}, identificado pelo {hw['origem_tipo']}.",
                                    CaptionLabel))
        for chave, (nome, _) in PECAS.items():
            instalado = recomendar_peca(hw, self.categorias, chave, "escritorio")["instalado"]
            if instalado:
                self.lista.addWidget(Cartao(ICONES_PECAS[chave], nome, instalado))


class App(FluentWindow):
    def __init__(self, categorias, escanear_ao_abrir=True):
        super().__init__()
        self.setWindowTitle("Qual peça comprar?")
        self.resize(980, 720)
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


def main():
    app = QApplication(sys.argv)
    setTheme(Theme.AUTO)  # segue o tema claro/escuro do Windows
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
