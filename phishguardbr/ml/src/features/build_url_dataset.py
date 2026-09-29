"""Monta o dataset do módulo de URL a partir dos feeds e do corpus de e-mail.

Positivos: `url_feeds_accumulated.csv` (OpenPhish = página enganosa, URLhaus =
entrega de payload). O rótulo de treino é binário — `is_malicious` — porque do
ponto de vista do e-mail as duas são a mesma decisão: o link é perigoso ou não.
O `threat_type` é preservado como METADADO, não como rótulo, para duas coisas:

  1. a camada de explicação do produto ("página que imita marca" x "link que
     baixa programa"), e
  2. o protocolo de avaliação cruzada em `url_model.py`, que treina num tipo de
     ameaça e testa no outro.

Negativos: URLs extraídas dos e-mails ham do corpus. São URLs reais, com caminho
e query de verdade — diferente de uma lista de domínios populares, que traria só
`dominio.com` e ensinaria ao modelo o atalho "tem caminho = perigoso".

LIMITAÇÃO DOCUMENTADA: os negativos vêm de corpora de 2002 e os positivos de
feeds de hoje. Há confusão temporal — TLDs, encurtadores e padrões de URL
mudaram. É por isso que `url_model.py` valida também no benchmark independente
PhishingWebsites (OpenML 4534), que tem positivos e negativos da mesma época.

Uso (a partir de ml/):
    python -m src.features.build_url_dataset
"""
import re
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ML_DIR = Path(__file__).resolve().parents[2]
FEEDS = ML_DIR / "data" / "raw" / "url_feeds" / "url_feeds_accumulated.csv"
CORPUS = ML_DIR / "data" / "processed" / "email_dataset_v2.parquet"
SAIDA = ML_DIR / "data" / "processed" / "url_dataset_v1.parquet"

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
BATCH_ROWS = 20_000
SEED = 42


def carregar_maliciosas() -> pd.DataFrame:
    if not FEEDS.exists():
        raise SystemExit(f"Falta {FEEDS} — rode src.parsing.collect_url_feeds.")
    df = pd.read_csv(FEEDS)
    df["is_malicious"] = 1
    return df[["url", "source", "threat_type", "first_seen", "is_malicious"]]


def extrair_benignas() -> pd.DataFrame:
    """URLs dos e-mails ham do corpus — legítimas, com estrutura real."""
    arquivo = pq.ParquetFile(CORPUS)
    urls: set[str] = set()
    for lote in arquivo.iter_batches(
        batch_size=BATCH_ROWS, columns=["raw_label", "body_text"]
    ):
        rotulos = lote.column("raw_label").to_pylist()
        corpos = lote.column("body_text").to_pylist()
        for rotulo, corpo in zip(rotulos, corpos):
            if rotulo != "ham":
                continue
            urls.update(URL_RE.findall(corpo or ""))
    return pd.DataFrame(
        {
            "url": sorted(urls),
            "source": "corpus_ham",
            "threat_type": "benign",
            "first_seen": "",
            "is_malicious": 0,
        }
    )


def main() -> None:
    mal = carregar_maliciosas()
    print(f"maliciosas: {len(mal):,}")
    print(mal.groupby(["source", "threat_type"]).size().to_string())

    ben = extrair_benignas()
    print(f"\nbenignas (URLs unicas de e-mail ham): {len(ben):,}")

    # Equilibra sem forçar 50/50 artificial: no máximo 3 benignas por maliciosa.
    teto = min(len(ben), len(mal) * 3)
    if len(ben) > teto:
        ben = ben.sample(teto, random_state=SEED)
        print(f"benignas amostradas para {teto:,}")

    df = pd.concat([mal, ben], ignore_index=True).drop_duplicates(subset=["url"])
    df = df.sample(frac=1, random_state=SEED).reset_index(drop=True)
    df.to_parquet(SAIDA, index=False)

    print(f"\ntotal: {len(df):,} | maliciosas {df['is_malicious'].sum():,} "
          f"({df['is_malicious'].mean() * 100:.1f}%)")
    print(df.groupby(["source", "threat_type"]).size().to_string())
    print(f"\nSalvo: {SAIDA}")


if __name__ == "__main__":
    main()
