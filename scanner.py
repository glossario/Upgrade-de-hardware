"""Lê o hardware deste computador pelo Windows (WMI/CIM) e organiza os dados.

`ler_hardware_bruto()` chama o PowerShell; `interpretar()` só transforma o JSON,
por isso pode ser testada sem depender da máquina.
"""
import json
import re
import subprocess

SCRIPT_POWERSHELL = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$r = [ordered]@{
  sistema  = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, PCSystemType, SystemSKUNumber
  bios     = Get-CimInstance Win32_BIOS | Select-Object SerialNumber, SMBIOSBIOSVersion
  memorias = @(Get-CimInstance Win32_PhysicalMemory | Select-Object Manufacturer, PartNumber, Capacity, Speed,
                 ConfiguredClockSpeed, SMBIOSMemoryType, MemoryType, FormFactor, DeviceLocator)
  slots    = @(Get-CimInstance Win32_PhysicalMemoryArray | Where-Object { $_.Use -eq 3 } |
                 Select-Object MemoryDevices, MaxCapacity, MaxCapacityEx)
  cpu      = @(Get-CimInstance Win32_Processor | Select-Object Name, SocketDesignation, NumberOfCores, NumberOfLogicalProcessors)
  gpus     = @(Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM)
  discos   = @(Get-PhysicalDisk | Select-Object FriendlyName, @{n='MediaType';e={[string]$_.MediaType}},
                 @{n='BusType';e={[string]$_.BusType}}, Size)
  placa    = Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer, Product, Version
  baterias = @(Get-CimInstance Win32_Battery).Count
  gabinete = @((Get-CimInstance Win32_SystemEnclosure).ChassisTypes)
}
$r | ConvertTo-Json -Depth 4 -Compress
"""

# Códigos SMBIOS de tipo de memória (Win32_PhysicalMemory.SMBIOSMemoryType)
TIPOS_MEMORIA = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 29: "LPDDR3",
                 30: "LPDDR4", 34: "DDR5", 35: "LPDDR5"}
# Win32_PhysicalMemory.FormFactor
FORMATOS_MEMORIA = {8: "DIMM", 12: "SO-DIMM", 7: "soldada"}
# Win32_SystemEnclosure.ChassisTypes (tabela SMBIOS de gabinetes)
TIPOS_GABINETE = {
    **dict.fromkeys([8, 9, 10, 11, 14, 30, 31, 32], "notebook"),  # portátil, laptop, notebook, conversível...
    **dict.fromkeys([3, 4, 5, 6, 7, 15, 16, 24, 35, 36], "desktop"),  # desktop, torre, mini PC...
    13: "all-in-one",
}
# Win32_ComputerSystem.PCSystemType: 2 = móvel
TIPOS_SISTEMA = {1: "desktop", 2: "notebook", 3: "desktop"}

_GPU_IGNORAR = re.compile(r"basic|virtual|remote|displaylink|citrix|parsec|meta", re.I)
_GPU_INTEGRADA = re.compile(
    r"intel.*(uhd|hd graphics|iris|intel\(r\) graphics|arc\(tm\) graphics)|radeon\(tm\) graphics|radeon graphics|vega", re.I)

GIB = 1024 ** 3


class FalhaLeitura(RuntimeError):
    pass


def ler_hardware_bruto(timeout=90):
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", SCRIPT_POWERSHELL],
            capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as e:
        raise FalhaLeitura("PowerShell não encontrado. Este programa funciona apenas no Windows.") from e
    except subprocess.TimeoutExpired as e:
        raise FalhaLeitura("A leitura do hardware demorou demais.") from e

    saida = proc.stdout.decode("utf-8", errors="replace").strip()
    if not saida:
        erro = proc.stderr.decode("utf-8", errors="replace").strip()
        raise FalhaLeitura(f"O Windows não devolveu dados do hardware. {erro}".strip())
    try:
        return json.loads(saida)
    except json.JSONDecodeError as e:
        raise FalhaLeitura("Resposta do Windows em formato inesperado.") from e


def _lista(valor):
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def _texto(valor):
    return str(valor).strip() if valor not in (None, "") else ""


# Valores de preenchimento que alguns fabricantes deixam na BIOS no lugar da informação real
_SEM_INFORMACAO = re.compile(r"^(to be filled by o\.?e\.?m\.?|default string|system (serial|sku) number|"
                             r"not (applicable|specified)|none|n/?a|0+|x+)$", re.I)


def _identificacao(valor):
    texto = _texto(valor)
    return "" if _SEM_INFORMACAO.match(texto) else texto


def _int(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


def _memoria(bruto):
    modulos = []
    for m in _lista(bruto.get("memorias")):
        codigo = _int(m.get("SMBIOSMemoryType")) or _int(m.get("MemoryType"))
        modulos.append({
            "slot": _texto(m.get("DeviceLocator")) or "?",
            "capacidade_gb": round(_int(m.get("Capacity")) / GIB),
            "tipo": TIPOS_MEMORIA.get(codigo),
            "formato": FORMATOS_MEMORIA.get(_int(m.get("FormFactor"))),
            "velocidade_mhz": _int(m.get("Speed")) or None,
            "velocidade_atual_mhz": _int(m.get("ConfiguredClockSpeed")) or None,
            "part_number": _texto(m.get("PartNumber")),
        })

    arrays = _lista(bruto.get("slots"))
    slots = sum(_int(a.get("MemoryDevices")) for a in arrays) or None
    # MaxCapacity(Ex) vem em KB
    max_kb = sum(_int(a.get("MaxCapacityEx")) or _int(a.get("MaxCapacity")) for a in arrays)
    max_gb = round(max_kb / 1024 ** 2) or None
    return {"modulos": modulos, "slots_total": slots, "max_gb": max_gb}


def _gpus(bruto):
    gpus = []
    for g in _lista(bruto.get("gpus")):
        nome = _texto(g.get("Name"))
        if not nome or _GPU_IGNORAR.search(nome):
            continue
        gpus.append({"nome": nome, "integrada": bool(_GPU_INTEGRADA.search(nome))})
    return gpus


def _discos(bruto):
    discos = []
    for d in _lista(bruto.get("discos")):
        midia = _texto(d.get("MediaType"))
        discos.append({
            "nome": _texto(d.get("FriendlyName")) or "Disco",
            "tipo": {"SSD": "SSD", "HDD": "HD", "4": "SSD", "3": "HD"}.get(midia),
            "barramento": {"17": "NVMe", "11": "SATA", "7": "USB"}.get(_texto(d.get("BusType")),
                                                                        _texto(d.get("BusType")) or None),
            "tamanho_gb": round(_int(d.get("Size")) / 1000 ** 3),
        })
    # Discos externos (USB) não fazem parte do upgrade interno
    return [d for d in discos if d["barramento"] != "USB"]


def _tipo_computador(bruto, memoria):
    """Decide notebook/desktop pela evidência mais confiável disponível; devolve (tipo, como_identificou)."""
    for codigo in _lista(bruto.get("gabinete")):
        if _int(codigo) in TIPOS_GABINETE:
            return TIPOS_GABINETE[_int(codigo)], "tipo de gabinete informado pela BIOS"
    tipo = TIPOS_SISTEMA.get(_int((bruto.get("sistema") or {}).get("PCSystemType")))
    if tipo:
        return tipo, "tipo de sistema informado pelo Windows"
    if _int(bruto.get("baterias")) > 0:
        return "notebook", "presença de bateria"
    if any(m["formato"] == "SO-DIMM" for m in memoria["modulos"]):
        return "notebook", "memória no formato de notebook (SO-DIMM)"
    return "desconhecido", "não foi possível identificar"


def interpretar(bruto):
    sistema = bruto.get("sistema") or {}
    memoria = _memoria(bruto)
    tipo, origem_tipo = _tipo_computador(bruto, memoria)

    cpus = _lista(bruto.get("cpu"))
    cpu = cpus[0] if cpus else {}
    placa = bruto.get("placa") or {}
    bios = bruto.get("bios") or {}

    return {
        "tipo": tipo,
        "origem_tipo": origem_tipo,
        "fabricante": _texto(sistema.get("Manufacturer")),
        "modelo": _texto(sistema.get("Model")),
        "placa_mae": " ".join(filter(None, [_texto(placa.get("Manufacturer")), _texto(placa.get("Product"))])),
        # Identificações usadas para comprar peça de reposição (ex.: placa-mãe de notebook)
        "identificacao": {
            "placa_fabricante": _identificacao(placa.get("Manufacturer")),
            "placa_referencia": _identificacao(placa.get("Product")),
            "placa_revisao": _identificacao(placa.get("Version")),
            "numero_serie": _identificacao(bios.get("SerialNumber")),
            "sku": _identificacao(sistema.get("SystemSKUNumber")),
            "bios": _identificacao(bios.get("SMBIOSBIOSVersion")),
        },
        "cpu": {
            "nome": re.sub(r"\s+", " ", _texto(cpu.get("Name"))),
            "socket": _texto(cpu.get("SocketDesignation")),
            "nucleos": _int(cpu.get("NumberOfCores")) or None,
            "threads": _int(cpu.get("NumberOfLogicalProcessors")) or None,
        },
        "memoria": memoria,
        "gpus": _gpus(bruto),
        "discos": _discos(bruto),
    }


def escanear():
    return interpretar(ler_hardware_bruto())
