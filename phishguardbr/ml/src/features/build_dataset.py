"""Constrói o dataset de treino v2 a partir do corpus parseado — Fase 3.

Aplica, nesta ordem, as decisões fechadas pelo EDA (`reports/EDA_REPORT.md`):

  1. Descarta corpo vazio.
  2. Deduplica por texto NORMALIZADO (minúsculo, espaços colapsados). A dedupe
     do consolidate_raw.py foi por texto exato e deixou passar 293.368 cópias —
     52,8% só do Enron, que repete o mesmo e-mail na caixa de cada destinatário.
  3. Aplica teto por célula (fonte × rótulo), não por fonte.

O teto por célula é o ponto não óbvio. Um teto por fonte corrige o volume da
Enron mas não a confusão fonte/rótulo: o Enron é 100% ham, então "escrever como
a Enron" continua sendo atalho para "legítimo" — foi o que a seção 7 do EDA
mostrou (ect, hou, kaminski e forwarded entre os termos mais preditivos de ham).
Limitando por célula, nenhuma combinação fonte×rótulo domina e o atalho fecha.

Dois estágios, porque o primeiro é caro (~8 min) e o segundo é barato: a dedupe
grava `email_dataset_v2_dedup.parquet` uma vez e a amostragem roda em cima dele
quantas vezes for preciso para calibrar o teto.

Uso (a partir de ml/):
    python -m src.features.build_dataset --stage dedup     # 1x, ~8 min
    python -m src.features.build_dataset --stage sample --cap 20000
    python -m src.features.build_dataset --stage sample --cap 20000 --dry-run
"""
import argparse
import hashlib
import random
import re
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ML_DIR = Path(__file__).resolve().parents[2]
PROCESSED = ML_DIR / "data" / "processed"
ENTRADA = PROCESSED / "email_dataset_v1_parsed.parquet"
DEDUP = PROCESSED / "email_dataset_v2_dedup.parquet"
SAIDA = PROCESSED / "email_dataset_v2.parquet"

WS_RE = re.compile(r"\s+")
BATCH_ROWS = 20_000
SEED = 42


def _chave(assunto: str | None, corpo: str | None) -> bytes | None:
    """Hash do texto normalizado. None quando não sobra texto nenhum."""
    texto = f"{assunto or ''} {corpo or ''}".strip()
    if not texto:
        return None
    return hashlib.sha1(WS_RE.sub(" ", texto.lower()).encode("utf-8")).digest()


def estagio_dedup() -> None:
    """Mantém a primeira ocorrência de cada texto normalizado.

    "Primeira" segue a ordem de gravação do consolidate_raw.py, então numa cópia
    entre fontes fica a da fonte lida antes. É arbitrário, mas consistente e
    reprodutível — o que importa é que cada texto apareça uma única vez.
    """
    arquivo = pq.ParquetFile(ENTRADA)
    vistos: set[bytes] = set()
    escritor: pq.ParquetWriter | None = None
    mantidos = removidos = vazios = 0

    try:
        for lote in arquivo.iter_batches(batch_size=BATCH_ROWS):
            assuntos = lote.column("subject").to_pylist()
            corpos = lote.column("body_text").to_pylist()

            manter = []
            for assunto, corpo in zip(assuntos, corpos):
                chave = _chave(assunto, corpo)
                if chave is None:
                    vazios += 1
                    manter.append(False)
                elif chave in vistos:
                    removidos += 1
                    manter.append(False)
                else:
                    vistos.add(chave)
                    mantidos += 1
                    manter.append(True)

            filtrado = lote.filter(pa.array(manter))
            if filtrado.num_rows:
                if escritor is None:
                    escritor = pq.ParquetWriter(DEDUP, filtrado.schema)
                escritor.write_batch(filtrado)
    finally:
        if escritor is not None:
            escritor.close()

    print(f"vazios descartados:     {vazios:,}")
    print(f"duplicatas removidas:   {removidos:,}")
    print(f"mantidos:               {mantidos:,}")
    print(f"\nSalvo: {DEDUP}")
    _matriz(DEDUP)


def _matriz(caminho: Path) -> pd.DataFrame:
    """Matriz fonte × rótulo — a foto que decide o teto."""
    df = pd.read_parquet(caminho, columns=["source", "raw_label"])
    m = df.groupby(["source", "raw_label"]).size().unstack(fill_value=0)
    for col in ("ham", "spam"):
        if col not in m.columns:
            m[col] = 0
    m = m[["ham", "spam"]]
    m["total"] = m.sum(axis=1)
    m = m.sort_values("total", ascending=False)
    print("\nMatriz fonte x rotulo (pos-dedupe):")
    print(m.to_string())
    print(f"\ntotal: {m['total'].sum():,} | "
          f"ham: {m['ham'].sum():,} ({m['ham'].sum() / m['total'].sum() * 100:.1f}%) | "
          f"spam: {m['spam'].sum():,} ({m['spam'].sum() / m['total'].sum() * 100:.1f}%)")
    return m


def _simular(m: pd.DataFrame, teto: int) -> pd.DataFrame:
    """Quanto sobra de cada célula com esse teto, sem tocar no arquivo."""
    sim = m[["ham", "spam"]].clip(upper=teto)
    sim["total"] = sim.sum(axis=1)
    return sim


def estagio_sample(teto: int, dry_run: bool) -> None:
    if not DEDUP.exists():
        print(f"Falta {DEDUP.name} — rode --stage dedup primeiro.")
        return

    m = _matriz(DEDUP)
    sim = _simular(m, teto)
    print(f"\nCom teto de {teto:,} por celula (fonte x rotulo):")
    print(sim.to_string())
    total = sim["total"].sum()
    ham, spam = sim["ham"].sum(), sim["spam"].sum()
    print(f"\nbase resultante: {total:,} | ham {ham:,} ({ham / total * 100:.1f}%) | "
          f"spam {spam:,} ({spam / total * 100:.1f}%)")
    maior = sim["total"].max()
    print(f"maior fonte: {sim['total'].idxmax()} com {maior / total * 100:.1f}% da base")

    if dry_run:
        print("\n(dry-run: nada gravado)")
        return

    # Pass 1: sorteia quais índices globais entram, por célula.
    leve = pd.read_parquet(DEDUP, columns=["source", "raw_label"])
    rng = random.Random(SEED)
    manter_idx: set[int] = set()
    for (fonte, rotulo), grupo in leve.groupby(["source", "raw_label"]):
        indices = grupo.index.tolist()
        if len(indices) > teto:
            indices = rng.sample(indices, teto)
        manter_idx.update(indices)
    del leve

    # Pass 2: reescreve só as linhas sorteadas.
    arquivo = pq.ParquetFile(DEDUP)
    escritor: pq.ParquetWriter | None = None
    deslocamento = 0
    try:
        for lote in arquivo.iter_batches(batch_size=BATCH_ROWS):
            manter = [
                (deslocamento + i) in manter_idx for i in range(lote.num_rows)
            ]
            deslocamento += lote.num_rows
            filtrado = lote.filter(pa.array(manter))
            if filtrado.num_rows:
                if escritor is None:
                    escritor = pq.ParquetWriter(SAIDA, filtrado.schema)
                escritor.write_batch(filtrado)
    finally:
        if escritor is not None:
            escritor.close()

    print(f"\nSalvo: {SAIDA}")
    _matriz(SAIDA)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["dedup", "sample"], required=True)
    p.add_argument("--cap", type=int, default=20_000, help="teto por celula fonte x rotulo")
    p.add_argument("--dry-run", action="store_true", help="so simula o teto")
    a = p.parse_args()

    if a.stage == "dedup":
        estagio_dedup()
    else:
        estagio_sample(a.cap, a.dry_run)
