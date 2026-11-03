"""Transforma o hardware detectado em sugestões de compra compatíveis com o que já está instalado.

O usuário só escolhe a peça e a finalidade; tudo o mais (notebook/desktop, tipo de memória,
socket, slots) vem do escaneamento. Cada função devolve uma seção:
{"titulo", "instalado", "recomendacoes", "avisos"}.
"""
import re

from recomendador import NIVEIS, NOMES_NIVEIS, SOCKETS, USOS, recomendar

# Tipos em que processador, vídeo e placa-mãe vêm soldados / não são trocáveis
TIPOS_INTEGRADOS = ("notebook", "all-in-one")

# Quanto cada finalidade pede (GB). Acima disso o ganho é pequeno.
ALVO_RAM_GB = {"escritorio": 16, "jogos": 32, "edicao": 64}
ALVO_DISCO_GB = {"escritorio": 500, "jogos": 1000, "edicao": 2000}


def tipo_memoria_unico(hw):
    """O tipo de memória que a placa usa (DDR4/DDR5), se todos os pentes concordarem."""
    tipos = {m["tipo"] for m in hw["memoria"]["modulos"] if m["tipo"]}
    return tipos.pop() if len(tipos) == 1 else None


def _nucleo_modelo(modelo):
    """'NVIDIA GeForce RTX 4060 8GB' -> 'geforce rtx 4060'; 'Intel Core i5-12400' -> 'core i5-12400'."""
    return re.sub(r"^(nvidia|amd|intel)\s+|\s+\d+gb$", "", modelo.lower())


def _ja_instalado(modelo, nomes_instalados):
    instalado = re.sub(r"\((r|tm)\)", "", nomes_instalados.lower())
    return _nucleo_modelo(modelo) in re.sub(r"\s+", " ", instalado)


def _secao(titulo):
    return {"titulo": titulo, "instalado": [], "recomendacoes": [], "avisos": []}


_SUFIXOS_EMPRESA = re.compile(r",?\s+(inc\.?|corporation|corp\.?|co\.?,?\s*ltd\.?|ltd\.?|limited|gmbh)$", re.I)


def _nome_computador(hw):
    """'Dell Inc.' + 'Latitude 3550' -> 'Dell Latitude 3550' (sem sufixo de empresa, que atrapalha a busca)."""
    fabricante = _SUFIXOS_EMPRESA.sub("", hw["fabricante"]).strip()
    return " ".join(filter(None, [fabricante, hw["modelo"]])) or "o mesmo modelo"


# Linhas de processador em ordem crescente, por fabricante
_LINHAS_CPU = [
    (re.compile(r"core\s*ultra\s*([3579])\b", re.I), "Core Ultra {}", ["3", "5", "7", "9"]),
    (re.compile(r"core\s*i([3579])\b|\bi([3579])-\d", re.I), "Core i{}", ["3", "5", "7", "9"]),
    (re.compile(r"ryzen\s*([3579])\b", re.I), "Ryzen {}", ["3", "5", "7", "9"]),
]


def _linhas_superiores(nome_cpu):
    """'13th Gen Intel(R) Core(TM) i5-1345U' -> ('Core i5', ['Core i7', 'Core i9'])."""
    nome = re.sub(r"\((r|tm)\)", "", nome_cpu, flags=re.I)
    for padrao, formato, ordem in _LINHAS_CPU:
        achado = padrao.search(nome)
        if achado:
            atual = next(g for g in achado.groups() if g)
            return formato.format(atual), [formato.format(n) for n in ordem[ordem.index(atual) + 1:]]
    return None, []


def _para_placa_mae(s, hw, situacao, objetivo):
    """Notebook/all-in-one: a peça vem soldada, então o upgrade é pela troca da placa-mãe."""
    s["recomendacoes"].append(
        f"Em {hw['tipo']}, {situacao} na placa-mãe. Para ter {objetivo}, troca-se a placa-mãe inteira por uma "
        f"versão do mesmo modelo ({_nome_computador(hw)}). Escolha \"Placa-mãe\" para ver as referências "
        "necessárias para a compra.")
    return s


def _tamanho(gb):
    return f"{gb // 1000} TB" if gb >= 1000 else f"{gb} GB"


# ---------------------------------------------------------------- memória

def _descrever_modulo(m):
    partes = [f"{m['capacidade_gb']} GB", m["tipo"] or "tipo desconhecido", m["formato"] or ""]
    if m["velocidade_mhz"]:
        partes.append(f"{m['velocidade_mhz']} MHz")
    texto = " ".join(p for p in partes if p)
    if m["velocidade_atual_mhz"] and m["velocidade_mhz"] and m["velocidade_atual_mhz"] < m["velocidade_mhz"]:
        texto += f" (rodando a {m['velocidade_atual_mhz']} MHz)"
    if m["part_number"]:
        texto += f" | código da peça: {m['part_number']}"
    return f"{m['slot']}: {texto}"


def _especificacao_pente(capacidade_gb, tipo, formato, velocidade):
    partes = [f"{capacidade_gb} GB", tipo, formato or "(confira se é DIMM ou SO-DIMM)"]
    if velocidade:
        partes.append(f"{velocidade} MHz")
    return " ".join(partes)


def sugerir_memoria(hw, categorias, uso):
    s = _secao("Memória RAM")
    mem = hw["memoria"]
    mods = mem["modulos"]
    if not mods:
        s["avisos"].append("O Windows não informou os pentes de memória instalados.")
        return s

    total = sum(m["capacidade_gb"] for m in mods)
    slots = mem["slots_total"]
    max_gb = mem["max_gb"]
    s["instalado"] = [_descrever_modulo(m) for m in mods]
    resumo = f"Total: {total} GB"
    if slots:
        resumo += f" | Slots ocupados: {len(mods)} de {slots}"
    if max_gb:
        resumo += f" | Máximo suportado: {max_gb} GB"
    s["instalado"].append(resumo)

    tipos = {m["tipo"] for m in mods}
    tipo = mods[0]["tipo"]
    if any(t and t.startswith("LPDDR") for t in tipos) or any(m["formato"] == "soldada" for m in mods):
        s["recomendacoes"].append("A memória é soldada na placa (LPDDR/onboard), então não dá para expandir.")
        return s
    if not tipo:
        s["avisos"].append("Não foi possível identificar se a memória é DDR4 ou DDR5. Confira no manual antes de comprar.")
        tipo = "DDR?"
    if len(tipos) > 1 or len({(m["capacidade_gb"], m["velocidade_mhz"]) for m in mods}) > 1:
        s["avisos"].append("Os pentes instalados são diferentes entre si. O conjunto roda na velocidade do mais lento.")

    # Referência: o pente instalado de menor velocidade, que é quem define a velocidade do conjunto.
    ref = min(mods, key=lambda m: m["velocidade_mhz"] or 10 ** 6)
    formato, velocidade = ref["formato"], ref["velocidade_mhz"]
    livres = slots - len(mods) if slots else None
    alvo = min(ALVO_RAM_GB[uso], max_gb) if max_gb else ALVO_RAM_GB[uso]
    finalidade = USOS[uso].lower()

    # Opção 1: completar os slots livres com pentes iguais ao atual.
    igual = None
    if livres is None or livres > 0:
        qtd = livres or 1
        novo_total = total + ref["capacidade_gb"] * qtd
        if not max_gb or novo_total <= max_gb:
            texto = (f"Comprar {qtd}x pente {_especificacao_pente(ref['capacidade_gb'], tipo, formato, velocidade)}, "
                     f"igual ao que você já tem. O total passa a {novo_total} GB.")
            if len(mods) == 1:
                texto += (" Com dois pentes iguais, a memória passa a trabalhar em dual channel, o que melhora o "
                          "desempenho (principalmente o do vídeo integrado).")
            igual = (novo_total, texto)

    # Opção 2: trocar tudo por pentes maiores, o suficiente para a finalidade.
    kit = None
    if slots:
        por_pente = ref["capacidade_gb"] * 2
        while por_pente * slots < alvo:
            por_pente *= 2
        kit_total = por_pente * slots
        if not max_gb or kit_total <= max_gb:
            kit = (kit_total, f"Trocar tudo por {slots}x {_especificacao_pente(por_pente, tipo, formato, velocidade)} "
                              f"({kit_total} GB no total).")

    if total >= alvo and alvo < ALVO_RAM_GB[uso]:
        s["recomendacoes"].append(
            f"A memória já está no máximo que este computador suporta ({max_gb} GB). Para {finalidade} o ideal "
            f"seria {ALVO_RAM_GB[uso]} GB, mas esta máquina não aceita mais.")
    elif total >= alvo:
        s["recomendacoes"].append(f"Para {finalidade}, {total} GB já é suficiente.")
        if igual and len(mods) == 1:
            s["recomendacoes"].append("Se quiser mais desempenho mesmo assim: " + igual[1])
    elif igual and igual[0] >= alvo:
        s["recomendacoes"].append(f"Para {finalidade}, o ideal são {alvo} GB. " + igual[1])
    elif kit:
        s["recomendacoes"].append(f"Para {finalidade}, o ideal são {alvo} GB. " + kit[1])
        if igual:
            s["recomendacoes"].append(f"Opção mais barata ({igual[0]} GB): " + igual[1])
    elif igual:
        s["recomendacoes"].append(igual[1])
    else:
        s["recomendacoes"].append("A memória já está no máximo que este computador suporta.")

    if igual or kit:
        if ref["part_number"] and igual:
            s["recomendacoes"].append(
                f"Para o pente igual, o ideal é o mesmo modelo ({ref['part_number']}). Outra marca também serve, "
                "desde que tenha o mesmo tipo, formato, capacidade e frequência.")
        if velocidade and ref["velocidade_atual_mhz"] and ref["velocidade_atual_mhz"] < velocidade:
            s["recomendacoes"].append(
                f"O seu computador limita a memória a {ref['velocidade_atual_mhz']} MHz. Um pente de "
                f"{velocidade} MHz (igual ao atual) é o ideal, e um de {ref['velocidade_atual_mhz']} MHz "
                "também funciona sem perda. Não vale pagar mais por um pente mais rápido.")
    if livres is None:
        s["avisos"].append("O Windows não informou quantos slots existem. Confirme se há slot livre.")
    if hw["tipo"] in TIPOS_INTEGRADOS:
        s["avisos"].append(
            "Confira no manual do fabricante: em alguns notebooks parte da memória é soldada, e o Windows "
            "pode informar a quantidade de slots errada.")
    return s


# ---------------------------------------------------------------- armazenamento

def sugerir_armazenamento(hw, categorias, uso):
    s = _secao("Armazenamento (SSD/HD)")
    discos = hw["discos"]
    if not discos:
        s["avisos"].append("O Windows não informou os discos internos.")
        return s
    for d in discos:
        detalhes = " ".join(filter(None, [d["tipo"], d["barramento"]])) or "tipo desconhecido"
        s["instalado"].append(f"{d['nome']}: {d['tamanho_gb']} GB ({detalhes})")

    tem_ssd = any(d["tipo"] == "SSD" for d in discos)
    tem_nvme = any(d["barramento"] == "NVMe" for d in discos)
    total = sum(d["tamanho_gb"] for d in discos)
    alvo = ALVO_DISCO_GB[uso]
    finalidade = USOS[uso].lower()
    usa_nvme = tem_nvme or hw["tipo"] not in TIPOS_INTEGRADOS
    modelo_ssd = (f"SSD NVMe M.2 de {_tamanho(alvo)} (PCIe 4.0, que também funciona em slot PCIe 3.0)"
                  if usa_nvme else f"SSD SATA 2,5\" de {_tamanho(alvo)}")

    if not tem_ssd:
        s["recomendacoes"].append(
            f"Instalar um {modelo_ssd} para o sistema. É o upgrade que mais deixa o computador rápido.")
    elif total < alvo * 0.9:
        s["recomendacoes"].append(
            f"Para {finalidade}, o ideal é ter pelo menos {_tamanho(alvo)} (você tem {total} GB). Sugestão: "
            f"{modelo_ssd}, no lugar do atual (clonando o sistema) ou como segundo disco, se houver espaço.")
    else:
        s["recomendacoes"].append(f"Para {finalidade}, o espaço atual ({total} GB em SSD) é suficiente.")

    if usa_nvme and (not tem_ssd or total < alvo * 0.9):
        s["avisos"].append(
            "Antes de comprar, confira no manual o tamanho do slot M.2 (2230, 2242 ou 2280). O Windows não "
            "informa isso, nem se existe um slot livre.")
    return s


# ---------------------------------------------------------------- peças do catálogo (desktop)

def _uma_por_nivel(itens, uso):
    """A melhor opção de cada faixa, para o usuário escolher pelo orçamento."""
    linhas = []
    for nivel in NIVEIS:
        do_nivel = [i for i in itens if i["nivel"] == nivel]
        if do_nivel:
            melhor = max(do_nivel, key=lambda i: i["notas"][uso])
            linha = f"{NOMES_NIVEIS[nivel]}: {melhor['modelo']}"
            if melhor.get("observacao"):
                linha += f". {melhor['observacao']}"
            linhas.append(linha)
    return linhas


def _instalado_no_catalogo(categorias, categoria, nomes):
    return next((i for i in categorias[categoria]["itens"] if _ja_instalado(i["modelo"], nomes)), None)


def _melhores_que_o_atual(categorias, categoria, uso, nomes_instalados, **filtros):
    """Itens compatíveis, sem o instalado e sem nada mais fraco que ele para a finalidade."""
    r = recomendar(categorias, categoria, uso, quantidade=999, **filtros)
    atual = _instalado_no_catalogo(categorias, categoria, nomes_instalados)
    piso = atual["notas"][uso] if atual else -1
    return [i for i in r["recomendacoes"]
            if not _ja_instalado(i["modelo"], nomes_instalados) and i["notas"][uso] > piso]


def sugerir_processador(hw, categorias, uso):
    s = _secao("Processador")
    cpu = hw["cpu"]
    s["instalado"].append(
        f"{cpu['nome'] or 'desconhecido'}"
        + (f" | {cpu['nucleos']} núcleos / {cpu['threads']} threads" if cpu["nucleos"] else ""))
    if hw["tipo"] in TIPOS_INTEGRADOS:
        return _para_placa_mae(s, hw, "o processador vem soldado", "um processador melhor")

    socket = cpu["socket"].upper() if cpu["socket"].upper() in SOCKETS else None
    if not socket:
        s["avisos"].append(
            f"Socket informado pelo Windows: '{cpu['socket'] or 'vazio'}'. Ele não está no catálogo, então não "
            "dá para garantir a compatibilidade.")
        return s
    memoria = tipo_memoria_unico(hw)
    opcoes = _melhores_que_o_atual(categorias, "cpu", uso, cpu["nome"], socket=socket, memoria=memoria)
    if opcoes:
        s["recomendacoes"].append(f"Compatíveis com a sua placa-mãe ({socket}{', ' + memoria if memoria else ''}), "
                                  "a melhor opção de cada faixa:")
        s["recomendacoes"] += _uma_por_nivel(opcoes, uso)
        s["avisos"].append("Antes de trocar, atualize a BIOS e confira na lista de CPUs suportadas pelo fabricante da placa-mãe.")
    else:
        s["recomendacoes"].append("O seu processador já é o melhor do catálogo para esta placa-mãe e finalidade.")
    return s


def sugerir_video(hw, categorias, uso):
    s = _secao("Placa de vídeo")
    gpus = hw["gpus"]
    for g in gpus:
        s["instalado"].append(f"{g['nome']} ({'integrada' if g['integrada'] else 'dedicada'})")
    if not gpus:
        s["instalado"].append("Nenhuma identificada")
    if hw["tipo"] in TIPOS_INTEGRADOS:
        return _para_placa_mae(s, hw, "o vídeo vem integrado", "um vídeo melhor (ou dedicado)")
    if uso == "escritorio" and gpus:
        s["recomendacoes"].append("Para escritório, o vídeo atual é suficiente. Não precisa comprar placa de vídeo.")
        return s

    opcoes = _melhores_que_o_atual(categorias, "gpu", uso, " ".join(g["nome"] for g in gpus))
    if opcoes:
        s["recomendacoes"].append("Melhor opção de cada faixa:")
        s["recomendacoes"] += _uma_por_nivel(opcoes, uso)
        exigencias = sorted({i["fonte_minima_w"] for i in opcoes})
        s["avisos"].append(
            f"Cada placa exige uma fonte mínima ({exigencias[0]} a {exigencias[-1]} W). O Windows não informa a "
            "potência da sua fonte: confira na etiqueta dela, ou escolha \"Fonte\" para ver qual comprar junto.")
    else:
        s["recomendacoes"].append("A sua placa de vídeo já é a melhor do catálogo para esta finalidade.")
    return s


def _placa_mae_integrada(hw, uso):
    """Notebook/all-in-one: a placa só serve se for do mesmo modelo; o que importa é a referência para comprar."""
    s = _secao("Placa-mãe")
    ident = hw.get("identificacao", {})
    nome_pc = _nome_computador(hw)
    eh_dell = "dell" in hw["fabricante"].lower()

    s["instalado"].append(f"Modelo do {hw['tipo']}: {nome_pc}")
    if ident.get("placa_referencia"):
        ref = f"Referência da placa-mãe (part number): {ident['placa_referencia']}"
        if ident.get("placa_revisao"):
            ref += f" (revisão {ident['placa_revisao']})"
        s["instalado"].append(ref)
    else:
        s["instalado"].append("Referência da placa-mãe: não informada pelo Windows (veja a etiqueta na própria placa)")
    if hw["cpu"]["nome"]:
        s["instalado"].append(f"Processador atual (soldado na placa): {hw['cpu']['nome']}")
    tipo_mem = tipo_memoria_unico(hw)
    formatos = {m["formato"] for m in hw["memoria"]["modulos"] if m["formato"]}
    if tipo_mem:
        s["instalado"].append(f"Memória usada pela placa: {tipo_mem} {' / '.join(sorted(formatos))}".rstrip())
    if ident.get("numero_serie"):
        s["instalado"].append(f"Número de série{' (Service Tag)' if eh_dell else ''}: {ident['numero_serie']}")
    extras = [f"SKU: {ident['sku']}" if ident.get("sku") else "", f"BIOS: {ident['bios']}" if ident.get("bios") else ""]
    if any(extras):
        s["instalado"].append(" | ".join(filter(None, extras)))

    linha_atual, superiores = _linhas_superiores(hw["cpu"]["nome"])
    if uso == "escritorio" and linha_atual and linha_atual[-1] in "579":
        s["recomendacoes"].append(
            f"Para escritório, o {linha_atual} atual normalmente basta. Só vale trocar a placa se houver lentidão.")
    if superiores:
        s["recomendacoes"].append(
            f"Para um processador melhor, procure a placa-mãe do {nome_pc} na versão com {superiores[0]} "
            f"(a sua é {linha_atual}).")
        s["recomendacoes"].append(f"Termo de busca: \"placa mãe {nome_pc} {superiores[0]}\".")
    elif linha_atual:
        s["recomendacoes"].append(
            f"O seu processador ({linha_atual}) já é da linha mais alta. Trocar a placa só compensa se o "
            f"{nome_pc} tiver versão de geração mais nova.")
    else:
        s["recomendacoes"].append(
            f"Procure a placa-mãe do {nome_pc} na versão com o processador desejado.")
    if uso in ("jogos", "edicao"):
        s["recomendacoes"].append(
            "Se este modelo teve versão com placa de vídeo dedicada, prefira essa placa: para jogos e edição, o "
            "vídeo dedicado faz mais diferença que o processador. Ela pode exigir outro dissipador (cooler).")
    if ident.get("placa_referencia"):
        s["recomendacoes"].append(
            f"Ao comprar, informe ao vendedor o modelo ({nome_pc}) e a referência atual "
            f"({ident['placa_referencia']}). A placa nova terá outra referência, e o vendedor precisa confirmar "
            "que ela é compatível com este modelo.")

    s["avisos"].append(
        f"A placa nova precisa ser do mesmo modelo de {hw['tipo']} ({nome_pc}): o encaixe no gabinete, os "
        "conectores de tela, teclado e bateria e a BIOS são específicos de cada modelo.")
    if tipo_mem:
        s["avisos"].append(
            f"Confirme que a placa nova usa a mesma memória ({tipo_mem} {' / '.join(sorted(formatos))}) para "
            "reaproveitar seus pentes. Algumas versões vêm com a memória soldada.")
    if ident.get("numero_serie"):
        s["avisos"].append(
            f"O suporte do fabricante consegue informar as placas compatíveis pelo número de série "
            f"({ident['numero_serie']}).")
    s["avisos"].append(
        "A troca de placa-mãe de notebook exige desmontar o aparelho inteiro. Se não tiver experiência, "
        "procure uma assistência técnica.")
    return s


def sugerir_placa_mae(hw, categorias, uso):
    if hw["tipo"] in TIPOS_INTEGRADOS:
        return _placa_mae_integrada(hw, uso)
    s = _secao("Placa-mãe")
    s["instalado"].append(hw["placa_mae"] or "desconhecida")
    socket = hw["cpu"]["socket"].upper()
    memoria = tipo_memoria_unico(hw)
    if socket not in SOCKETS:
        s["avisos"].append("Não foi possível identificar o socket do processador para garantir a compatibilidade.")
        return s
    opcoes = recomendar(categorias, "placa_mae", uso, socket=socket, memoria=memoria, quantidade=999)["recomendacoes"]
    if opcoes:
        s["recomendacoes"].append(
            f"Para reaproveitar seu processador ({socket}) e sua memória ({memoria or 'mesmo tipo'}), "
            "a melhor opção de cada faixa:")
        s["recomendacoes"] += _uma_por_nivel(opcoes, uso)
    else:
        s["recomendacoes"].append(f"Nenhuma placa-mãe do catálogo aceita ao mesmo tempo {socket} e {memoria}.")
    return s


def _potencia(item):
    achado = re.search(r"(\d+)\s*W", item["modelo"])
    return int(achado.group(1)) if achado else 0


def sugerir_fonte(hw, categorias, uso):
    s = _secao("Fonte de alimentação")
    if hw["tipo"] in TIPOS_INTEGRADOS:
        s["recomendacoes"].append(f"Em {hw['tipo']} não há fonte interna para trocar (usa carregador próprio).")
        return s
    s["instalado"].append("Potência não informada pelo Windows (confira na etiqueta da fonte)")

    gpu = _instalado_no_catalogo(categorias, "gpu", " ".join(g["nome"] for g in hw["gpus"]))
    minimo = gpu["fonte_minima_w"] if gpu else 0
    itens = [i for i in categorias["fonte"]["itens"] if _potencia(i) >= minimo]
    if gpu:
        s["recomendacoes"].append(f"Sua placa de vídeo ({gpu['modelo']}) pede no mínimo {minimo} W.")
    s["recomendacoes"].append("Melhor opção de cada faixa:")
    s["recomendacoes"] += _uma_por_nivel(itens, uso)
    s["avisos"].append("Se for trocar também a placa de vídeo, escolha a fonte pela exigência da placa nova.")
    return s


PECAS = {
    "memoria": ("Memória RAM", sugerir_memoria),
    "armazenamento": ("Armazenamento (SSD/HD)", sugerir_armazenamento),
    "processador": ("Processador", sugerir_processador),
    "video": ("Placa de vídeo", sugerir_video),
    "placa_mae": ("Placa-mãe", sugerir_placa_mae),
    "fonte": ("Fonte de alimentação", sugerir_fonte),
}


def recomendar_peca(hw, categorias, peca, uso):
    if peca not in PECAS:
        raise KeyError(f"Peça desconhecida: {peca}")
    if uso not in USOS:
        raise KeyError(f"Finalidade desconhecida: {uso}")
    return PECAS[peca][1](hw, categorias, uso)
