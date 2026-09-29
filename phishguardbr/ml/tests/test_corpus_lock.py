"""Testes do congelamento do corpus de controle — PROTOCOLO_EXPERIMENTAL.md §8.

Quatro cenários exigidos:
    1. corpus idêntico                  -> passa
    2. conteúdo alterado                -> FALHA antes do treinamento
    3. só o artefato físico alterado    -> passa, com aviso registrado
    4. mudança deliberada do lock       -> aceita e fica auditável

Uso (a partir de ml/):
    python -m pytest tests/test_corpus_lock.py -v
"""
import json

import pandas as pd
import pytest

from src.corpus import corpus_lock as cl


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Raiz artificial com um corpus de controle mínimo."""
    destino = tmp_path / "data" / "processed"
    destino.mkdir(parents=True)
    df = pd.DataFrame(
        {
            "id": [f"m{i}" for i in range(6)],
            "source": ["enron", "enron", "spamassassin", "spamassassin",
                       "sms_spam_collection", "sms_spam_collection"],
            "channel": ["email"] * 4 + ["sms"] * 2,
            "raw_label": ["ham", "spam", "ham", "spam", "ham", "spam"],
            "subject": ["Reuniao", "Viagra", "Patch", "Premio", "", ""],
            "body_text": ["corpo a", "corpo b", "corpo c", "corpo d",
                          "corpo e", "corpo f"],
            "char_count": [7, 7, 7, 7, 7, 7],
        }
    )
    df.to_parquet(destino / "email_dataset_v2.parquet", index=False)

    monkeypatch.setitem(
        cl.CONJUNTOS, "corpus_estrangeiro_controle",
        {
            "arquivo": "data/processed/email_dataset_v2.parquet",
            "papel": "treino estrangeiro em A e C; parcela estrangeira em B e D",
            "parametros_geracao": {"cap_por_celula": 20000, "seed": 42},
        },
    )
    lock = tmp_path / "models" / "corpus.lock.json"
    return tmp_path, lock, destino / "email_dataset_v2.parquet"


# ---------------------------------------------------------------- cenário 1


def test_1_corpus_identico_passa(ambiente):
    raiz, lock, _ = ambiente
    cl.gerar_lock(raiz=raiz, destino=lock)
    assert cl.exigir_corpus_congelado(raiz=raiz, lockfile=lock) == []


def test_1_lock_registra_o_exigido(ambiente):
    raiz, lock, _ = ambiente
    dados = cl.gerar_lock(raiz=raiz, destino=lock)["conjuntos"]["corpus_estrangeiro_controle"]
    assert dados["linhas"] == 6
    assert len(dados["content_sha256"]) == 64
    assert len(dados["artifact_sha256"]) == 64
    assert dados["schema"]                      # schema do dataset
    assert dados["parametros_geracao"]["cap_por_celula"] == 20000
    assert dados["parametros_geracao"]["seed"] == 42
    assert "A e C" in dados["papel"] and "B e D" in dados["papel"]


# ---------------------------------------------------------------- cenário 2


def test_2_conteudo_alterado_falha_antes_do_treino(ambiente):
    raiz, lock, arquivo = ambiente
    cl.gerar_lock(raiz=raiz, destino=lock)

    df = pd.read_parquet(arquivo)
    df.loc[0, "body_text"] = "corpo adulterado"
    df.to_parquet(arquivo, index=False)

    with pytest.raises(cl.CorpusDivergente) as e:
        cl.exigir_corpus_congelado(raiz=raiz, lockfile=lock)
    assert "content_sha256" in str(e.value)
    assert "ANTES do treinamento" in str(e.value)


def test_2_linha_removida_falha(ambiente):
    raiz, lock, arquivo = ambiente
    cl.gerar_lock(raiz=raiz, destino=lock)
    pd.read_parquet(arquivo).iloc[:-1].to_parquet(arquivo, index=False)
    with pytest.raises(cl.CorpusDivergente):
        cl.exigir_corpus_congelado(raiz=raiz, lockfile=lock)


def test_2_rotulo_trocado_falha(ambiente):
    """Trocar um rotulo mantem linhas e schema — so o conteudo acusa."""
    raiz, lock, arquivo = ambiente
    cl.gerar_lock(raiz=raiz, destino=lock)
    df = pd.read_parquet(arquivo)
    df.loc[0, "raw_label"] = "spam"
    df.to_parquet(arquivo, index=False)
    with pytest.raises(cl.CorpusDivergente) as e:
        cl.exigir_corpus_congelado(raiz=raiz, lockfile=lock)
    assert "content_sha256" in str(e.value)


def test_2_coluna_experimental_removida_falha(ambiente):
    raiz, lock, arquivo = ambiente
    cl.gerar_lock(raiz=raiz, destino=lock)
    pd.read_parquet(arquivo).drop(columns=["subject"]).to_parquet(arquivo, index=False)
    with pytest.raises(cl.CorpusDivergente):
        cl.exigir_corpus_congelado(raiz=raiz, lockfile=lock)


# ---------------------------------------------------------------- cenário 3


def test_3_so_artefato_alterado_passa_com_aviso(ambiente):
    """Reordenar as linhas muda os bytes, nao o conjunto experimental."""
    raiz, lock, arquivo = ambiente
    cl.gerar_lock(raiz=raiz, destino=lock)
    antes = cl.artifact_sha256(arquivo)

    df = pd.read_parquet(arquivo)
    df.iloc[::-1].reset_index(drop=True).to_parquet(arquivo, index=False)

    assert cl.artifact_sha256(arquivo) != antes, "o teste precisa mudar os bytes"

    avisos = cl.exigir_corpus_congelado(raiz=raiz, lockfile=lock)  # nao levanta
    assert [d.campo for d in avisos] == ["artifact_sha256"]
    assert all(not d.fatal for d in avisos)


def test_3_content_hash_independe_da_ordem(ambiente):
    _, _, arquivo = ambiente
    df = pd.read_parquet(arquivo)
    assert cl.content_sha256(df) == cl.content_sha256(df.iloc[::-1])


def test_3_coluna_nao_experimental_nao_afeta_conteudo(ambiente):
    """char_count e derivada: mudar nao altera a identidade logica."""
    _, _, arquivo = ambiente
    df = pd.read_parquet(arquivo)
    antes = cl.content_sha256(df)
    df["char_count"] = 999
    assert cl.content_sha256(df) == antes


# ---------------------------------------------------------------- cenário 4


def test_4_mudanca_deliberada_do_lock_e_auditavel(ambiente):
    raiz, lock, arquivo = ambiente
    primeiro = cl.gerar_lock(raiz=raiz, destino=lock)
    hash_antigo = primeiro["conjuntos"]["corpus_estrangeiro_controle"]["content_sha256"]

    df = pd.read_parquet(arquivo)
    df.loc[0, "body_text"] = "corpus reconstruido com outro cap"
    df.to_parquet(arquivo, index=False)

    # sem regerar, falha
    with pytest.raises(cl.CorpusDivergente):
        cl.exigir_corpus_congelado(raiz=raiz, lockfile=lock)

    # regerado com justificativa, passa — e o anterior fica registrado
    novo = cl.gerar_lock(raiz=raiz, destino=lock,
                         motivo="cap alterado para 25000 apos decisao metodologica")
    assert cl.exigir_corpus_congelado(raiz=raiz, lockfile=lock) == []
    assert novo["motivo"].startswith("cap alterado")
    assert novo["substitui"]["content_sha256"]["corpus_estrangeiro_controle"] == hash_antigo
    gravado = json.loads(lock.read_text(encoding="utf-8"))
    assert gravado["substitui"]["registrado_em"]


def test_lock_ausente_falha_com_instrucao(ambiente):
    raiz, lock, _ = ambiente
    with pytest.raises(cl.CorpusDivergente) as e:
        cl.exigir_corpus_congelado(raiz=raiz, lockfile=lock)
    assert "--gerar" in str(e.value)


def test_arquivo_ausente_e_fatal(ambiente):
    raiz, lock, arquivo = ambiente
    cl.gerar_lock(raiz=raiz, destino=lock)
    arquivo.unlink()
    with pytest.raises(cl.CorpusDivergente) as e:
        cl.exigir_corpus_congelado(raiz=raiz, lockfile=lock)
    assert "AUSENTE" in str(e.value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
