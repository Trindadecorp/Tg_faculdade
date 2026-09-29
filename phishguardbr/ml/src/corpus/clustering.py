"""Detecção de agrupamento para controle de vazamento — CORPUS_SCHEMA.md §6.

Quatro camadas, em ordem crescente de custo. Os limiares são **pré-registrados**
no protocolo e não podem ser ajustados depois de ver resultado experimental.

    camada  método                         limiar          decide
    1       hash do texto normalizado      igualdade       duplicata exata
    2       MinHash sobre 5-gramas         Jaccard >= 0,70 mesma campanha
    3       cosseno sobre embeddings E5    >= 0,90         mesma campanha
    4       revisão humana                 faixas de dúvida  adjudicação

O módulo **não decide** os casos de fronteira: ele os emite como pendência. O
corpus é objeto científico, então precisa ficar registrado o que veio da coleta
e o que foi inferido pelo pipeline — por isso todo agrupamento carrega método e
confiança.

A camada 3 é opcional **apenas na inspeção**. Na geração oficial do corpus ela é
obrigatória: duas execuções do build têm de produzir o mesmo agrupamento, e isso
não se sustenta se a camada semântica rodar numa e não na outra.

    --mode check                camada 3 dispensável; o relatório registra a ausência
    --mode check --embeddings   camada 3 executada
    --mode build                camada 3 OBRIGATÓRIA; ambiente ausente falha o build

O modelo é fixado por revisão em `models/e5.lock.json`, gravado na primeira
execução e verificado nas seguintes.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from datasketch import MinHash, MinHashLSH

from src.corpus.schema import MetodoAgrupamento, normalizar

E5_MODELO = "intfloat/multilingual-e5-base"
LOCKFILE = Path(__file__).resolve().parents[2] / "models" / "e5.lock.json"


class EmbeddingIndisponivel(RuntimeError):
    """Camada semântica exigida mas impossível de executar neste ambiente."""

# Pré-registrados. Alterar exige nova versão do esquema.
JACCARD_CAMPANHA = 0.70
JACCARD_DUVIDA = 0.55
COSSENO_CAMPANHA = 0.90
COSSENO_DUVIDA = 0.80

SHINGLE = 5
NUM_PERM = 128


@dataclass
class ResultadoAgrupamento:
    grupos: dict[str, str] = field(default_factory=dict)          # id -> grupo
    metodos: dict[str, MetodoAgrupamento] = field(default_factory=dict)
    confianca: dict[str, float] = field(default_factory=dict)
    pendencias: list[dict] = field(default_factory=list)          # adjudicação
    camada_embedding_ativa: bool = False
    camada_embedding_motivo: str = "nao solicitada"
    ambiente: dict = field(default_factory=dict)  # modelo, revisão, versões


def _shingles(texto: str) -> set[str]:
    t = normalizar(texto)
    if len(t) < SHINGLE:
        return {t} if t else set()
    return {t[i : i + SHINGLE] for i in range(len(t) - SHINGLE + 1)}


def _minhash(texto: str) -> MinHash:
    m = MinHash(num_perm=NUM_PERM)
    for s in _shingles(texto):
        m.update(s.encode("utf-8"))
    return m


def _jaccard_exato(a: str, b: str) -> float:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class _Uniao:
    """Union-find: pares de similaridade viram grupos transitivos."""

    def __init__(self, ids):
        self.pai = {i: i for i in ids}

    def achar(self, x):
        while self.pai[x] != x:
            self.pai[x] = self.pai[self.pai[x]]
            x = self.pai[x]
        return x

    def unir(self, a, b):
        ra, rb = self.achar(a), self.achar(b)
        if ra != rb:
            self.pai[rb] = ra


def agrupar(
    registros: list[dict],
    usar_embeddings: bool = False,
    obrigatorio: bool = False,
    encoder=None,
) -> ResultadoAgrupamento:
    """Atribui `grupo_campanha` aos registros de natureza real.

    `registros` é lista de dicts com ao menos `id`, `texto`, `natureza`.

    `obrigatorio=True` (modo build) faz a ausência do ambiente de embeddings
    levantar `EmbeddingIndisponivel` em vez de degradar silenciosamente.

    `encoder` permite injetar o codificador — usado nos testes para exercitar o
    fluxo sem depender do download do modelo.
    """
    res = ResultadoAgrupamento()

    # Ambiente é verificado ANTES de qualquer trabalho: build que vai falhar
    # deve falhar rápido, não depois de processar o corpus inteiro.
    if obrigatorio and encoder is None:
        _exigir_ambiente()

    reais = [r for r in registros if r.get("natureza") == "real"]
    if not reais:
        if usar_embeddings or obrigatorio:
            res.ambiente = _ambiente(encoder)
            res.camada_embedding_ativa = True
            res.camada_embedding_motivo = "executada (nenhum registro real)"
        return res

    ids = [r["id"] for r in reais]
    texto = {r["id"]: r.get("texto", "") for r in reais}
    uniao = _Uniao(ids)
    metodo_par: dict[tuple[str, str], MetodoAgrupamento] = {}

    # camada 1 — duplicata exata do texto normalizado
    por_hash: dict[str, list[str]] = {}
    for i in ids:
        por_hash.setdefault(normalizar(texto[i]), []).append(i)
    for mesmos in por_hash.values():
        for outro in mesmos[1:]:
            uniao.unir(mesmos[0], outro)
            # Chave sempre ordenada: as camadas seguintes precisam reconhecer o
            # mesmo par para não registrar evidência duplicada.
            metodo_par[tuple(sorted((mesmos[0], outro)))] = MetodoAgrupamento.HASH

    # camada 2 — MinHash/LSH. LSH evita comparar todos contra todos.
    lsh = MinHashLSH(threshold=JACCARD_DUVIDA, num_perm=NUM_PERM)
    assinaturas = {}
    for i in ids:
        m = _minhash(texto[i])
        assinaturas[i] = m
        lsh.insert(i, m)

    vistos: set[tuple[str, str]] = set()
    for i in ids:
        for j in lsh.query(assinaturas[i]):
            if i == j:
                continue
            par = tuple(sorted((i, j)))
            if par in vistos:
                continue
            vistos.add(par)

            # LSH é aproximado; confirma com Jaccard exato sobre os shingles.
            sim = _jaccard_exato(texto[par[0]], texto[par[1]])
            if sim >= JACCARD_CAMPANHA:
                uniao.unir(*par)
                # setdefault, não atribuição: duplicata exata já foi registrada
                # como HASH na camada 1 e essa evidência é mais forte.
                metodo_par.setdefault(par, MetodoAgrupamento.MINHASH)
            elif sim >= JACCARD_DUVIDA:
                res.pendencias.append(
                    {
                        "id_a": par[0], "id_b": par[1],
                        "camada": "minhash", "similaridade": round(sim, 4),
                        "faixa": f"[{JACCARD_DUVIDA}, {JACCARD_CAMPANHA})",
                        "decisao": "",  # preenchido por humano
                    }
                )

    # camada 3 — embeddings
    if usar_embeddings or obrigatorio:
        _camada_embedding(ids, texto, uniao, metodo_par, res, encoder)
        res.camada_embedding_ativa = True
        res.camada_embedding_motivo = "executada"
        res.ambiente = _ambiente(encoder)
    else:
        res.camada_embedding_motivo = "nao solicitada (--mode check sem --embeddings)"

    # consolida os grupos
    rotulo_grupo: dict[str, str] = {}
    for i in ids:
        raiz = uniao.achar(i)
        if raiz not in rotulo_grupo:
            rotulo_grupo[raiz] = f"camp_{len(rotulo_grupo):04d}"
        res.grupos[i] = rotulo_grupo[raiz]

    tamanho: dict[str, int] = {}
    for g in res.grupos.values():
        tamanho[g] = tamanho.get(g, 0) + 1

    for i in ids:
        if tamanho[res.grupos[i]] == 1:
            res.metodos[i] = MetodoAgrupamento.SINGLETON
            res.confianca[i] = 1.0
        else:
            metodos_i = [
                m for (a, b), m in metodo_par.items() if i in (a, b)
            ]
            # HASH é mais forte que MINHASH, que é mais forte que EMBEDDING.
            if MetodoAgrupamento.HASH in metodos_i:
                res.metodos[i], res.confianca[i] = MetodoAgrupamento.HASH, 1.0
            elif MetodoAgrupamento.MINHASH in metodos_i:
                res.metodos[i], res.confianca[i] = MetodoAgrupamento.MINHASH, 0.85
            elif MetodoAgrupamento.EMBEDDING in metodos_i:
                res.metodos[i], res.confianca[i] = MetodoAgrupamento.EMBEDDING, 0.75
            else:
                # Ligado por transitividade, não por par direto.
                res.metodos[i], res.confianca[i] = MetodoAgrupamento.MINHASH, 0.60
    return res


def _versoes() -> dict:
    """Versões das bibliotecas que determinam o resultado do agrupamento."""
    out = {}
    for nome in ("torch", "transformers", "sentence_transformers"):
        try:
            out[nome] = __import__(nome).__version__
        except Exception:
            out[nome] = None
    return out


def _exigir_ambiente() -> None:
    """Falha cedo se a camada semântica não puder rodar."""
    faltando = [n for n, v in _versoes().items() if v is None]
    if faltando:
        raise EmbeddingIndisponivel(
            f"modo build exige a camada de embeddings, mas faltam: "
            f"{', '.join(faltando)}. Instale com: "
            f"pip install sentence-transformers"
        )


def _revisao_travada(modelo=None) -> tuple[str | None, str]:
    """Lê (ou grava) a revisão fixada do E5.

    Na primeira execução resolve o commit do modelo carregado e grava o lock;
    nas seguintes exige que seja o mesmo. Assim o build oficial é reproduzível
    sem que ninguém precise procurar o SHA à mão.
    """
    atual = None
    if modelo is not None:
        try:  # o caminho do snapshot no cache do HF termina no commit
            from pathlib import Path as _P
            atual = _P(modelo[0].auto_model.config._name_or_path).name
            if len(atual) != 40:
                atual = None
        except Exception:
            atual = None

    if LOCKFILE.exists():
        travada = json.loads(LOCKFILE.read_text(encoding="utf-8")).get("revision")
        if atual and travada and atual != travada:
            raise EmbeddingIndisponivel(
                f"revisao do E5 mudou: lock={travada} carregado={atual}. "
                f"Apague {LOCKFILE.name} deliberadamente se a troca for intencional."
            )
        return travada, "lock"

    if atual:
        LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
        LOCKFILE.write_text(
            json.dumps(
                {"modelo": E5_MODELO, "revision": atual, "versoes": _versoes()},
                indent=2,
            ),
            encoding="utf-8",
        )
        return atual, "gravado agora"
    return None, "nao resolvida"


def _ambiente(encoder=None) -> dict:
    if encoder is not None:
        return {"modelo": "encoder injetado (teste)", "revision": None,
                "origem_revisao": "n/a", "versoes": _versoes()}
    rev, origem = _revisao_travada()
    return {"modelo": E5_MODELO, "revision": rev, "origem_revisao": origem,
            "versoes": _versoes()}


def _camada_embedding(ids, texto, uniao, metodo_par, res, encoder=None) -> None:
    """Levanta EmbeddingIndisponivel se exigida e o ambiente não permitir."""
    import numpy as np

    entradas = [f"query: {texto[i]}" for i in ids]

    if encoder is not None:
        vetores = encoder(entradas)
    else:
        _exigir_ambiente()
        from sentence_transformers import SentenceTransformer

        rev, _ = _revisao_travada()
        modelo = SentenceTransformer(E5_MODELO, revision=rev)
        _revisao_travada(modelo)  # grava o lock na primeira vez
        vetores = modelo.encode(
            entradas, normalize_embeddings=True, show_progress_bar=False
        )

    sim = np.asarray(vetores) @ np.asarray(vetores).T
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            s = float(sim[a][b])
            par = tuple(sorted((ids[a], ids[b])))
            if s >= COSSENO_CAMPANHA:
                uniao.unir(*par)
                metodo_par.setdefault(par, MetodoAgrupamento.EMBEDDING)
            elif s >= COSSENO_DUVIDA:
                res.pendencias.append(
                    {
                        "id_a": par[0], "id_b": par[1],
                        "camada": "embedding", "similaridade": round(s, 4),
                        "faixa": f"[{COSSENO_DUVIDA}, {COSSENO_CAMPANHA})",
                        "decisao": "",
                    }
                )
