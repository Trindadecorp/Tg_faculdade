"""Baixa datasets de phishing/spam hospedados no Hugging Face Hub para ml/data/raw/.

`seven-phishing-email-datasets` cobre, num único corpus já unificado, fontes que
seriam bloqueadas se buscadas individualmente: TREC-05/06/07 (exige aceite de termo
no host original) e Ling-Spam (sem host oficial estável) — além de mais uma leitura
de SpamAssassin/CEAS-08/Enron. Nenhum dos dois datasets abaixo exige autenticação.

Uso (a partir de ml/):
    python -m src.parsing.download_huggingface
"""
from pathlib import Path

from datasets import load_dataset

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def download_seven_phishing_datasets() -> None:
    """puyang2025/seven-phishing-email-datasets — combina SpamAssassin, CEAS-08,
    Enron, Ling-Spam e TREC-05/06/07 num único corpus rotulado (~203k linhas)."""
    dest_dir = RAW_DIR / "hf_seven_phishing"
    dest_dir.mkdir(parents=True, exist_ok=True)

    ds = load_dataset("puyang2025/seven-phishing-email-datasets")
    for split_name, split in ds.items():
        out_path = dest_dir / f"{split_name}.parquet"
        split.to_parquet(str(out_path))
        print(f"OK: {out_path} ({len(split)} registros)")


def download_zefang_phishing() -> None:
    """zefang-liu/phishing-email-dataset — 18.650 e-mails (Safe Email / Phishing Email),
    espelho do dataset 'Phishing Email Detection' do Kaggle."""
    dest_dir = RAW_DIR / "hf_zefang_phishing"
    dest_dir.mkdir(parents=True, exist_ok=True)

    ds = load_dataset("zefang-liu/phishing-email-dataset")
    for split_name, split in ds.items():
        out_path = dest_dir / f"{split_name}.parquet"
        split.to_parquet(str(out_path))
        print(f"OK: {out_path} ({len(split)} registros)")


if __name__ == "__main__":
    download_seven_phishing_datasets()
    download_zefang_phishing()
