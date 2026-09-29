"""Analisa o lote piloto de `.eml` e produz evidência para decidir mudanças.

Responde às cinco perguntas que o lote piloto existe para responder:

    1. os campos atuais são suficientes?
    2. quais pendências aparecem com mais frequência?
    3. a anonimização removeu informação demais ou de menos?
    4. algum tipo de mensagem real não foi tratado corretamente?
    5. quais campos precisam de lista controlada na planilha de curadoria?

Este script **não altera nada** — nem schema, nem validador, nem protocolo, nem
a própria fila. Ele só observa e registra, porque a ordem combinada é: primeiro
evidência, depois decisão.

A seção de anonimização merece atenção: ela aponta *suspeitas* de dado pessoal
remanescente usando heurísticas propositalmente amplas. Falso positivo aqui é
barato; falso negativo é vazamento. Toda suspeita vai para conferência humana,
nenhuma vira ação automática.

Uso (a partir de ml/):
    python -m src.corpus.analisar_piloto
"""
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

from src.features.url_features import MARCAS

ML_DIR = Path(__file__).resolve().parents[2]
FILA = ML_DIR / "data" / "ptbr" / "processed_private" / "fila_curadoria.csv"
RELATORIO = ML_DIR / "reports" / "PILOTO_REPORT.md"

MARCADOR_RE = re.compile(r"<(?:EMAIL|TEL|CPF|CNPJ|CEP|CARTAO|NOME|PARAM)>")

# Heurísticas de dado pessoal que pode ter escapado. Amplas de propósito.
RESIDUAL = {
    "saudacao_com_nome": re.compile(
        r"\b(?:prezad[oa]|car[oa]|ol[áa]|bom dia|boa tarde|boa noite)[, ]+"
        r"([A-ZÁ-Ú][a-zá-ú]{2,}(?:\s+[A-ZÁ-Ú][a-zá-ú]{2,})+)"),
    "agencia_conta": re.compile(
        r"\b(?:ag(?:[êe]ncia)?\.?\s*\d{3,5}[\s/-]*(?:c(?:onta)?\.?\s*)?\d{4,})\b",
        re.IGNORECASE),
    "chave_pix_aleatoria": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
    "endereco": re.compile(
        r"\b(?:rua|av\.?|avenida|travessa|alameda|rodovia)\s+[A-ZÁ-Ú][\w\sá-ú.]{4,40},?\s*\d+",
        re.IGNORECASE),
    "rg": re.compile(r"\bRG[:\s]*\d{1,2}\.?\d{3}\.?\d{3}-?[\dxX]\b"),
    "data_nascimento": re.compile(
        r"\b(?:nascimento|nasc\.?)[:\s]*\d{2}/\d{2}/\d{4}\b", re.IGNORECASE),
    "numero_pedido_longo": re.compile(r"\b(?:pedido|protocolo|nº|no\.)\s*[:#]?\s*\w{10,}\b",
                                      re.IGNORECASE),
    "cpf_parcial_mascarado": re.compile(r"\*{3}\.?\d{3}\.?\d{3}-?\*{2}"),
}


def carregar(caminho: Path) -> list[dict]:
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _marcas_citadas(texto: str) -> set[str]:
    baixo = texto.lower()
    return {
        m for m in MARCAS
        if re.search(rf"(?<![0-9a-zà-ú]){re.escape(m)}(?![0-9a-zà-ú])", baixo)
    }


def inventario(reg: list[dict]) -> list[str]:
    tipos = Counter(r["tipo_corpo"] for r in reg)
    erros = [r for r in reg if r["parse_erro"]]
    anexos = sum(int(r["n_anexos"] or 0) for r in reg)
    tamanhos = sorted(int(r["n_caracteres"] or 0) for r in reg)
    mediana = tamanhos[len(tamanhos) // 2] if tamanhos else 0

    linhas = [
        "## 1. Inventário do lote",
        "",
        f"- registros processados: **{len(reg)}**",
        f"- erros de parsing: **{len(erros)}**",
        f"- anexos ignorados: **{anexos}**",
        f"- comprimento do texto: mínimo {tamanhos[0] if tamanhos else 0}, "
        f"mediana {mediana}, máximo {tamanhos[-1] if tamanhos else 0} caracteres",
        "",
        "| tipo de corpo | registros |",
        "|---|---:|",
    ]
    linhas += [f"| {t} | {n} |" for t, n in tipos.most_common()]
    if erros:
        linhas += ["", "**Erros de parsing:**", ""]
        linhas += [f"- `{r['id']}`: {r['parse_erro']}" for r in erros]
    return linhas + [""]


def pendencias(reg: list[dict]) -> list[str]:
    contagem = Counter()
    for r in reg:
        for p in filter(None, (r.get("pendencias") or "").split(",")):
            contagem[p] += 1

    linhas = [
        "## 2. Pendências de curadoria",
        "",
        "Frequência com que cada campo ficou em aberto. Campo pendente em 100% "
        "dos registros é candidato natural a lista controlada na planilha.",
        "",
        "| campo | pendente em | % |",
        "|---|---:|---:|",
    ]
    for campo, n in contagem.most_common():
        linhas.append(f"| `{campo}` | {n} | {n / len(reg) * 100:.0f}% |")
    return linhas + [""]


def anonimizacao(reg: list[dict]) -> list[str]:
    categorias = Counter()
    for r in reg:
        for c in filter(None, (r["categorias_anonimizadas"] or "").split(",")):
            categorias[c] += 1

    sem_nenhuma = [r for r in reg if not r["categorias_anonimizadas"]]

    # Excesso: quanto do texto virou marcador.
    excessivos = []
    for r in reg:
        texto = r["texto"] or ""
        if not texto:
            continue
        marcados = sum(len(m.group()) for m in MARCADOR_RE.finditer(texto))
        prop = marcados / len(texto)
        if prop > 0.15:
            excessivos.append((r["id"], prop, len(texto)))

    # Falta: padrões que podem ter escapado.
    suspeitas: dict[str, list[tuple[str, str]]] = {}
    for r in reg:
        for nome, padrao in RESIDUAL.items():
            for m in padrao.finditer(r["texto"] or ""):
                trecho = m.group(0)[:60]
                suspeitas.setdefault(nome, []).append((r["id"], trecho))

    linhas = [
        "## 3. Auditoria da anonimização",
        "",
        "### Categorias detectadas e mascaradas",
        "",
        "| categoria | registros |",
        "|---|---:|",
    ]
    linhas += [f"| {c} | {n} |" for c, n in categorias.most_common()]
    linhas += [
        "",
        f"Registros sem nenhum dado pessoal detectado: **{len(sem_nenhuma)}** "
        f"de {len(reg)}.",
        "",
        "### Mascaramento excessivo",
        "",
    ]
    if excessivos:
        linhas += [
            "Registros em que mais de 15% do texto virou marcador — verificar se "
            "sobrou conteúdo suficiente para curadoria e treino:",
            "",
            "| id | proporção mascarada | caracteres |",
            "|---|---:|---:|",
        ]
        linhas += [f"| `{i}` | {p * 100:.0f}% | {n} |" for i, p, n in
                   sorted(excessivos, key=lambda x: -x[1])]
    else:
        linhas.append("Nenhum registro passou de 15% do texto mascarado.")

    linhas += ["", "### Suspeitas de dado pessoal remanescente", ""]
    if suspeitas:
        linhas += [
            "Heurísticas amplas — falso positivo aqui é esperado e barato. "
            "**Toda linha exige conferência humana no `.eml` bruto**; nenhuma "
            "gera ação automática.",
            "",
            "| heurística | ocorrências | exemplo (do texto já anonimizado) |",
            "|---|---:|---|",
        ]
        for nome, achados in sorted(suspeitas.items(), key=lambda x: -len(x[1])):
            exemplo = achados[0][1].replace("|", "\\|")
            linhas.append(f"| `{nome}` | {len(achados)} | `{exemplo}` |")
        linhas += ["", "**Detalhe por registro:**", ""]
        for nome, achados in sorted(suspeitas.items()):
            for rid, trecho in achados[:8]:
                linhas.append(f"- `{nome}` em `{rid}`: `{trecho}`")
    else:
        linhas.append("Nenhuma suspeita levantada pelas heurísticas atuais.")
    return linhas + [""]


def anomalias(reg: list[dict]) -> list[str]:
    vazios = [r for r in reg if not (r["texto"] or "").strip()]
    curtos = [r for r in reg if 0 < len(r["texto"] or "") < 40]
    longos = [r for r in reg if len(r["texto"] or "") > 20000]
    so_html = [r for r in reg if r["tipo_corpo"] == "html"]
    sem_assunto = [r for r in reg if not (r["assunto"] or "").strip()]
    sem_dominio = [r for r in reg if not r["remetente_dominio_hash"]]

    linhas = ["## 4. Tipos de mensagem que podem não ter sido tratados", "",
              "| situação | registros | o que investigar |", "|---|---:|---|"]
    for rotulo, itens, nota in [
        ("texto vazio após parsing", vazios,
         "corpo só em imagem, ou formato não coberto"),
        ("texto com menos de 40 caracteres", curtos,
         "pode ser corpo em imagem ou parsing parcial"),
        ("texto acima de 20 mil caracteres", longos,
         "thread longa ou assinatura repetida — avaliar truncamento"),
        ("somente HTML", so_html,
         "conversão pode ter perdido estrutura de tabela ou botão"),
        ("sem assunto", sem_assunto, "verificar se o cabeçalho existia"),
        ("sem domínio de remetente", sem_dominio, "cabeçalho From ausente ou malformado"),
    ]:
        linhas.append(f"| {rotulo} | {len(itens)} | {nota} |")

    detalhe = []
    for rotulo, itens in [("vazio", vazios), ("curto", curtos), ("longo", longos)]:
        for r in itens[:5]:
            detalhe.append(f"- {rotulo}: `{r['id']}` "
                           f"({r['n_caracteres']} car., tipo `{r['tipo_corpo']}`)")
    if detalhe:
        linhas += ["", "**Registros a inspecionar:**", ""] + detalhe
    return linhas + [""]


def listas_controladas(reg: list[dict]) -> list[str]:
    marcas = Counter()
    for r in reg:
        for m in _marcas_citadas(f"{r['assunto']} {r['texto']}"):
            marcas[m] += 1

    dominios = Counter(r["remetente_dominio_hash"] for r in reg if r["remetente_dominio_hash"])
    repetidos = {d: n for d, n in dominios.items() if n > 1}

    linhas = [
        "## 5. Insumos para as listas controladas da planilha",
        "",
        "### Marcas observadas no lote",
        "",
        "Detectadas por correspondência de palavra contra a lista de marcas já "
        "usada pelo módulo de URL. Indica quais entradas o campo `marca` "
        "precisa oferecer de fato.",
        "",
    ]
    if marcas:
        linhas += ["| marca | registros |", "|---|---:|"]
        linhas += [f"| {m} | {n} |" for m, n in marcas.most_common()]
        ausentes = "nenhuma"
        linhas += ["", f"Marcas da lista que não apareceram no lote: verificar se "
                       f"o lote é representativo ({len(MARCAS) - len(marcas)} de "
                       f"{len(MARCAS)} não vistas)."]
    else:
        linhas.append("Nenhuma marca conhecida detectada — lote pequeno ou "
                      "vocabulário de marcas insuficiente.")

    linhas += [
        "",
        "### Remetentes repetidos",
        "",
        f"{len(repetidos)} domínio(s) de remetente aparecem em mais de um "
        f"registro. Domínio repetido é indício de campanha — insumo para "
        "`grupo_campanha` na curadoria.",
        "",
    ]
    if repetidos:
        linhas += ["| hash do domínio | registros |", "|---|---:|"]
        linhas += [f"| `{d}` | {n} |" for d, n in
                   sorted(repetidos.items(), key=lambda x: -x[1])]
    return linhas + [""]


def main() -> int:
    p = argparse.ArgumentParser(description="Analisa o lote piloto de .eml.")
    p.add_argument("--fila", type=Path, default=FILA)
    a = p.parse_args()

    if not a.fila.exists():
        print(f"ERRO: fila nao encontrada: {a.fila}", file=sys.stderr)
        print("Rode primeiro: python -m src.corpus.eml_parser", file=sys.stderr)
        return 2

    reg = carregar(a.fila)
    if not reg:
        print("fila vazia", file=sys.stderr)
        return 2

    linhas = [
        "# Lote piloto — evidência para decisão",
        "",
        f"> Gerado por `src/corpus/analisar_piloto.py` sobre `{a.fila.name}`.",
        "> Este relatório **não decide nada**: registra o que o lote mostrou, "
        "para que mudanças de schema ou protocolo sejam discutidas com base em "
        "evidência.",
        "",
    ]
    linhas += inventario(reg)
    linhas += pendencias(reg)
    linhas += anonimizacao(reg)
    linhas += anomalias(reg)
    linhas += listas_controladas(reg)

    RELATORIO.parent.mkdir(parents=True, exist_ok=True)
    RELATORIO.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    print(f"registros analisados: {len(reg)}")
    print(f"relatorio: {RELATORIO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
