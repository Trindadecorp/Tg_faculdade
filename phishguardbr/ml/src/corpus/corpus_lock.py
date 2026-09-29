"""Congelamento do corpus de controle — PROTOCOLO_EXPERIMENTAL.md §8 (v1.1).

Se o corpus estrangeiro usado em A/C mudar entre execuções — por alteração de
`cap`, semente, amostragem ou reconstrução do dataset —, os contrastes A→B e
C→D deixam de isolar o efeito do corpus PT-BR, e nada acusa. Este módulo torna
essa divergência detectável e fatal.

Dois hashes, com papéis diferentes
----------------------------------
`artifact_sha256`  SHA-256 dos bytes do arquivo. Evidência do artefato físico.
                   Muda com compressão, ordem de gravação ou versão do parquet,
                   mesmo sem mudança lógica nenhuma.

`content_sha256`   Identidade **lógica** do conjunto experimental. Calculado
                   apenas sobre os campos que o experimento usa, de forma
                   determinística e **independente da ordem das linhas**: cada
                   linha vira um hash, os hashes são ordenados, e o conjunto
                   ordenado é hasheado.

A validação oficial decide pelo `content_sha256`. O hash físico entra como
evidência adicional: divergir nele com o conteúdo idêntico é observação
registrada, não falha — o conjunto experimental continua sendo o mesmo.

Uso (a partir de ml/):
    python -m src.corpus.corpus_lock --gerar
    python -m src.corpus.corpus_lock --verificar
"""
import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ML_DIR = Path(__file__).resolve().parents[2]
LOCKFILE = ML_DIR / "models" / "corpus_controle.lock.json"

# Campos que determinam o experimento. Colunas fora desta lista (ids, contagens
# derivadas) não alteram a identidade lógica do conjunto.
CAMPOS_EXPERIMENTAIS = ["source", "channel", "raw_label", "subject", "body_text"]

SEP = "\x1f"  # separador de unidade: não ocorre em texto de e-mail

CONJUNTOS = {
    "corpus_estrangeiro_controle": {
        "arquivo": "data/processed/email_dataset_v2.parquet",
        "papel": (
            "treino estrangeiro em A e C; parcela estrangeira do conjunto "
            "combinado em B e D"
        ),
        "parametros_geracao": {
            "script": "src/features/build_dataset.py",
            "estagio": "sample",
            "cap_por_celula": 20000,
            "seed": 42,
            "entrada": "email_dataset_v2_dedup.parquet",
            "origem_da_dedupe": "email_dataset_v1_parsed.parquet",
        },
    },
}


class CorpusDivergente(RuntimeError):
    """O corpus de controle não corresponde à versão congelada."""


@dataclass
class Divergencia:
    conjunto: str
    campo: str
    esperado: str
    encontrado: str
    fatal: bool

    def __str__(self) -> str:
        # Nome completo do campo: a mensagem precisa apontar exatamente a chave
        # do lock que divergiu, senao quem le nao sabe onde olhar.
        marca = "FATAL" if self.fatal else "aviso"
        return (f"{marca}: {self.conjunto}.{self.campo} "
                f"esperado={self.esperado[:20]}... encontrado={self.encontrado[:20]}...")


def content_sha256(df: pd.DataFrame) -> str:
    """Identidade lógica, estável sob reordenação de linhas.

    Hash por linha, lista ordenada, hash do conjunto. Assim uma reordenação —
    versão diferente do pandas, outra ordem de gravação — não produz
    divergência, porque o conjunto de mensagens é o mesmo.
    """
    faltando = [c for c in CAMPOS_EXPERIMENTAIS if c not in df.columns]
    if faltando:
        raise CorpusDivergente(
            f"colunas experimentais ausentes: {', '.join(faltando)}")

    sub = df[CAMPOS_EXPERIMENTAIS]
    linhas = []
    for tupla in sub.itertuples(index=False, name=None):
        canon = SEP.join(
            "" if v is None or (isinstance(v, float) and v != v) else str(v)
            for v in tupla
        )
        linhas.append(hashlib.sha256(canon.encode("utf-8")).hexdigest())
    linhas.sort()
    return hashlib.sha256("\n".join(linhas).encode("utf-8")).hexdigest()


def artifact_sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _descrever(caminho: Path, meta: dict) -> dict:
    df = pd.read_parquet(caminho)
    return {
        "arquivo": meta["arquivo"],
        "papel": meta["papel"],
        "linhas": int(len(df)),
        "schema": {c: str(t) for c, t in zip(df.columns, df.dtypes)},
        "campos_experimentais": CAMPOS_EXPERIMENTAIS,
        "parametros_geracao": meta["parametros_geracao"],
        "content_sha256": content_sha256(df),
        "artifact_sha256": artifact_sha256(caminho),
        "bytes": caminho.stat().st_size,
        "row_groups": pq.ParquetFile(caminho).metadata.num_row_groups,
    }


def gerar_lock(raiz: Path = ML_DIR, destino: Path = LOCKFILE,
               motivo: str = "congelamento inicial") -> dict:
    """Grava o lock. Sobrescrever é ato deliberado e fica registrado."""
    anterior = json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else None

    lock = {
        "versao_protocolo": "1.1",
        "registrado_em": date.today().isoformat(),
        "motivo": motivo,
        "conjuntos": {},
    }
    for nome, meta in CONJUNTOS.items():
        caminho = raiz / meta["arquivo"]
        if not caminho.exists():
            continue
        lock["conjuntos"][nome] = _descrever(caminho, meta)

    if anterior:
        lock["substitui"] = {
            "registrado_em": anterior.get("registrado_em"),
            "content_sha256": {
                n: c.get("content_sha256")
                for n, c in (anterior.get("conjuntos") or {}).items()
            },
        }

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(lock, indent=2, ensure_ascii=False), encoding="utf-8")
    return lock


def verificar(raiz: Path = ML_DIR, lockfile: Path = LOCKFILE) -> list[Divergencia]:
    """Compara o estado atual com o lock. Lista vazia = idêntico."""
    if not lockfile.exists():
        raise CorpusDivergente(
            f"lock ausente: {lockfile.name}. Gere com "
            f"`python -m src.corpus.corpus_lock --gerar` antes de executar o "
            f"experimento."
        )

    lock = json.loads(lockfile.read_text(encoding="utf-8"))
    divergencias: list[Divergencia] = []

    for nome, esperado in (lock.get("conjuntos") or {}).items():
        caminho = raiz / esperado["arquivo"]
        if not caminho.exists():
            divergencias.append(Divergencia(
                nome, "arquivo", esperado["arquivo"], "AUSENTE", True))
            continue

        df = pd.read_parquet(caminho)

        # Conteúdo é a autoridade.
        atual_content = content_sha256(df)
        if atual_content != esperado["content_sha256"]:
            divergencias.append(Divergencia(
                nome, "content_sha256", esperado["content_sha256"],
                atual_content, True))

        if len(df) != esperado["linhas"]:
            divergencias.append(Divergencia(
                nome, "linhas", str(esperado["linhas"]), str(len(df)), True))

        schema_atual = {c: str(t) for c, t in zip(df.columns, df.dtypes)}
        if schema_atual != esperado["schema"]:
            divergencias.append(Divergencia(
                nome, "schema", "congelado", "alterado", True))

        # Artefato físico é evidência, não autoridade: recompressão ou nova
        # ordem de gravação mudam os bytes sem mudar o conjunto experimental.
        atual_artifact = artifact_sha256(caminho)
        if atual_artifact != esperado["artifact_sha256"]:
            divergencias.append(Divergencia(
                nome, "artifact_sha256", esperado["artifact_sha256"],
                atual_artifact, False))

    return divergencias


def exigir_corpus_congelado(raiz: Path = ML_DIR, lockfile: Path = LOCKFILE) -> list[Divergencia]:
    """Chamada obrigatória antes de treinar qualquer condição de A/B/C/D.

    Levanta `CorpusDivergente` se a identidade lógica não bater. Devolve as
    divergências não fatais para que o relatório as registre.
    """
    divergencias = verificar(raiz, lockfile)
    fatais = [d for d in divergencias if d.fatal]
    if fatais:
        detalhe = "\n".join(f"  - {d}" for d in fatais)
        raise CorpusDivergente(
            "corpus de controle diverge da versao congelada; execucao "
            "interrompida ANTES do treinamento:\n" + detalhe +
            "\n\nSe a mudanca for deliberada, regenere o lock com "
            "`python -m src.corpus.corpus_lock --gerar --motivo \"<justificativa>\"` "
            "e registre a nova versao no protocolo."
        )
    return [d for d in divergencias if not d.fatal]


def main() -> int:
    p = argparse.ArgumentParser(description="Congela e verifica o corpus de controle.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--gerar", action="store_true", help="grava/regrava o lock")
    g.add_argument("--verificar", action="store_true", help="compara com o lock")
    p.add_argument("--motivo", default="congelamento inicial")
    a = p.parse_args()

    if a.gerar:
        lock = gerar_lock(motivo=a.motivo)
        for nome, c in lock["conjuntos"].items():
            print(f"{nome}")
            print(f"  linhas:   {c['linhas']:,}")
            print(f"  content:  {c['content_sha256']}")
            print(f"  artifact: {c['artifact_sha256']}")
        if "substitui" in lock:
            print("\nATENCAO: lock anterior substituido. Motivo registrado: "
                  f"{a.motivo}")
        print(f"\nlock: {LOCKFILE}")
        return 0

    try:
        avisos = exigir_corpus_congelado()
    except CorpusDivergente as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1

    print("OK: corpus de controle identico a versao congelada.")
    for d in avisos:
        print(f"  {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
