"""Análise exploratória (EDA) do corpus consolidado — Fase 3 (planejamento_tg.md §10).

Responde, com número e gráfico, às perguntas que a banca faz sobre a base antes
de qualquer treino:

  1. Quantos registros por fonte e por classe? (viés de fonte)
  2. Qual o balanceamento ham/spam? (§5.2 — acurácia é métrica enganosa aqui)
  3. Como varia o comprimento do texto por fonte e por classe? (viés de comprimento)
  4. Quantos registros ficaram vazios ou com erro de parsing?
  5. Quantas duplicatas aproximadas sobraram depois da dedupe exata?
  6. O corpus é mesmo 100% inglês? (lacuna PT-BR — contribuição do TG)
  7. Quais termos mais separam spam de ham?

Lê `email_dataset_v1_parsed.parquet` em dois passes porque a base não cabe na
memória disponível: primeiro as colunas numéricas/categóricas (baratas), depois
o texto em lotes via pyarrow, sem nunca materializar as 782 mil linhas de corpo.

Uso (a partir de ml/):
    python -m src.eda.run_eda
"""
import hashlib
import random
import re
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sem display: salva PNG direto

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ML_DIR = Path(__file__).resolve().parents[2]
PARQUET = ML_DIR / "data" / "processed" / "email_dataset_v1_parsed.parquet"
FIG_DIR = ML_DIR / "reports" / "figures"
REPORT = ML_DIR / "reports" / "EDA_REPORT.md"

# Colunas leves: cabem na memória inteiras (782k x 8, sem texto).
LIGHT_COLS = [
    "source",
    "channel",
    "raw_label",
    "char_count",
    "links_count",
    "attachments_count",
    "parse_error",
]

SAMPLE_SIZE = 8_000  # amostra para idioma e termos discriminativos
BATCH_ROWS = 20_000  # lote do pass 2 — limita o pico de memória do texto

TOKEN_RE = re.compile(r"[a-zá-úà-ùâ-ûã-õç]{3,}")
WS_RE = re.compile(r"\s+")

# Palavras estruturais que aparecem em qualquer texto e não discriminam nada.
STOPWORDS = {
    "the", "and", "for", "you", "that", "this", "with", "have", "from", "not",
    "are", "was", "will", "your", "can", "all", "has", "but", "our", "they",
    "out", "one", "get", "her", "his", "она", "com", "www", "http", "https",
    "any", "more", "been", "were", "would", "there", "their", "what", "when",
    "which", "about", "into", "also", "than", "them", "then", "some", "only",
    "such", "other", "over", "just", "like", "new", "who", "how", "its",
}


# ---------------------------------------------------------------- pass 1


def carregar_colunas_leves() -> pd.DataFrame:
    df = pd.read_parquet(PARQUET, columns=LIGHT_COLS)
    # `parse_error` vem como bool nullable em algumas linhas; normaliza.
    df["parse_error"] = df["parse_error"].fillna(False).astype(bool)
    return df


def tabela_fonte_rotulo(df: pd.DataFrame) -> pd.DataFrame:
    t = df.groupby(["source", "raw_label"]).size().unstack(fill_value=0)
    for col in ("ham", "spam"):
        if col not in t.columns:
            t[col] = 0
    t = t[["ham", "spam"]]
    t["total"] = t.sum(axis=1)
    t["%_da_base"] = (t["total"] / t["total"].sum() * 100).round(1)
    t["%_spam_na_fonte"] = (t["spam"] / t["total"] * 100).round(1)
    return t.sort_values("total", ascending=False)


def estatisticas_comprimento(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["source", "raw_label"])["char_count"]
    return pd.DataFrame(
        {
            "n": g.size(),
            "mediana": g.median().round(0),
            "media": g.mean().round(0),
            "p90": g.quantile(0.90).round(0),
        }
    )


# ---------------------------------------------------------------- pass 2


def varrer_texto() -> dict:
    """Passa o corpo em lotes: conta duplicatas normalizadas, vazios e amostra.

    A dedupe do consolidate_raw.py foi por texto exato. Aqui a chave é o texto
    normalizado (minúsculo, espaços colapsados), que pega as cópias que diferem
    só em formatação — as que inflam a base sem trazer informação nova.
    """
    arquivo = pq.ParquetFile(PARQUET)
    vistos: set[bytes] = set()
    duplicatas = 0
    vazios = 0
    total = 0
    # Onde estão as duplicatas: decide quanto dá para amostrar de cada fonte.
    por_fonte: Counter = Counter()
    dup_por_fonte: Counter = Counter()
    amostra: list[tuple[str, str]] = []  # (rótulo, texto)
    rng = random.Random(42)

    for lote in arquivo.iter_batches(
        batch_size=BATCH_ROWS, columns=["source", "raw_label", "subject", "body_text"]
    ):
        fontes = lote.column("source").to_pylist()
        rotulos = lote.column("raw_label").to_pylist()
        assuntos = lote.column("subject").to_pylist()
        corpos = lote.column("body_text").to_pylist()

        for fonte, rotulo, assunto, corpo in zip(fontes, rotulos, assuntos, corpos):
            total += 1
            por_fonte[fonte] += 1
            texto = f"{assunto or ''} {corpo or ''}".strip()
            if not texto:
                vazios += 1
                continue

            chave = hashlib.sha1(WS_RE.sub(" ", texto.lower()).encode("utf-8")).digest()
            if chave in vistos:
                duplicatas += 1
                dup_por_fonte[fonte] += 1
            else:
                vistos.add(chave)

            # Amostragem por reservatório: amostra uniforme sem guardar tudo.
            if len(amostra) < SAMPLE_SIZE:
                amostra.append((rotulo, texto[:3000]))
            else:
                j = rng.randrange(total)
                if j < SAMPLE_SIZE:
                    amostra[j] = (rotulo, texto[:3000])

    tabela_dup = pd.DataFrame(
        {
            "registros": pd.Series(por_fonte),
            "duplicatas": pd.Series(dup_por_fonte),
        }
    ).fillna(0).astype(int)
    tabela_dup["%_duplicado"] = (
        tabela_dup["duplicatas"] / tabela_dup["registros"] * 100
    ).round(1)
    tabela_dup["unicos"] = tabela_dup["registros"] - tabela_dup["duplicatas"]

    return {
        "total": total,
        "vazios": vazios,
        "duplicatas_normalizadas": duplicatas,
        "unicos": len(vistos),
        "dup_por_fonte": tabela_dup.sort_values("registros", ascending=False),
        "amostra": amostra,
    }


def detectar_idioma(amostra: list[tuple[str, str]]) -> Counter:
    from langdetect import DetectorFactory, LangDetectException, detect

    DetectorFactory.seed = 0
    contagem: Counter = Counter()
    for _, texto in amostra:
        try:
            contagem[detect(texto[:1000])] += 1
        except LangDetectException:
            contagem["indeterminado"] += 1
    return contagem


def termos_discriminativos(amostra: list[tuple[str, str]], n: int = 15) -> pd.DataFrame:
    """Log-odds de cada termo entre spam e ham, com suavização de Laplace.

    Mede o quanto um termo puxa para spam em vez de só listar os mais frequentes
    (que seriam palavras comuns em qualquer e-mail).
    """
    freq = {"ham": Counter(), "spam": Counter()}
    for rotulo, texto in amostra:
        if rotulo not in freq:
            continue
        tokens = set(TOKEN_RE.findall(texto.lower())) - STOPWORDS
        freq[rotulo].update(tokens)

    n_ham = sum(1 for r, _ in amostra if r == "ham")
    n_spam = sum(1 for r, _ in amostra if r == "spam")
    if not n_ham or not n_spam:
        return pd.DataFrame()

    candidatos = {t for t, c in freq["spam"].items() if c >= 20}
    candidatos |= {t for t, c in freq["ham"].items() if c >= 20}

    linhas = []
    for termo in candidatos:
        p_spam = (freq["spam"][termo] + 1) / (n_spam + 2)
        p_ham = (freq["ham"][termo] + 1) / (n_ham + 2)
        linhas.append(
            {
                "termo": termo,
                "log_odds": np.log(p_spam / p_ham),
                "doc_spam": freq["spam"][termo],
                "doc_ham": freq["ham"][termo],
            }
        )

    df = pd.DataFrame(linhas).sort_values("log_odds", ascending=False)
    return pd.concat([df.head(n), df.tail(n)])


# ---------------------------------------------------------------- gráficos


def _salvar(fig, nome: str) -> str:
    caminho = FIG_DIR / nome
    fig.savefig(caminho, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  figura: {caminho.name}")
    return nome


def grafico_fonte_rotulo(tabela: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(9, 5))
    t = tabela.sort_values("total")
    ax.barh(t.index, t["ham"], label="ham (legítimo)", color="#4C78A8")
    ax.barh(t.index, t["spam"], left=t["ham"], label="spam/phishing", color="#E45756")
    ax.set_xlabel("registros")
    ax.set_title("Registros por fonte e classe — viés de fonte")
    ax.legend()
    for i, (nome, linha) in enumerate(t.iterrows()):
        ax.text(linha["total"] * 1.01, i, f"{linha['%_da_base']}%", va="center", fontsize=8)
    return _salvar(fig, "01_fonte_rotulo.png")


def grafico_balanceamento(df: pd.DataFrame) -> str:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))

    classe = df["raw_label"].value_counts()
    ax1.pie(
        classe,
        labels=[f"{i}\n{v:,}".replace(",", ".") for i, v in classe.items()],
        colors=["#4C78A8", "#E45756"],
        autopct="%1.1f%%",
        startangle=90,
    )
    ax1.set_title("Balanceamento de classe (base inteira)")

    canal = df.groupby(["channel", "raw_label"]).size().unstack(fill_value=0)
    canal.plot(kind="bar", stacked=True, ax=ax2, color=["#4C78A8", "#E45756"], rot=0)
    ax2.set_title("Distribuição por canal")
    ax2.set_ylabel("registros")
    ax2.set_yscale("log")
    return _salvar(fig, "02_balanceamento.png")


def grafico_comprimento(df: pd.DataFrame) -> str:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    fontes = df["source"].value_counts().index.tolist()
    dados = [df.loc[df["source"] == f, "char_count"].clip(1, 100_000) for f in fontes]
    ax1.boxplot(dados, tick_labels=fontes, vert=False, showfliers=False)
    ax1.set_xscale("log")
    ax1.set_xlabel("caracteres (escala log)")
    ax1.set_title("Comprimento por fonte")

    for rotulo, cor in (("ham", "#4C78A8"), ("spam", "#E45756")):
        serie = df.loc[df["raw_label"] == rotulo, "char_count"].clip(1, 100_000)
        ax2.hist(
            np.log10(serie + 1), bins=60, alpha=0.6, label=f"{rotulo} (n={len(serie):,})".replace(",", "."), color=cor
        )
    ax2.set_xlabel("log10(caracteres)")
    ax2.set_ylabel("registros")
    ax2.set_title("Comprimento por classe — risco de atalho do modelo")
    ax2.legend()
    return _salvar(fig, "03_comprimento.png")


def grafico_sinais(df: pd.DataFrame) -> str:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))

    links = df.groupby("raw_label")["links_count"].mean()
    ax1.bar(links.index, links.values, color=["#4C78A8", "#E45756"])
    ax1.set_title("Média de links por mensagem")
    for i, v in enumerate(links.values):
        ax1.text(i, v, f"{v:.2f}", ha="center", va="bottom")

    anexos = df.groupby("raw_label")["attachments_count"].mean()
    ax2.bar(anexos.index, anexos.values, color=["#4C78A8", "#E45756"])
    ax2.set_title("Média de anexos por mensagem")
    for i, v in enumerate(anexos.values):
        ax2.text(i, v, f"{v:.2f}", ha="center", va="bottom")
    return _salvar(fig, "04_sinais.png")


def grafico_termos(termos: pd.DataFrame) -> str:
    if termos.empty:
        return ""
    fig, ax = plt.subplots(figsize=(8, 7))
    t = termos.sort_values("log_odds")
    cores = ["#4C78A8" if v < 0 else "#E45756" for v in t["log_odds"]]
    ax.barh(t["termo"], t["log_odds"], color=cores)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("log-odds  (< 0 puxa para ham, > 0 puxa para spam)")
    ax.set_title("Termos mais discriminativos (amostra)")
    return _salvar(fig, "05_termos.png")


# ---------------------------------------------------------------- relatório


def _num(n) -> str:
    """Milhar com ponto (pt-BR). Formatar direto no f-string e dar .replace(',', '.')
    depois quebra as vírgulas da própria prose — por isso a conversão fica aqui."""
    return f"{n:,}".replace(",", ".")


def escrever_relatorio(ctx: dict) -> None:
    t = ctx["tabela"]
    enron_pct = t.loc["enron", "%_da_base"] if "enron" in t.index else 0.0
    idiomas = ctx["idiomas"]
    n_amostra = sum(idiomas.values())
    top_idioma, top_n = idiomas.most_common(1)[0]

    linhas = [
        "# Relatório de EDA — Corpus PhishGuard BR",
        "",
        "> Gerado por `src/eda/run_eda.py` sobre `email_dataset_v1_parsed.parquet`.",
        "> Ver planejamento_tg.md §5.2 (amostragem) e §10 (Fase 3).",
        "",
        "## 1. Volume e viés de fonte",
        "",
        f"A base tem **{_num(ctx['total'])} registros** de {len(t)} fontes.",
        "",
        t.to_markdown(),
        "",
        f"**Achado.** A maior fonte responde por {t['%_da_base'].max()}% da base. "
        f"O Enron sozinho é {enron_pct}% e não tem um único spam — um modelo treinado "
        "sobre a base integral pode aprender a reconhecer o estilo de correspondência "
        "corporativa da Enron em vez de aprender fraude.",
        "",
        "## 2. Balanceamento de classe",
        "",
        f"- ham: **{_num(ctx['n_ham'])}** ({ctx['pct_ham']:.1f}%)",
        f"- spam: **{_num(ctx['n_spam'])}** ({100 - ctx['pct_ham']:.1f}%)",
        "",
        f"**Achado.** Um classificador que responda sempre \"legítimo\" acerta "
        f"{ctx['pct_ham']:.1f}% — por isso o projeto reporta F1, precisão e recall, "
        "nunca acurácia isolada.",
        "",
        "## 3. Comprimento do texto",
        "",
        ctx["comprimento"].to_markdown(),
        "",
        f"**Achado.** A mediana varia de {ctx['min_mediana']:.0f} a "
        f"{ctx['max_mediana']:.0f} caracteres entre fontes. Sem estratificação, "
        "\"texto curto\" vira atalho para prever a classe majoritária daquela fonte.",
        "",
        "## 4. Qualidade do parsing",
        "",
        f"- registros com erro de parsing: **{_num(ctx['n_erro'])}** "
        f"({ctx['pct_erro']:.2f}%)",
        f"- registros com corpo vazio após parsing: **{_num(ctx['vazios'])}** "
        f"({ctx['pct_vazio']:.2f}%)",
        "",
        "## 5. Duplicatas remanescentes",
        "",
        "A consolidação removeu duplicatas de texto **exato**. Normalizando "
        "(minúsculas + espaços colapsados) sobram "
        f"**{_num(ctx['duplicatas'])} duplicatas** ({ctx['pct_dup']:.1f}% da base), "
        f"deixando {_num(ctx['unicos'])} textos realmente distintos.",
        "",
        ctx["dup_por_fonte"].to_markdown(),
        "",
        "_Leitura correta da tabela: a duplicata é atribuída à fonte lida **depois**, "
        "então `duplicatas` mistura repetição interna da fonte com sobreposição de "
        "fontes anteriores. A coluna `unicos` é o que importa — o texto novo que "
        "aquela fonte de fato acrescenta ao corpus._",
        "",
        "**Decisão.** Deduplicar por texto normalizado antes do split, senão a mesma "
        "mensagem cai em treino e em teste e infla a métrica.",
        "",
        "## 6. Idioma",
        "",
        f"Amostra de {_num(n_amostra)} registros:",
        "",
        "| idioma | registros | % |",
        "|---|---|---|",
    ]
    for lang, n in idiomas.most_common(8):
        linhas.append(f"| {lang} | {_num(n)} | {n / n_amostra * 100:.1f}% |")

    linhas += [
        "",
        f"**Achado.** {top_n / n_amostra * 100:.1f}% da amostra é `{top_idioma}`. "
        "Não há português no corpus público — é exatamente a lacuna que o corpus "
        "PT-BR deste TG vem preencher, e significa que hoje não existe conjunto de "
        "teste válido para o produto final.",
        "",
        "## 7. Termos discriminativos",
        "",
        ctx["termos"].to_markdown(index=False) if not ctx["termos"].empty else "_amostra insuficiente_",
        "",
        "## 8. Decisões que este EDA fecha",
        "",
        "1. **Amostrar o Enron**, não usá-lo integral — teto por fonte para nenhuma "
        "passar de ~25% da base de treino.",
        "2. **Split estratificado** por fonte *e* por classe.",
        "3. **Deduplicar por texto normalizado** antes de dividir treino/teste.",
        "4. **Descartar** registros com corpo vazio.",
        "5. **Métrica principal: F1** sobre a classe spam; acurácia só como contexto.",
        "6. **Conjunto de teste final em PT-BR**, nunca visto em treino (§5.3).",
        "",
        "## Figuras",
        "",
    ]
    linhas += [f"![{f}](figures/{f})" for f in ctx["figuras"] if f]

    REPORT.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"\nRelatório: {REPORT}")


# ---------------------------------------------------------------- main


def main() -> None:
    if not PARQUET.exists():
        print(f"Base não encontrada: {PARQUET}\nRode parse_and_anonymize.py primeiro.")
        return

    FIG_DIR.mkdir(parents=True, exist_ok=True)

    print("Pass 1 — colunas leves ...")
    df = carregar_colunas_leves()
    tabela = tabela_fonte_rotulo(df)
    comprimento = estatisticas_comprimento(df)
    print(tabela.to_string())

    print("\nPass 2 — varredura de texto em lotes ...")
    texto = varrer_texto()
    print(f"  {texto['total']:,} lidos | {texto['vazios']:,} vazios | "
          f"{texto['duplicatas_normalizadas']:,} duplicatas normalizadas")
    print(texto["dup_por_fonte"].to_string())

    print("\nDetectando idioma na amostra ...")
    idiomas = detectar_idioma(texto["amostra"])
    print("  " + ", ".join(f"{k}={v}" for k, v in idiomas.most_common(5)))

    print("\nCalculando termos discriminativos ...")
    termos = termos_discriminativos(texto["amostra"])

    print("\nGerando figuras ...")
    figuras = [
        grafico_fonte_rotulo(tabela),
        grafico_balanceamento(df),
        grafico_comprimento(df),
        grafico_sinais(df),
        grafico_termos(termos),
    ]

    n_ham = int((df["raw_label"] == "ham").sum())
    n_spam = int((df["raw_label"] == "spam").sum())
    n_erro = int(df["parse_error"].sum())
    total = len(df)

    escrever_relatorio(
        {
            "total": total,
            "tabela": tabela,
            "comprimento": comprimento,
            "n_ham": n_ham,
            "n_spam": n_spam,
            "pct_ham": n_ham / total * 100,
            "n_erro": n_erro,
            "pct_erro": n_erro / total * 100,
            "vazios": texto["vazios"],
            "pct_vazio": texto["vazios"] / total * 100,
            "duplicatas": texto["duplicatas_normalizadas"],
            "pct_dup": texto["duplicatas_normalizadas"] / total * 100,
            "unicos": texto["unicos"],
            "dup_por_fonte": texto["dup_por_fonte"],
            "min_mediana": comprimento["mediana"].min(),
            "max_mediana": comprimento["mediana"].max(),
            "idiomas": idiomas,
            "termos": termos,
            "figuras": figuras,
        }
    )


if __name__ == "__main__":
    main()
