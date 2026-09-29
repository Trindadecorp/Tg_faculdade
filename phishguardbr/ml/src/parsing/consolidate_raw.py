"""Consolida as fontes brutas em ml/data/raw/ em dois datasets tabulares:

- email_dataset_v1 (mensagens completas, rotuladas ham/spam)
- phishing_urls_v1 (URLs isoladas — feed OpenPhish, não tem corpo de mensagem)

Entregável da Fase 2 (planejamento_tg.md §10). Cada fonte tem formato diferente
(TSV, e-mail avulso em pasta, maildir, parquet do Hugging Face) — este script
normaliza tudo para as mesmas colunas, sem ainda fazer parsing MIME completo nem
rotular na taxonomia final do produto (seguro/suspeito/golpe) — isso é decisão
de feature engineering (Fase 3), não de consolidação.

Uso (a partir de ml/):
    python -m src.parsing.consolidate_raw
"""
import csv
import uuid
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

SPAMASSASSIN_FOLDERS = {
    "easy_ham": "ham",
    "easy_ham_2": "ham",
    "hard_ham": "ham",
    "spam": "spam",
    "spam_2": "spam",
}


def _read_text_best_effort(path: Path) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_bytes().decode("utf-8", errors="replace")


def load_sms_spam_collection() -> list[dict]:
    path = RAW_DIR / "sms_spam_collection" / "SMSSpamCollection"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        label, _, text = line.partition("\t")
        if not text:
            continue
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "source": "sms_spam_collection",
                "channel": "sms",
                "raw_label": label,
                "text": text,
                "raw_path": str(path),
            }
        )
    return rows


def load_spamassassin() -> list[dict]:
    base = RAW_DIR / "spamassassin"
    if not base.exists():
        return []
    rows = []
    for folder, raw_label in SPAMASSASSIN_FOLDERS.items():
        folder_path = base / folder
        if not folder_path.exists():
            continue
        for file_path in folder_path.iterdir():
            if not file_path.is_file() or file_path.name == "cmds":
                continue
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "source": "spamassassin",
                    "channel": "email",
                    "raw_label": raw_label,
                    "text": _read_text_best_effort(file_path),
                    "raw_path": str(file_path),
                }
            )
    return rows


def load_enron() -> list[dict]:
    maildir = RAW_DIR / "enron" / "maildir"
    if not maildir.exists():
        return []
    rows = []
    for file_path in maildir.rglob("*"):
        if not file_path.is_file():
            continue
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "source": "enron",
                "channel": "email",
                "raw_label": "ham",  # todo o corpus Enron é correspondência corporativa legítima
                "text": _read_text_best_effort(file_path),
                "raw_path": str(file_path),
            }
        )
    return rows


def load_enron_spam() -> list[dict]:
    """AUEB — pastas ham/ e spam/ dentro de cada enronN/ extraído."""
    base = RAW_DIR / "enron_spam"
    if not base.exists():
        return []
    rows = []
    for file_path in base.rglob("*"):
        if not file_path.is_file():
            continue
        parts_lower = {p.lower() for p in file_path.parts}
        if "ham" in parts_lower:
            raw_label = "ham"
        elif "spam" in parts_lower:
            raw_label = "spam"
        else:
            continue
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "source": "enron_spam",
                "channel": "email",
                "raw_label": raw_label,
                "text": _read_text_best_effort(file_path),
                "raw_path": str(file_path),
            }
        )
    return rows


def _load_hf_parquet_dir(
    dir_path: Path,
    source_name: str,
    text_col_candidates: list[str],
    label_col_candidates: list[str],
    positive_values: set,
) -> list[dict]:
    """Lê parquet(s) baixados via Hugging Face e normaliza para o esquema comum.

    Nomes de coluna variam por dataset — tenta a lista de candidatos na ordem
    e avisa (sem quebrar o resto do pipeline) se nenhum bater.
    """
    if not dir_path.exists():
        return []
    rows = []
    for parquet_file in sorted(dir_path.glob("*.parquet")):
        df = pd.read_parquet(parquet_file)
        text_col = next((c for c in text_col_candidates if c in df.columns), None)
        label_col = next((c for c in label_col_candidates if c in df.columns), None)
        if text_col is None or label_col is None:
            print(f"  aviso: colunas não reconhecidas em {parquet_file.name}: {list(df.columns)}")
            continue
        sub = df[[text_col, label_col]].rename(
            columns={text_col: "text", label_col: "raw_label_value"}
        )
        sub["raw_label"] = sub["raw_label_value"].isin(positive_values).map(
            {True: "spam", False: "ham"}
        )
        sub["id"] = [str(uuid.uuid4()) for _ in range(len(sub))]
        sub["source"] = source_name
        sub["channel"] = "email"
        sub["raw_path"] = str(parquet_file)
        rows.extend(sub[["id", "source", "channel", "raw_label", "text", "raw_path"]].to_dict("records"))
    return rows


def load_hf_seven_phishing() -> list[dict]:
    """puyang2025/seven-phishing-email-datasets — SpamAssassin+CEAS-08+Enron+Ling+TREC-05/06/07."""
    return _load_hf_parquet_dir(
        RAW_DIR / "hf_seven_phishing",
        "hf_seven_phishing",
        text_col_candidates=["body", "text", "email_text", "content"],
        label_col_candidates=["label", "labels"],
        positive_values={1, "1", True},
    )


def load_hf_zefang_phishing() -> list[dict]:
    """zefang-liu/phishing-email-dataset — 18.650 e-mails (Safe Email / Phishing Email)."""
    return _load_hf_parquet_dir(
        RAW_DIR / "hf_zefang_phishing",
        "hf_zefang_phishing",
        text_col_candidates=["Email Text", "text"],
        label_col_candidates=["Email Type", "label"],
        positive_values={"Phishing Email"},
    )


def consolidate_urls() -> None:
    """Feeds de URL (OpenPhish + URLhaus) — schema diferente do email_dataset.

    Os dois não são a mesma ameaça: OpenPhish cataloga phishing; URLhaus cataloga
    distribuição de malware. O tipo real fica na coluna `threat_type`, para não
    contaminar o rótulo de phishing com URLs de malware.
    """
    rows = []

    openphish = RAW_DIR / "openphish" / "feed.txt"
    if openphish.exists():
        urls = [u.strip() for u in openphish.read_text(encoding="utf-8").splitlines() if u.strip()]
        rows.extend(
            {"id": str(uuid.uuid4()), "url": u, "source": "openphish", "threat_type": "phishing"}
            for u in urls
        )
        print(f"openphish: {len(urls)} URLs")
    else:
        print("openphish: ainda não disponível (pulado)")

    urlhaus = RAW_DIR / "urlhaus" / "csv_recent.csv"
    if urlhaus.exists():
        linhas = [
            l
            for l in urlhaus.read_text(encoding="utf-8", errors="replace").splitlines()
            if l and not l.startswith("#")
        ]
        antes = len(rows)
        for registro in csv.reader(linhas):
            if len(registro) >= 6:
                rows.append(
                    {
                        "id": str(uuid.uuid4()),
                        "url": registro[2],
                        "source": "urlhaus",
                        "threat_type": registro[5],  # malware_download, etc.
                    }
                )
        print(f"urlhaus: {len(rows) - antes} URLs")
    else:
        print("urlhaus: ainda não disponível (pulado)")

    if not rows:
        return

    df = pd.DataFrame(rows).drop_duplicates(subset=["url"])
    out_path = OUT_DIR / "malicious_urls_v1.csv"
    df.to_csv(out_path, index=False)
    print(f"URLs consolidadas: {len(df)} -> {out_path}")
    print(df.groupby(["source", "threat_type"]).size().to_string())


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    loaders = {
        "sms_spam_collection": load_sms_spam_collection,
        "spamassassin": load_spamassassin,
        "enron": load_enron,
        "enron_spam": load_enron_spam,
        "hf_seven_phishing": load_hf_seven_phishing,
        "hf_zefang_phishing": load_hf_zefang_phishing,
    }
    all_rows: list[dict] = []
    for name, loader in loaders.items():
        rows = loader()
        print(f"{name}: {len(rows)} registros" if rows else f"{name}: ainda não disponível (pulado)")
        all_rows.extend(rows)

    consolidate_urls()

    if not all_rows:
        print("Nenhuma fonte disponível ainda — rode download_datasets.py primeiro.")
        return

    df = pd.DataFrame(all_rows)
    df["char_count"] = df["text"].str.len()
    df = df.drop_duplicates(subset=["text"])

    csv_path = OUT_DIR / "email_dataset_v1.csv"
    parquet_path = OUT_DIR / "email_dataset_v1.parquet"
    df.to_csv(csv_path, index=False)
    df.to_parquet(parquet_path, index=False)

    print(f"\nOK: {len(df)} registros consolidados (após remover duplicatas exatas de texto)")
    print(df.groupby(["source", "raw_label"]).size().to_string())
    print(f"\nSalvo em:\n  {csv_path}\n  {parquet_path}")


if __name__ == "__main__":
    main()
