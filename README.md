# Qual peça comprar?

Programa para Windows que lê as peças do computador e recomenda o upgrade compatível.
O usuário escolhe só **a peça** e **a finalidade** (jogos, escritório ou edição); notebook/desktop,
tipo de memória, socket e slots são detectados automaticamente.

## Como rodar

```
pip install -r requirements.txt
python app.py
```

Requer Windows (a leitura do hardware usa WMI via PowerShell) e Python 3.10+.

## Arquivos

| Arquivo | Função |
|---|---|
| `app.py` | Janela (PySide6 + PyQt-Fluent-Widgets) |
| `scanner.py` | Lê o hardware pelo Windows |
| `upgrade.py` | Transforma o hardware detectado em recomendações |
| `recomendador.py` | Filtra e ordena os modelos do catálogo |
| `dados/catalogo.json` | Catálogo de modelos (editável) |

## Testes

```
python -m unittest
```

## Observações

- As notas 0–10 do catálogo são estimativas relativas, não benchmarks; especificações conferidas até 2025.
- O Windows não informa o tamanho do slot M.2, slots livres de SSD nem a potência da fonte: o programa avisa para conferir.
- A interface usa PyQt-Fluent-Widgets (GPLv3): uso interno é livre; distribuir para terceiros exige liberar o código sob GPL ou licença comercial do autor.
