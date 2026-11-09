import copy
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # testa a janela sem abrir na tela

from PySide6.QtWidgets import QApplication, QLabel

from app import App
from recomendador import USOS, carregar_catalogo
from scanner import interpretar
from upgrade import PECAS, recomendar_peca

GIB = 1024 ** 3
CAT = carregar_catalogo()

# Leitura real do Dell Latitude 3550 (1x16 GB DDR5 SO-DIMM, 2 slots)
NOTEBOOK = {
    "sistema": {"Manufacturer": "Dell Inc.", "Model": "Latitude 3550", "PCSystemType": 2, "SystemSKUNumber": "0C98"},
    "bios": {"SerialNumber": "9LPDVB4", "SMBIOSBIOSVersion": "1.22.1"},
    "memorias": [{"Manufacturer": "04CB000080AD", "PartNumber": "AL1V56WCSV1-B1ES   ", "Capacity": 16 * GIB,
                  "Speed": 5600, "ConfiguredClockSpeed": 5200, "SMBIOSMemoryType": 34, "MemoryType": 0,
                  "FormFactor": 12, "DeviceLocator": "DIMM 1"}],
    "slots": [{"MemoryDevices": 2, "MaxCapacity": 67108864, "MaxCapacityEx": 67108864}],
    "cpu": [{"Name": "13th Gen Intel(R) Core(TM) i5-1345U", "SocketDesignation": "U3E1",
             "NumberOfCores": 10, "NumberOfLogicalProcessors": 12}],
    "gpus": [{"Name": "Intel(R) UHD Graphics", "AdapterRAM": 2147479552}],
    "discos": [{"FriendlyName": "BG6 KIOXIA 256GB", "MediaType": "SSD", "BusType": "NVMe", "Size": 256060514304}],
    "placa": {"Manufacturer": "Dell Inc.", "Product": "064F52", "Version": "A00"},
    "baterias": 1,
    "gabinete": [10],
}

def pente(slot, gb=8, tipo=26, ff=8, mhz=3200):
    return {"PartNumber": "X", "Capacity": gb * GIB, "Speed": mhz, "ConfiguredClockSpeed": mhz,
            "SMBIOSMemoryType": tipo, "FormFactor": ff, "DeviceLocator": slot}

DESKTOP = {
    "sistema": {"Manufacturer": "PC", "Model": "Montado", "PCSystemType": 1},
    "memorias": [pente("DIMM_A2"), pente("DIMM_B2")],
    "slots": {"MemoryDevices": 4, "MaxCapacityEx": 128 * 1024 ** 2},  # objeto único, não lista
    "cpu": {"Name": "AMD Ryzen 5 5600X 6-Core Processor", "SocketDesignation": "AM4",
            "NumberOfCores": 6, "NumberOfLogicalProcessors": 12},
    "gpus": [{"Name": "NVIDIA GeForce RTX 4060"}, {"Name": "Microsoft Basic Display Adapter"}],
    "discos": [{"FriendlyName": "WD Blue", "MediaType": "HDD", "BusType": "SATA", "Size": 1000 * 1000 ** 3},
               {"FriendlyName": "Pendrive", "MediaType": "Unspecified", "BusType": "USB", "Size": 32 * 1000 ** 3}],
    "baterias": 0,
}


def rec(bruto, peca, uso="jogos"):
    return recomendar_peca(interpretar(bruto), CAT, peca, uso)


def texto_rec(bruto, peca, uso="jogos"):
    return " ".join(rec(bruto, peca, uso)["recomendacoes"])


class TestScanner(unittest.TestCase):
    def test_notebook_real(self):
        hw = interpretar(NOTEBOOK)
        self.assertEqual(hw["tipo"], "notebook")
        m = hw["memoria"]
        self.assertEqual((m["slots_total"], m["max_gb"]), (2, 64))
        self.assertEqual(m["modulos"][0], {"slot": "DIMM 1", "capacidade_gb": 16, "tipo": "DDR5",
                                           "formato": "SO-DIMM", "velocidade_mhz": 5600,
                                           "velocidade_atual_mhz": 5200, "part_number": "AL1V56WCSV1-B1ES"})
        self.assertTrue(hw["gpus"][0]["integrada"])

    def test_desktop_objeto_unico_ignora_usb_e_adaptador_basico(self):
        hw = interpretar(DESKTOP)
        self.assertEqual(hw["tipo"], "desktop")
        self.assertEqual((hw["memoria"]["slots_total"], hw["memoria"]["max_gb"]), (4, 128))
        self.assertEqual([d["nome"] for d in hw["discos"]], ["WD Blue"])
        self.assertEqual([g["nome"] for g in hw["gpus"]], ["NVIDIA GeForce RTX 4060"])
        self.assertFalse(hw["gpus"][0]["integrada"])

    def test_dados_vazios_nao_quebram_nenhuma_combinacao(self):
        hw = interpretar({})
        for peca in PECAS:
            for uso in USOS:
                self.assertIn("recomendacoes", recomendar_peca(hw, CAT, peca, uso))

    def test_todas_combinacoes_nos_dois_tipos(self):
        for bruto in (NOTEBOOK, DESKTOP):
            for peca in PECAS:
                for uso in USOS:
                    s = rec(bruto, peca, uso)
                    self.assertTrue(s["recomendacoes"] or s["avisos"], (peca, uso))


class TestTipoComputador(unittest.TestCase):
    def test_notebook_pelo_gabinete(self):
        hw = interpretar(NOTEBOOK)
        self.assertEqual(hw["tipo"], "notebook")
        self.assertIn("gabinete", hw["origem_tipo"])

    def test_gabinete_tem_prioridade(self):
        bruto = copy.deepcopy(NOTEBOOK)
        bruto["gabinete"] = [7]  # torre
        self.assertEqual(interpretar(bruto)["tipo"], "desktop")

    def test_sem_gabinete_usa_tipo_de_sistema(self):
        bruto = copy.deepcopy(NOTEBOOK)
        bruto["gabinete"] = [2]  # "desconhecido" na tabela SMBIOS
        self.assertEqual(interpretar(bruto)["origem_tipo"], "tipo de sistema informado pelo Windows")

    def test_ultimo_recurso_memoria_so_dimm(self):
        bruto = copy.deepcopy(NOTEBOOK)
        del bruto["gabinete"]
        bruto["sistema"]["PCSystemType"] = 0
        bruto["baterias"] = 0
        hw = interpretar(bruto)
        self.assertEqual(hw["tipo"], "notebook")
        self.assertIn("SO-DIMM", hw["origem_tipo"])

    def test_all_in_one_nao_sugere_trocar_cpu(self):
        bruto = copy.deepcopy(DESKTOP)
        bruto["gabinete"] = [13]
        self.assertIn("troca-se a placa-mãe inteira", texto_rec(bruto, "processador"))


class TestMemoria(unittest.TestCase):
    def test_notebook_jogos_sugere_pente_identico(self):
        texto = texto_rec(NOTEBOOK, "memoria", "jogos")
        self.assertIn("1x pente 16 GB DDR5 SO-DIMM 5600 MHz", texto)
        self.assertIn("32 GB", texto)
        self.assertIn("dual channel", texto)
        self.assertIn("AL1V56WCSV1-B1ES", texto)
        self.assertIn("limita a memória a 5200 MHz", texto)
        self.assertNotIn("DDR4", texto)

    def test_notebook_escritorio_ja_basta(self):
        texto = texto_rec(NOTEBOOK, "memoria", "escritorio")
        self.assertIn("16 GB já é suficiente", texto)
        self.assertIn("Se quiser mais desempenho", texto)

    def test_notebook_edicao_sugere_kit_de_64(self):
        recs = rec(NOTEBOOK, "memoria", "edicao")["recomendacoes"]
        self.assertIn("2x 32 GB DDR5 SO-DIMM 5600 MHz", recs[0])
        self.assertIn("Opção mais barata (32 GB)", recs[1])

    def test_memoria_soldada(self):
        bruto = copy.deepcopy(NOTEBOOK)
        bruto["memorias"][0]["SMBIOSMemoryType"] = 35  # LPDDR5
        recs = rec(bruto, "memoria")["recomendacoes"]
        self.assertEqual(len(recs), 1)
        self.assertIn("soldada", recs[0])

    def test_slots_cheios_sugere_kit_maior_ddr4(self):
        bruto = copy.deepcopy(DESKTOP)
        bruto["slots"]["MemoryDevices"] = 2
        texto = texto_rec(bruto, "memoria", "jogos")
        self.assertIn("2x 16 GB DDR4 DIMM 3200 MHz", texto)
        self.assertNotIn("DDR5", texto)

    def test_slots_cheios_no_maximo(self):
        bruto = copy.deepcopy(DESKTOP)
        bruto["slots"] = {"MemoryDevices": 2, "MaxCapacityEx": 16 * 1024 ** 2}
        self.assertIn("16 GB já é suficiente", texto_rec(bruto, "memoria", "escritorio"))
        self.assertIn("já está no máximo", texto_rec(bruto, "memoria", "jogos"))

    def test_desktop_slots_livres_jogos_completa_com_iguais(self):
        self.assertIn("2x pente 8 GB DDR4 DIMM 3200 MHz", texto_rec(DESKTOP, "memoria", "jogos"))


class TestOutrasPecas(unittest.TestCase):
    def test_notebook_ssd_pequeno(self):
        texto = texto_rec(NOTEBOOK, "armazenamento", "jogos")
        self.assertIn("1 TB", texto)
        self.assertIn("NVMe", texto)

    def test_hd_sem_ssd(self):
        self.assertIn("SSD NVMe", texto_rec(DESKTOP, "armazenamento", "escritorio"))

    def test_desktop_cpu_mesmo_socket_mais_forte_que_o_atual(self):
        recs = rec(DESKTOP, "processador", "jogos")["recomendacoes"]
        texto = " ".join(recs)
        self.assertIn("AM4", texto)
        self.assertNotIn("AM5", texto)
        self.assertNotIn("Ryzen 5 5600.", texto)  # o instalado (5600X) não é sugerido
        self.assertTrue(any("5700X3D" in r for r in recs))

    def test_desktop_gpu_so_mais_fortes_que_a_atual(self):
        recs = rec(DESKTOP, "video", "jogos")["recomendacoes"]
        self.assertFalse(any("RTX 4060 8GB" in r or "RX 6600" in r or "RTX 3050" in r for r in recs))
        self.assertTrue(any(r.startswith("Avançado") for r in recs))

    def test_desktop_placa_mae_mesmo_socket_e_memoria(self):
        recs = rec(DESKTOP, "placa_mae")["recomendacoes"]
        self.assertTrue(any("B550" in r for r in recs))
        self.assertFalse(any("AM5" in r for r in recs[1:]))

    def test_desktop_fonte_respeita_gpu_atual(self):
        self.assertIn("pede no mínimo 550 W", texto_rec(DESKTOP, "fonte"))

    def test_notebook_cpu_e_video_apontam_para_placa_mae(self):
        for peca in ("processador", "video"):
            texto = texto_rec(NOTEBOOK, peca)
            self.assertIn("troca-se a placa-mãe inteira", texto)
            self.assertIn("Dell Latitude 3550", texto)
        self.assertIn("não há fonte", texto_rec(NOTEBOOK, "fonte"))


class TestPlacaMaeNotebook(unittest.TestCase):
    def test_mostra_referencias_para_compra(self):
        instalado = " ".join(rec(NOTEBOOK, "placa_mae")["instalado"])
        self.assertIn("part number): 064F52 (revisão A00)", instalado)
        self.assertIn("Service Tag): 9LPDVB4", instalado)
        self.assertIn("SKU: 0C98 | BIOS: 1.22.1", instalado)
        self.assertIn("DDR5 SO-DIMM", instalado)
        self.assertIn("i5-1345U", instalado)

    def test_sugere_linha_acima_e_termo_de_busca(self):
        texto = texto_rec(NOTEBOOK, "placa_mae", "jogos")
        self.assertIn("versão com Core i7 (a sua é Core i5)", texto)
        self.assertIn('"placa mãe Dell Latitude 3550 Core i7"', texto)
        self.assertNotIn("Inc.", texto)
        self.assertIn("vídeo dedicada", texto)

    def test_escritorio_avisa_que_i5_basta(self):
        self.assertIn("Core i5 atual normalmente basta", texto_rec(NOTEBOOK, "placa_mae", "escritorio"))

    def test_avisos_de_compatibilidade(self):
        avisos = " ".join(rec(NOTEBOOK, "placa_mae")["avisos"])
        self.assertIn("mesmo modelo de notebook", avisos)
        self.assertIn("mesma memória (DDR5 SO-DIMM)", avisos)
        self.assertIn("número de série (9LPDVB4)", avisos)

    def test_linha_mais_alta(self):
        bruto = copy.deepcopy(NOTEBOOK)
        bruto["cpu"][0]["Name"] = "AMD Ryzen 9 7940HS w/ Radeon 780M Graphics"
        self.assertIn("já é da linha mais alta", texto_rec(bruto, "placa_mae"))

    def test_core_ultra(self):
        bruto = copy.deepcopy(NOTEBOOK)
        bruto["cpu"][0]["Name"] = "Intel(R) Core(TM) Ultra 5 125U"
        self.assertIn("versão com Core Ultra 7 (a sua é Core Ultra 5)", texto_rec(bruto, "placa_mae"))

    def test_identificacao_de_preenchimento_e_ignorada(self):
        bruto = copy.deepcopy(NOTEBOOK)
        bruto["placa"] = {"Manufacturer": "OEM", "Product": "To be filled by O.E.M.", "Version": "Default string"}
        bruto["bios"] = {"SerialNumber": "System Serial Number"}
        hw = interpretar(bruto)
        self.assertEqual(hw["identificacao"]["placa_referencia"], "")
        self.assertEqual(hw["identificacao"]["numero_serie"], "")
        instalado = " ".join(recomendar_peca(hw, CAT, "placa_mae", "jogos")["instalado"])
        self.assertIn("não informada pelo Windows", instalado)
        self.assertNotIn("Service Tag", instalado)


class TestDiagnostico(unittest.TestCase):
    def test_grava_leitura_e_interpretacao(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        import app
        with tempfile.TemporaryDirectory() as pasta, \
                mock.patch.object(app, "ler_hardware_bruto", return_value=NOTEBOOK), \
                mock.patch.object(app.Path, "cwd", return_value=Path(pasta)):
            destino = app.gerar_diagnostico()
            texto = destino.read_text(encoding="utf-8")
        self.assertEqual(destino.name, "diagnostico.txt")
        self.assertIn("Latitude 3550", texto)
        self.assertIn('"tipo": "notebook"', texto)

    def test_falha_na_leitura_fica_registrada(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        import app
        with tempfile.TemporaryDirectory() as pasta, \
                mock.patch.object(app, "ler_hardware_bruto", side_effect=RuntimeError("sem WMI")), \
                mock.patch.object(app.Path, "cwd", return_value=Path(pasta)):
            texto = app.gerar_diagnostico().read_text(encoding="utf-8")
        self.assertIn("sem WMI", texto)


class TestJanela(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def textos(self, widget):
        return " ".join(l.text() for l in widget.findChildren(QLabel))

    def test_fluxo_peca_e_finalidade(self):
        app = App(CAT, escanear_ao_abrir=False)
        try:
            pagina = app.pagina_recomendar
            self.assertFalse(pagina.botao.isEnabled())
            app.definir_hardware(interpretar(NOTEBOOK))
            self.assertTrue(pagina.botao.isEnabled())
            self.assertIn("Latitude 3550 (notebook)", pagina.lbl_pc.text())

            pagina.combo_peca.setCurrentIndex(list(PECAS).index("memoria"))
            pagina.combo_uso.setCurrentIndex(list(USOS).index("jogos"))
            pagina.recomendar()
            texto = self.textos(pagina)
            self.assertIn("16 GB DDR5 SO-DIMM 5600 MHz", texto)
            self.assertIn("Confira no manual", texto)  # aviso aparece
            self.assertNotIn("DDR4", texto)

            # Trocar a escolha substitui o resultado anterior
            pagina.combo_peca.setCurrentIndex(list(PECAS).index("processador"))
            pagina.recomendar()
            self.qapp.processEvents()
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            texto = self.textos(pagina)
            self.assertIn("troca-se a placa-mãe inteira", texto)
            self.assertNotIn("SO-DIMM 5600 MHz, igual", texto)

            self.assertIn("BG6 KIOXIA", self.textos(app.pagina_pc))
        finally:
            app.close()

    def test_identidade_visual_blasync(self):
        import app as modulo
        from app import FaixaMarca
        from qfluentwidgets import isDarkTheme, qconfig
        for arquivo in ("faixa_blasync.jpg", "simbolo_blasync.png", "blasync.ico"):
            self.assertTrue((modulo.ASSETS / arquivo).is_file(), arquivo)
        janela = App(CAT, escanear_ao_abrir=False)
        try:
            self.assertIn("Blasync Technology", janela.windowTitle())
            self.assertFalse(janela.windowIcon().isNull())
            self.assertTrue(isDarkTheme())
            # A cor configurada; no tema escuro a biblioteca a exibe um pouco mais clara para contraste
            self.assertEqual(qconfig.get(qconfig.themeColor).name().upper(), modulo.COR_ROXO)
            faixas = janela.pagina_recomendar.findChildren(FaixaMarca)
            self.assertEqual(len(faixas), 1)
            self.assertFalse(faixas[0].imagem.isNull())
            self.assertIn("impulsionando o amanhã", self.textos(janela.pagina_pc))
        finally:
            janela.close()


if __name__ == "__main__":
    unittest.main()
