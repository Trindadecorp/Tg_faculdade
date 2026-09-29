"""Baixa os datasets públicos citados no planejamento_tg.md §5.1 para ml/data/raw/.

Automatiza o que tem URL direta e estável (UCI, Apache, CMU). Os demais (Nazario,
TREC, 419, DSmishSMS, CSDMC2010) exigem torrent, aceite de termo ou login/Kaggle —
sem forma confiável de automatizar sem contornar essas barreiras, então o script
só imprime instrução exata de onde buscar.

Uso (a partir de ml/):
    python -m src.parsing.download_datasets            # tudo que é automatizável
    python -m src.parsing.download_datasets --skip-enron  # pula o download de 1,7 GB
"""
import argparse
import bz2
import shutil
import ssl
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

# Hosts acadêmicos antigos com cadeia de certificado quebrada, mas cujo conteúdo é
# um dataset citável e estável (não é sobre confiar no host, é sobre TLS mal
# configurado num servidor universitário parado no tempo). Verificação desligada
# só para esses domínios específicos, nunca de forma global.
_SKIP_CERT_VERIFY_HOSTS = {"www.aueb.gr", "www2.aueb.gr"}


def _download_with_retry(url: str, dest: Path, retries: int = 4, backoff: float = 5.0) -> None:
    """Download com retomada do zero em caso de conexão interrompida ou TLS quebrado.

    Downloads grandes (Enron ~423 MB) podem cair no meio; urlretrieve sozinho não
    verifica o tamanho nem tenta de novo — ele só levanta o erro.
    """
    ctx = None
    if any(host in url for host in _SKIP_CERT_VERIFY_HOSTS):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30, context=ctx) as response, open(dest, "wb") as f:
                shutil.copyfileobj(response, f)
            return
        except (urllib.error.ContentTooShortError, urllib.error.URLError, TimeoutError) as e:
            last_error = e
            dest.unlink(missing_ok=True)
            if attempt < retries:
                print(f"  falhou (tentativa {attempt}/{retries}): {e} — nova tentativa em {backoff:.0f}s")
                time.sleep(backoff)
    raise RuntimeError(f"Falha ao baixar {url} após {retries} tentativas: {last_error}")

SMS_SPAM_COLLECTION_URL = (
    "https://archive.ics.uci.edu/ml/machine-learning-databases/00228/smsspamcollection.zip"
)

SPAMASSASSIN_BASE = "https://spamassassin.apache.org/old/publiccorpus/"
SPAMASSASSIN_FILES = [
    "20021010_easy_ham.tar.bz2",
    "20021010_hard_ham.tar.bz2",
    "20021010_spam.tar.bz2",
    "20030228_easy_ham.tar.bz2",
    "20030228_easy_ham_2.tar.bz2",
    "20030228_hard_ham.tar.bz2",
    "20030228_spam.tar.bz2",
    "20030228_spam_2.tar.bz2",
    "20050311_spam_2.tar.bz2",
]

ENRON_URL = "https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz"

ENRON_SPAM_BASE = "http://www.aueb.gr/users/ion/data/enron-spam/preprocessed/"
ENRON_SPAM_FILES = [f"enron{i}.tar.gz" for i in range(1, 7)]

OPENPHISH_FEED_URL = "https://openphish.com/feed.txt"

URLHAUS_FEED_URL = "https://urlhaus.abuse.ch/downloads/csv_recent/"


def download_sms_spam_collection() -> None:
    """UCI SMS Spam Collection — 5.574 SMS rotulados (ham/spam)."""
    dest_dir = RAW_DIR / "sms_spam_collection"
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "smsspamcollection.zip"

    print(f"Baixando {SMS_SPAM_COLLECTION_URL} ...")
    _download_with_retry(SMS_SPAM_COLLECTION_URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest_dir)
    print(f"OK: {dest_dir}/SMSSpamCollection")


def download_spamassassin() -> None:
    """SpamAssassin Public Corpus — ~6.000 e-mails ham/spam (host oficial Apache)."""
    dest_dir = RAW_DIR / "spamassassin"
    dest_dir.mkdir(parents=True, exist_ok=True)

    for filename in SPAMASSASSIN_FILES:
        url = SPAMASSASSIN_BASE + filename
        archive_path = dest_dir / filename
        print(f"Baixando {url} ...")
        _download_with_retry(url, archive_path)

        with bz2.BZ2File(archive_path) as bz2_file:
            with tarfile.open(fileobj=bz2_file) as tar:
                tar.extractall(dest_dir)

    print(f"OK: {dest_dir}/ ({len(SPAMASSASSIN_FILES)} arquivos extraídos)")


def download_enron(skip: bool = False) -> None:
    """Enron Email Dataset — ~500.000 e-mails corporativos legítimos (host oficial CMU).

    ~1,7 GB compactado — pode demorar dependendo da conexão.
    """
    if skip:
        print("Enron: pulado (--skip-enron).")
        return

    dest_dir = RAW_DIR / "enron"
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive_path = dest_dir / "enron_mail_20150507.tar.gz"

    print(f"Baixando {ENRON_URL} (~423 MB compactado, pode demorar) ...")
    _download_with_retry(ENRON_URL, archive_path)

    print("Extraindo ...")
    with tarfile.open(archive_path) as tar:
        tar.extractall(dest_dir)
    print(f"OK: {dest_dir}/")


def download_enron_spam() -> None:
    """Enron-Spam (AUEB/Metsis, Androutsopoulos & Paliouras) — ~33k e-mails
    ham/spam pré-rotulados (6 caixas de funcionários Enron + spam real).
    Complementa o Enron cru (que é só ham): host oficial da Athens University
    of Economics and Business.
    """
    dest_dir = RAW_DIR / "enron_spam"
    dest_dir.mkdir(parents=True, exist_ok=True)

    for filename in ENRON_SPAM_FILES:
        url = ENRON_SPAM_BASE + filename
        archive_path = dest_dir / filename
        print(f"Baixando {url} ...")
        _download_with_retry(url, archive_path)
        with tarfile.open(archive_path) as tar:
            tar.extractall(dest_dir)

    print(f"OK: {dest_dir}/ ({len(ENRON_SPAM_FILES)} arquivos extraídos)")


def download_openphish_feed() -> None:
    """OpenPhish — feed comunitário de URLs de phishing ativas (atualizado a cada
    12h). Não é corpo de mensagem, é lista de URLs — alimenta o módulo de URL
    (planejamento_tg.md §6.3), não o email_dataset_v1.
    """
    dest_dir = RAW_DIR / "openphish"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "feed.txt"

    print(f"Baixando {OPENPHISH_FEED_URL} ...")
    _download_with_retry(OPENPHISH_FEED_URL, dest_path)
    n = sum(1 for _ in dest_path.open(encoding="utf-8"))
    print(f"OK: {dest_path} ({n} URLs)")


def download_urlhaus_feed() -> None:
    """URLhaus (abuse.ch) — feed público de URLs maliciosas, sem necessidade de chave.

    Atenção: URLhaus cataloga principalmente **distribuição de malware**, não
    phishing. É dado útil para o módulo de URL e para a bateria adversarial, mas
    o rótulo correto vem da coluna `threat` — não deve ser tratado como phishing.
    """
    dest_dir = RAW_DIR / "urlhaus"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "csv_recent.csv"

    print(f"Baixando {URLHAUS_FEED_URL} ...")
    _download_with_retry(URLHAUS_FEED_URL, dest_path)
    dados = [
        linha
        for linha in dest_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if linha and not linha.startswith("#")
    ]
    print(f"OK: {dest_path} ({len(dados)} URLs)")


def print_manual_instructions() -> None:
    manual = {
        "dsmishsms": (
            "Mishra & Soni (DSmishSMS) — sem endpoint de download direto: "
            "https://data.mendeley.com/datasets/f45bkkt8pr/1 (usar botão 'Download All')"
        ),
        "nazario": (
            "Nazario Phishing Corpus — host original instável; usar Academic Torrents "
            "(exige cliente torrent): "
            "https://academictorrents.com/details/a77cda9a9d89a60dbdfbe581adf6e2df9197995a"
        ),
        "trec2007": (
            "TREC Public Spam Corpus 2007 — exige aceitar 'Agreement for use' na página "
            "(https://plg.uwaterloo.ca/~gvcormac/treccorpus07/). Coberto indiretamente via "
            "TREC-05/06/07 dentro do dataset Hugging Face 'seven-phishing-email-datasets' "
            "— rodar download_huggingface.py."
        ),
        "fraudulent_419": (
            "Fraudulent E-mail Corpus (419) — apenas via Kaggle (requer conta + "
            "`kaggle datasets download -d rtatman/fraudulent-email-corpus`): "
            "https://www.kaggle.com/datasets/rtatman/fraudulent-email-corpus"
        ),
        "csdmc2010": (
            "CSDMC2010 SPAM Corpus — arquivo do concurso ICONIP 2010, sem host oficial "
            "estável; buscar `CSDMC2010_SPAM.tar.bz2` em espelhos acadêmicos/GitHub "
            "antes de usar (confirmar licença caso a caso)."
        ),
    }
    for name, msg in manual.items():
        dest_dir = RAW_DIR / name
        dest_dir.mkdir(parents=True, exist_ok=True)
        print(f"- {msg}\n  -> salvar em {dest_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-enron", action="store_true", help="pula o download de 1,7 GB")
    args = parser.parse_args()

    download_sms_spam_collection()
    download_spamassassin()
    download_enron_spam()
    download_openphish_feed()
    download_urlhaus_feed()
    download_enron(skip=args.skip_enron)
    print_manual_instructions()
    print(
        "\nTambém rode `python -m src.parsing.download_huggingface` para trazer o "
        "corpus combinado do Hugging Face (SpamAssassin+CEAS-08+Enron+Ling+TREC-05/06/07, "
        "~203k registros) e o phishing-email-dataset (18,6k)."
    )
