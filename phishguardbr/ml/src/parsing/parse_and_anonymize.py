"""Parsing MIME + anonimização — planejamento_tg.md §5.3 etapas 2 e 4.

Lê email_dataset_v1.parquet (texto bruto, algumas fontes com cabeçalho RFC822
colado no corpo) e produz email_dataset_v1_parsed.parquet: campos estruturados
(assunto, corpo, contagem de links/anexos) + anonimização de e-mail/telefone.

Regra do projeto (arquitetura_tecnica.md §1): nunca persistir remetente em claro
— só o hash SHA-256 do domínio. O texto bruto com PII fica em ml/data/raw/
(gitignored, nunca publicado); só o resultado deste script é candidato a uso em
treino ou publicação do corpus.

Fontes com cabeçalho RFC822 completo (parsing MIME real): spamassassin, enron,
enron_spam. As demais (sms_spam_collection, hf_*) já chegam como corpo puro —
passam direto pela anonimização, sem parsing de cabeçalho.

Uso (a partir de ml/):
    python -m src.parsing.parse_and_anonymize
"""
import hashlib
import logging
import re
from pathlib import Path

import mailparser
import pandas as pd

# mailparser loga um warning por parte de MIME que não reconhece (pgp-signature,
# ms-tnef, ...) — inofensivo, mas inunda o stdout em centenas de milhares de linhas.
logging.getLogger("mailparser").setLevel(logging.ERROR)

IN_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "email_dataset_v1.parquet"
OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "email_dataset_v1_parsed.parquet"

RAW_MIME_SOURCES = {"spamassassin", "enron", "enron_spam"}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
URL_RE = re.compile(r"https?://\S+")
# Telefone: sequência de 8-13 dígitos com separadores comuns, evitando capturar
# números curtos genéricos demais (datas, contagens) — heurística, não regra fina.
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,5}[-.\s]?\d{4}\b")


def _domain_hash(address: str | None) -> str | None:
    if not address or "@" not in address:
        return None
    domain = address.rsplit("@", 1)[-1].strip().lower()
    return hashlib.sha256(domain.encode("utf-8")).hexdigest()


def _anonymize(text: str) -> str:
    text = EMAIL_RE.sub("<EMAIL>", text)
    text = PHONE_RE.sub("<TEL>", text)
    return text


def parse_raw_email(raw_text: str) -> dict:
    try:
        mail = mailparser.parse_from_string(raw_text)
        sender = mail.from_[0][1] if mail.from_ else None
        body = mail.body or raw_text
        return {
            "subject": mail.subject,
            "body_text": body,
            "sender_domain_hash": _domain_hash(sender),
            "attachments_count": len(mail.attachments or []),
            "parse_method": "mime",
            "parse_error": False,
        }
    except Exception:
        return {
            "subject": None,
            "body_text": raw_text,
            "sender_domain_hash": None,
            "attachments_count": 0,
            "parse_method": "mime_failed",
            "parse_error": True,
        }


def passthrough(raw_text: str) -> dict:
    return {
        "subject": None,
        "body_text": raw_text,
        "sender_domain_hash": None,
        "attachments_count": 0,
        "parse_method": "passthrough",
        "parse_error": False,
    }


def main() -> None:
    if not IN_PATH.exists():
        print(f"Não encontrado: {IN_PATH} — rode consolidate_raw.py primeiro.")
        return

    df = pd.read_parquet(IN_PATH)
    print(f"Processando {len(df)} registros ...")

    parsed_rows = []
    for i, row in enumerate(df.itertuples(index=False), start=1):
        raw_text = row.text if isinstance(row.text, str) else ""

        if row.source in RAW_MIME_SOURCES:
            parsed = parse_raw_email(raw_text)
        else:
            parsed = passthrough(raw_text)

        body = parsed["body_text"] or ""
        parsed["links_count"] = len(URL_RE.findall(body))
        parsed["body_text"] = _anonymize(body)
        if parsed["subject"]:
            parsed["subject"] = _anonymize(parsed["subject"])
        parsed_rows.append(parsed)

        if i % 100_000 == 0:
            print(f"  {i}/{len(df)}")

    parsed_df = pd.DataFrame(parsed_rows)
    out = pd.concat(
        [df[["id", "source", "channel", "raw_label"]].reset_index(drop=True), parsed_df],
        axis=1,
    )
    out["char_count"] = out["body_text"].str.len()

    out.to_parquet(OUT_PATH, index=False)
    out.to_csv(OUT_PATH.with_suffix(".csv"), index=False)

    print(f"\nOK: {len(out)} registros processados")
    print(f"  falhas de parsing MIME: {int(out['parse_error'].sum())}")
    print(f"  método: \n{out['parse_method'].value_counts().to_string()}")
    print(f"\nSalvo em:\n  {OUT_PATH}\n  {OUT_PATH.with_suffix('.csv')}")
    print(
        "\nIMPORTANTE: o campo 'text' com remetente/corpo em claro só existe em "
        "email_dataset_v1.parquet (derivado de ml/data/raw/, gitignored). Este "
        "arquivo (_parsed) é o que deve ser usado a partir daqui — e-mail e "
        "telefone já substituídos por marcadores, remetente reduzido a hash."
    )


if __name__ == "__main__":
    main()
