"""Testes do validador — cada caso quebrado corresponde a uma regra do protocolo.

O objetivo não é cobrir o código: é **provar que o validador recusa exatamente
aquilo que o protocolo diz que deve recusar**. Cada teste nomeia a regra, e uma
regra que deixe de ser aplicada quebra o teste correspondente.

Uso (a partir de ml/):
    python -m pytest tests/test_corpus_validator.py -v
"""
import pandas as pd
import pytest

from src.corpus.clustering import agrupar
from src.corpus.schema import calcular_hash, normalizar
from src.corpus.validate_corpus import validar, validar_registro

TEXTO = "Sua conta sera bloqueada hoje. Regularize seus dados no link."


def reg(**over) -> dict:
    """Registro valido; os testes sobrescrevem o campo que querem quebrar."""
    base = {
        "id": "r1",
        "texto": TEXTO,
        "assunto": None,
        "canal": "sms",
        "rotulo": "golpe",
        "arquetipo": "bloqueio_bancario",
        "marca": None,
        "natureza": "sintetico",
        "fonte_aquisicao": "geracao_interna",
        "metodo_geracao": "llm",
        "transformacao": "original",
        "familia_template": None,
        "grupo_campanha": None,
        "grupo_campanha_metodo": None,
        "grupo_campanha_confianca": None,
        "anonimizado": True,
        "proveniencia_verificada": True,
        "uso_pesquisa": True,
        "redistribuivel": True,
        "base_juridica": "dado_proprio",
        "revisado": True,
        "revisor": "PT",
        "particao": "treino",
        "criado_em": "2026-09-25",
        "hash": calcular_hash(TEXTO),
    }
    base.update(over)
    if "texto" in over and "hash" not in over:
        base["hash"] = calcular_hash(over["texto"])
    return base


def regras(violacoes) -> set[str]:
    return {v.regra for v in violacoes if v.gravidade == "erro"}


# ----------------------------------------------------------------- registro


def test_registro_valido_passa():
    assert validar_registro(reg()) == []


def test_R00_campo_obrigatorio_ausente():
    r = reg()
    del r["canal"]
    assert "R00" in regras(validar_registro(r))


def test_R00_enum_invalido():
    assert "R00" in regras(validar_registro(reg(canal="telegram")))


def test_R00_texto_curto_demais():
    assert "R00" in regras(validar_registro(reg(texto="oi")))


def test_R02_hash_nao_corresponde():
    assert "R02" in regras(validar_registro(reg(hash="0" * 64)))


def test_R03_real_sem_anonimizacao():
    v = validar_registro(reg(
        natureza="real", fonte_aquisicao="doacao", metodo_geracao="nenhum",
        grupo_campanha="camp_0001", grupo_campanha_metodo="singleton",
        anonimizado=False))
    assert "R03" in regras(v)


def test_R03b_real_com_metodo_geracao_llm():
    """natureza=real e metodo_geracao=llm sao contraditorios."""
    v = validar_registro(reg(
        natureza="real", fonte_aquisicao="doacao", metodo_geracao="llm",
        grupo_campanha="camp_0001", grupo_campanha_metodo="singleton"))
    assert "R03b" in regras(v)


def test_R03b_sintetico_sem_metodo_geracao():
    assert "R03b" in regras(validar_registro(reg(metodo_geracao="nenhum")))


def test_R03b_sintetico_com_fonte_de_aquisicao_real():
    assert "R03b" in regras(validar_registro(reg(fonte_aquisicao="doacao")))


def test_R04_template_sem_familia():
    v = validar_registro(reg(metodo_geracao="template", familia_template=None))
    assert "R04" in regras(v)


def test_R05_real_sem_grupo_campanha():
    v = validar_registro(reg(
        natureza="real", fonte_aquisicao="doacao", metodo_geracao="nenhum"))
    assert "R05" in regras(v)


def test_R06_sintetico_no_gold_test():
    """O caso mais importante: sintetico nao entra no Gold Test."""
    assert "R06" in regras(validar_registro(reg(particao="gold_test")))


def test_R06_gold_sem_revisao():
    v = validar_registro(reg(
        particao="gold_test", natureza="real", fonte_aquisicao="doacao",
        metodo_geracao="nenhum", grupo_campanha="camp_0001",
        grupo_campanha_metodo="singleton", revisado=False))
    assert "R06" in regras(v)


def test_R06_gold_sem_proveniencia_verificada():
    v = validar_registro(reg(
        particao="gold_test", natureza="real", fonte_aquisicao="doacao",
        metodo_geracao="nenhum", grupo_campanha="camp_0001",
        grupo_campanha_metodo="singleton", proveniencia_verificada=False))
    assert "R06" in regras(v)


def test_R07_stress_sem_revisao():
    assert "R07" in regras(validar_registro(reg(particao="stress_test", revisado=False)))


def test_R08_redistribuivel_sem_base_juridica_compativel():
    v = validar_registro(reg(redistribuivel=True, base_juridica="legitimo_interesse"))
    assert "R08" in regras(v)


def test_R08_redistribuivel_sem_uso_pesquisa():
    assert "R08" in regras(validar_registro(reg(uso_pesquisa=False)))


def test_R09_arquetipo_de_golpe_em_registro_seguro():
    assert "R09" in regras(validar_registro(reg(rotulo="seguro")))


def test_R09_arquetipo_fora_do_vocabulario():
    assert "R09" in regras(validar_registro(reg(arquetipo="golpe_do_pix_novo")))


def test_R10_assunto_em_canal_sms():
    assert "R10" in regras(validar_registro(reg(assunto="Aviso importante")))


# ----------------------------------------------------------------- conjunto


def _df(*registros) -> pd.DataFrame:
    return pd.DataFrame(list(registros))


def test_R11_familia_template_atravessa_particoes():
    df = _df(
        reg(id="a", metodo_geracao="template", familia_template="fam_1",
            particao="treino"),
        reg(id="b", texto=TEXTO + " variante", metodo_geracao="template",
            familia_template="fam_1", particao="stress_test"),
    )
    rel, _ = validar(df)
    assert "R11" in regras(rel.violacoes)
    assert not rel.consistente


def test_R12_grupo_campanha_atravessa_particoes():
    comum = dict(natureza="real", fonte_aquisicao="doacao", metodo_geracao="nenhum",
                 grupo_campanha="camp_0042", grupo_campanha_metodo="minhash",
                 grupo_campanha_confianca=0.85)
    df = _df(
        reg(id="a", particao="treino", **comum),
        reg(id="b", texto=TEXTO + " outra", particao="gold_test", **comum),
    )
    rel, _ = validar(df)
    assert "R12" in regras(rel.violacoes)


def test_R13_texto_identico_em_particoes_diferentes():
    df = _df(
        reg(id="a", particao="treino"),
        reg(id="b", texto=TEXTO.upper(), particao="stress_test"),
    )
    rel, _ = validar(df)
    assert "R13" in regras(rel.violacoes)


def test_R14_id_duplicado():
    df = _df(reg(id="x"), reg(id="x", texto=TEXTO + " dois"))
    rel, _ = validar(df)
    assert "R14" in regras(rel.violacoes)


def test_conjunto_valido_e_consistente():
    df = _df(
        reg(id="a", particao="treino"),
        reg(id="b", texto="Ola, segue o resumo da reuniao de ontem.",
            rotulo="seguro", arquetipo="comunicacao_corporativa", particao="treino"),
    )
    rel, _ = validar(df)
    assert rel.consistente, [str(v) for v in rel.erros]


# ----------------------------------------------------------------- agrupamento


def test_agrupamento_junta_duplicata_exata():
    a = dict(natureza="real", fonte_aquisicao="doacao", metodo_geracao="nenhum")
    res = agrupar([reg(id="a", **a), reg(id="b", texto=TEXTO.upper(), **a)])
    assert res.grupos["a"] == res.grupos["b"]
    assert res.metodos["a"].value == "hash"


def test_agrupamento_junta_campanha_parecida():
    """Tres SMS reais da mesma campanha, sem template — o vazamento escondido."""
    a = dict(natureza="real", fonte_aquisicao="doacao", metodo_geracao="nenhum")
    res = agrupar([
        reg(id="a", texto="Sua encomenda foi taxada. Regularize em ate 24h no link.", **a),
        reg(id="b", texto="Sua encomenda foi taxada. Regularize em ate 48h no link.", **a),
    ])
    assert res.grupos["a"] == res.grupos["b"]


def test_agrupamento_nao_junta_mensagens_distintas():
    a = dict(natureza="real", fonte_aquisicao="doacao", metodo_geracao="nenhum")
    res = agrupar([
        reg(id="a", texto="Sua encomenda foi taxada. Regularize no link agora.", **a),
        reg(id="b", texto="Bom dia, segue em anexo o relatorio trimestral pedido.", **a),
    ])
    assert res.grupos["a"] != res.grupos["b"]
    assert res.metodos["a"].value == "singleton"


def test_sinteticos_nao_recebem_grupo_campanha():
    res = agrupar([reg(id="a"), reg(id="b", texto=TEXTO + " dois")])
    assert res.grupos == {}


# ------------------------------------------- camada semantica: check x build
#
# A camada de embeddings e dispensavel na INSPECAO e obrigatoria na GERACAO
# oficial do corpus: duas execucoes do build precisam produzir o mesmo
# agrupamento, o que nao se sustenta se a camada rodar numa e nao na outra.


def _encoder_falso(dim: int = 8):
    """Codificador injetado: evita depender do download do E5 (~2,5 GB) para
    exercitar o fluxo. O que se testa aqui e o controle de execucao, nao o
    modelo."""
    import numpy as np

    def encode(textos):
        vetores = []
        for t in textos:
            h = abs(hash(normalizar(t)))
            v = np.array([(h >> (i * 4)) & 0xF for i in range(dim)], dtype=float)
            vetores.append(v / (np.linalg.norm(v) or 1.0))
        return np.vstack(vetores)

    return encode


def _df_real():
    comum = dict(natureza="real", fonte_aquisicao="doacao", metodo_geracao="nenhum",
                 grupo_campanha="camp_0001", grupo_campanha_metodo="singleton",
                 grupo_campanha_confianca=1.0, base_juridica="consentimento",
                 particao="treino")
    return _df(
        reg(id="a", texto="Sua encomenda foi taxada. Regularize no link.", **comum),
        reg(id="b", texto="Bom dia, segue o relatorio trimestral em anexo.",
            rotulo="seguro", arquetipo="comunicacao_corporativa",
            **{**comum, "grupo_campanha": "camp_0002"}),
    )


def test_check_funciona_sem_e5():
    """1. check sem embeddings e permitido."""
    rel, _ = validar(_df_real(), usar_embeddings=False, obrigatorio=False)
    assert rel.consistente
    assert rel.camada_embedding_ativa is False


def test_relatorio_registra_camada_nao_executada():
    """4. o relatorio diz explicitamente que a camada nao rodou."""
    rel, _ = validar(_df_real(), usar_embeddings=False, obrigatorio=False)
    assert "nao solicitada" in rel.camada_embedding_motivo


def test_build_recusado_sem_e5(monkeypatch):
    """2. build sem o ambiente de embeddings falha, nao degrada."""
    import src.corpus.clustering as cl

    monkeypatch.setattr(
        cl, "_versoes",
        lambda: {"torch": None, "transformers": None, "sentence_transformers": None},
    )
    with pytest.raises(cl.EmbeddingIndisponivel) as e:
        validar(_df_real(), usar_embeddings=True, obrigatorio=True)
    assert "build" in str(e.value).lower()


def test_build_funciona_com_e5_disponivel():
    """3. com a camada disponivel, o build roda e registra que executou."""
    rel, agr = validar(
        _df_real(), usar_embeddings=True, obrigatorio=True,
        encoder=_encoder_falso(),
    )
    assert rel.consistente
    assert rel.camada_embedding_ativa is True
    assert rel.camada_embedding_motivo == "executada"


def test_relatorio_registra_versoes_quando_camada_executa():
    """4. o relatorio registra o ambiente usado na geracao."""
    rel, _ = validar(
        _df_real(), usar_embeddings=True, obrigatorio=True,
        encoder=_encoder_falso(),
    )
    assert "versoes" in rel.ambiente
    assert set(rel.ambiente["versoes"]) == {
        "torch", "transformers", "sentence_transformers"}


def test_cli_build_retorna_3_sem_ambiente(monkeypatch, tmp_path):
    """2 (ponta a ponta). O CLI sai com codigo != 0 — especificamente 3."""
    import src.corpus.clustering as cl
    import src.corpus.validate_corpus as vc

    monkeypatch.setattr(
        cl, "_versoes",
        lambda: {"torch": None, "transformers": None, "sentence_transformers": None},
    )
    entrada = tmp_path / "corpus.parquet"
    _df_real().to_parquet(entrada, index=False)
    monkeypatch.setattr(
        "sys.argv",
        ["validate_corpus", "--mode", "build", "--input", str(entrada),
         "--output", str(tmp_path / "out")],
    )
    assert vc.main() == 3


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
