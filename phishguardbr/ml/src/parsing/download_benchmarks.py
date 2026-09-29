"""Baixa datasets de benchmark (vetores de features) via OpenML.

Diferente das fontes em download_datasets.py, estes NÃO contêm o texto das
mensagens — trazem features numéricas já extraídas. Por isso não entram no
email_dataset_v1 (que é corpus de texto) e ficam em ml/data/raw/benchmarks/.

Servem a dois propósitos no TG:
  1. Comparação com a literatura — Spambase e PhishingWebsites são benchmarks
     clássicos com resultados publicados, o que dá um número comparável à banca.
  2. PhishingWebsites descreve features de URL/site, alinhadas ao módulo de URL
     (planejamento_tg.md §6.3).

Uso (a partir de ml/):
    python -m src.parsing.download_benchmarks
"""
from pathlib import Path

from sklearn.datasets import fetch_openml

DEST_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "benchmarks"

DATASETS = {
    # nome_arquivo: (openml_data_id, descrição)
    "spambase": (44, "4.601 e-mails, 57 features de frequência de palavra/caractere"),
    "phishing_websites": (4534, "11.055 sites, 30 features de URL/página"),
}


def main() -> None:
    DEST_DIR.mkdir(parents=True, exist_ok=True)

    for nome, (data_id, descricao) in DATASETS.items():
        print(f"Baixando {nome} (OpenML id={data_id}) — {descricao} ...")
        dataset = fetch_openml(data_id=data_id, as_frame=True, parser="auto")
        df = dataset.frame

        out_path = DEST_DIR / f"{nome}.parquet"
        df.to_parquet(out_path, index=False)

        alvo = dataset.target.name
        print(f"  OK: {out_path} — {df.shape[0]} linhas x {df.shape[1]} colunas")
        print(f"  alvo '{alvo}': {dict(dataset.target.value_counts())}")


if __name__ == "__main__":
    main()
