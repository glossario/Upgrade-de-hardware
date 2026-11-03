import json
import tempfile
import unittest
from pathlib import Path

from recomendador import CatalogoInvalido, NIVEIS, USOS, carregar_catalogo, recomendar


class TestCatalogoReal(unittest.TestCase):
    def setUp(self):
        self.cat = carregar_catalogo()

    def test_toda_combinacao_gera_recomendacao_sem_filtros(self):
        for categoria in self.cat:
            for uso in USOS:
                for nivel in [None] + NIVEIS:
                    r = recomendar(self.cat, categoria, uso, nivel)
                    self.assertTrue(r["recomendacoes"], (categoria, uso, nivel))

    def test_cpu_respeita_socket(self):
        r = recomendar(self.cat, "cpu", "jogos", socket="AM4", quantidade=99)
        self.assertTrue(all(i["socket"] == "AM4" for i in r["recomendacoes"]))
        self.assertTrue(r["descartados"])

    def test_cpu_am4_jogos_avancado_cai_para_nivel_proximo_com_aviso(self):
        r = recomendar(self.cat, "cpu", "jogos", "avancado", socket="AM4")
        self.assertEqual(r["recomendacoes"][0]["modelo"], "AMD Ryzen 7 5700X3D")
        self.assertIsNotNone(r["aviso"])

    def test_gpu_respeita_fonte(self):
        r = recomendar(self.cat, "gpu", "jogos", fonte_w=550, quantidade=99)
        self.assertTrue(all(i["fonte_minima_w"] <= 550 for i in r["recomendacoes"]))

    def test_gpu_fonte_pequena_demais_nao_recomenda_nada(self):
        r = recomendar(self.cat, "gpu", "jogos", fonte_w=300)
        self.assertEqual(r["recomendacoes"], [])
        self.assertIn("Nenhum", r["aviso"])

    def test_filtro_que_nao_vale_para_a_categoria_e_ignorado(self):
        com = recomendar(self.cat, "armazenamento", "jogos", socket="AM4", memoria="DDR4", fonte_w=300)
        sem = recomendar(self.cat, "armazenamento", "jogos")
        self.assertEqual(com["recomendacoes"], sem["recomendacoes"])

    def test_ram_ddr5_jogos_intermediario(self):
        r = recomendar(self.cat, "ram", "jogos", "intermediario", memoria="DDR5")
        self.assertEqual(r["recomendacoes"][0]["modelo"], "Kit DDR5 32GB (2x16GB) 6000MHz CL30")
        self.assertIsNone(r["aviso"])

    def test_escritorio_prefere_cpu_com_video_integrado(self):
        r = recomendar(self.cat, "cpu", "escritorio", "entrada")
        self.assertIn("Sim", r["recomendacoes"][0]["specs"]["Vídeo integrado"])

    def test_parametros_invalidos(self):
        with self.assertRaises(KeyError):
            recomendar(self.cat, "teclado", "jogos")
        with self.assertRaises(KeyError):
            recomendar(self.cat, "cpu", "minerar")
        with self.assertRaises(KeyError):
            recomendar(self.cat, "cpu", "jogos", "ultra")


class TestValidacaoCatalogo(unittest.TestCase):
    def _carregar(self, dados):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps(dados), encoding="utf-8")
            return carregar_catalogo(p)

    def test_nota_fora_da_faixa(self):
        item = {"modelo": "X", "nivel": "entrada", "notas": {"jogos": 11, "escritorio": 5, "edicao": 5}}
        with self.assertRaises(CatalogoInvalido):
            self._carregar({"categorias": {"cpu": {"nome": "CPU", "itens": [item]}}})

    def test_nivel_invalido(self):
        item = {"modelo": "X", "nivel": "top", "notas": {"jogos": 5, "escritorio": 5, "edicao": 5}}
        with self.assertRaises(CatalogoInvalido):
            self._carregar({"categorias": {"cpu": {"nome": "CPU", "itens": [item]}}})

    def test_sem_categorias(self):
        with self.assertRaises(CatalogoInvalido):
            self._carregar({})


if __name__ == "__main__":
    unittest.main()
