"""Lógica de recomendação de peças de PC.

Não depende de interface: recebe o catálogo e as escolhas do usuário e devolve
os modelos mais indicados, já filtrados por compatibilidade.
"""
import json
from pathlib import Path

CATALOGO_PADRAO = Path(__file__).parent / "dados" / "catalogo.json"

NIVEIS = ["entrada", "intermediario", "avancado"]
NOMES_NIVEIS = {"entrada": "Entrada", "intermediario": "Intermediário", "avancado": "Avançado"}

USOS = {
    "jogos": "Jogos",
    "escritorio": "Escritório / estudo",
    "edicao": "Edição de vídeo / criação",
}

SOCKETS = ["AM4", "AM5", "LGA1700"]
MEMORIAS = ["DDR4", "DDR5"]


class CatalogoInvalido(ValueError):
    pass


def carregar_catalogo(caminho=CATALOGO_PADRAO):
    """Lê o catálogo JSON e valida cada item, para que erros de edição apareçam já na abertura."""
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)

    categorias = dados.get("categorias")
    if not isinstance(categorias, dict) or not categorias:
        raise CatalogoInvalido("O catálogo não tem a chave 'categorias'.")

    for chave, cat in categorias.items():
        for campo in ("nome", "itens"):
            if campo not in cat:
                raise CatalogoInvalido(f"Categoria '{chave}' sem o campo '{campo}'.")
        for i, item in enumerate(cat["itens"], start=1):
            local = f"{chave}, item {i} ({item.get('modelo', 'sem modelo')})"
            if not item.get("modelo"):
                raise CatalogoInvalido(f"{local}: falta 'modelo'.")
            if item.get("nivel") not in NIVEIS:
                raise CatalogoInvalido(f"{local}: 'nivel' deve ser um de {NIVEIS}.")
            notas = item.get("notas", {})
            for uso in USOS:
                nota = notas.get(uso)
                if not isinstance(nota, (int, float)) or not 0 <= nota <= 10:
                    raise CatalogoInvalido(f"{local}: nota de '{uso}' ausente ou fora de 0-10.")
    return categorias


def motivo_incompatibilidade(item, filtros, socket=None, memoria=None, fonte_w=None):
    """Devolve o motivo pelo qual o item não serve, ou None se for compatível.

    Só aplica os filtros que a categoria declara; um filtro sem valor informado é ignorado.
    """
    if "socket" in filtros and socket and item.get("socket") != socket:
        return f"socket {item.get('socket')} (o seu é {socket})"
    if "memoria" in filtros and memoria and memoria not in item.get("memoria", []):
        return f"memória {'/'.join(item.get('memoria', []))} (a sua é {memoria})"
    if "fonte_w" in filtros and fonte_w and fonte_w < item.get("fonte_minima_w", 0):
        return f"pede fonte de {item['fonte_minima_w']} W (a sua tem {fonte_w} W)"
    return None


def recomendar(categorias, categoria, uso, nivel=None, socket=None, memoria=None,
               fonte_w=None, quantidade=3):
    """Ordena os itens compatíveis e devolve os `quantidade` mais indicados.

    Critério: mais próximo do nível pedido primeiro, depois maior nota para o uso
    e, no empate, o nível mais baixo (menos peça do que o necessário não é comprada à toa).
    """
    if categoria not in categorias:
        raise KeyError(f"Categoria desconhecida: {categoria}")
    if uso not in USOS:
        raise KeyError(f"Uso desconhecido: {uso}")
    if nivel is not None and nivel not in NIVEIS:
        raise KeyError(f"Nível desconhecido: {nivel}")

    cat = categorias[categoria]
    filtros = cat.get("filtros", [])

    compativeis, descartados = [], []
    for item in cat["itens"]:
        motivo = motivo_incompatibilidade(item, filtros, socket, memoria, fonte_w)
        if motivo:
            descartados.append((item, motivo))
        else:
            compativeis.append(item)

    def distancia(item):
        if nivel is None:
            return 0
        return abs(NIVEIS.index(item["nivel"]) - NIVEIS.index(nivel))

    ordenados = sorted(
        compativeis,
        key=lambda it: (distancia(it), -it["notas"][uso], NIVEIS.index(it["nivel"])),
    )

    aviso = None
    if not compativeis:
        aviso = "Nenhum modelo do catálogo é compatível com as peças informadas."
    elif nivel is not None and distancia(ordenados[0]) > 0:
        aviso = (f"Não há opção compatível no nível {NOMES_NIVEIS[nivel]}; "
                 "mostrando as do nível mais próximo.")

    dicas = cat.get("dicas", {})
    dica = dicas.get(uso) or dicas.get("_geral")

    return {
        "categoria": cat["nome"],
        "recomendacoes": ordenados[:quantidade],
        "total_compativeis": len(compativeis),
        "descartados": descartados,
        "aviso": aviso,
        "dica": dica,
    }
