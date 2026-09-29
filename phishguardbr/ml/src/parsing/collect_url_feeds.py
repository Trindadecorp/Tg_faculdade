"""Coletor incremental dos feeds de URL — acumula o que os feeds só mostram por 12h.

O OpenPhish publica um snapshot rotativo: cada coleta traz ~300 URLs ativas
naquele momento e descarta as anteriores. Uma coleta única deixa o corpus com
300 URLs de phishing — pouco para treinar qualquer coisa. Rodando de tempos em
tempos e acumulando, o volume cresce sozinho.

Cada URL é gravada com a data em que foi vista pela primeira vez (`first_seen`),
então dá para (a) medir o crescimento do corpus ao longo do TG e (b) montar um
split temporal honesto mais adiante — treinar no que veio antes, testar no que
veio depois.

Uso (a partir de ml/):
    python -m src.parsing.collect_url_feeds

Para agendar a cada 12h no Windows, ver `scripts/agendar_coleta.ps1`.
"""
import csv
import datetime
from pathlib import Path

from src.parsing.download_datasets import (
    OPENPHISH_FEED_URL,
    URLHAUS_FEED_URL,
    _download_with_retry,
)

ML_DIR = Path(__file__).resolve().parents[2]
DEST_DIR = ML_DIR / "data" / "raw" / "url_feeds"
ACUMULADO = DEST_DIR / "url_feeds_accumulated.csv"
CAMPOS = ["url", "source", "threat_type", "first_seen"]


def _carregar_existentes() -> dict[str, dict]:
    if not ACUMULADO.exists():
        return {}
    with open(ACUMULADO, encoding="utf-8", newline="") as f:
        return {linha["url"]: linha for linha in csv.DictReader(f)}


def _coletar_openphish(tmp: Path) -> list[dict]:
    _download_with_retry(OPENPHISH_FEED_URL, tmp)
    urls = [u.strip() for u in tmp.read_text(encoding="utf-8").splitlines() if u.strip()]
    return [{"url": u, "source": "openphish", "threat_type": "phishing"} for u in urls]


def _coletar_urlhaus(tmp: Path) -> list[dict]:
    _download_with_retry(URLHAUS_FEED_URL, tmp)
    linhas = [
        l
        for l in tmp.read_text(encoding="utf-8", errors="replace").splitlines()
        if l and not l.startswith("#")
    ]
    registros = []
    for campos in csv.reader(linhas):
        if len(campos) >= 6:
            registros.append(
                {"url": campos[2], "source": "urlhaus", "threat_type": campos[5]}
            )
    return registros


def main() -> None:
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    hoje = datetime.date.today().isoformat()

    existentes = _carregar_existentes()
    antes = len(existentes)
    print(f"acumulado atual: {antes:,} URLs")

    novos_por_fonte: dict[str, int] = {}
    for nome, coletor in (
        ("openphish", _coletar_openphish),
        ("urlhaus", _coletar_urlhaus),
    ):
        tmp = DEST_DIR / f"_{nome}_tmp"
        try:
            registros = coletor(tmp)
        except Exception as e:  # feed fora do ar não pode derrubar a coleta inteira
            print(f"  {nome}: falhou ({e}) — pulado")
            continue
        finally:
            tmp.unlink(missing_ok=True)

        novos = 0
        for r in registros:
            if r["url"] not in existentes:
                existentes[r["url"]] = {**r, "first_seen": hoje}
                novos += 1
        novos_por_fonte[nome] = novos
        print(f"  {nome}: {len(registros):,} no feed, {novos:,} ineditos")

    with open(ACUMULADO, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=CAMPOS)
        escritor.writeheader()
        escritor.writerows(existentes.values())

    depois = len(existentes)
    print(f"\nacumulado: {antes:,} -> {depois:,} (+{depois - antes:,})")
    print(f"Salvo: {ACUMULADO}")

    por_tipo: dict[str, int] = {}
    for r in existentes.values():
        chave = f"{r['source']}/{r['threat_type']}"
        por_tipo[chave] = por_tipo.get(chave, 0) + 1
    for chave, n in sorted(por_tipo.items(), key=lambda x: -x[1])[:10]:
        print(f"  {n:7,}  {chave}")


if __name__ == "__main__":
    main()
