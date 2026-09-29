"""Validador do corpus PT-BR — torna o protocolo executável.

As restrições de `docs/CORPUS_SCHEMA.md` e `docs/PROTOCOLO_CURADORIA.md` viram
invariantes verificadas automaticamente antes de cada geração do conjunto
experimental. Violação estrutural **quebra o build** (saída != 0), não imprime
aviso.

Dois modos:

    --mode check   só verifica e gera relatório; não escreve artefato derivado
    --mode build   verifica, calcula agrupamentos e, se tudo estiver consistente,
                   produz os artefatos derivados

O modo build **nunca sobrescreve a entrada**. Agrupamento inferido pelo pipeline
sai em `candidate_clusters.parquet` e `adjudication_pending.csv`; o corpus
validado é uma versão derivada, com `grupo_campanha_metodo` e
`grupo_campanha_confianca` preenchidos — para que fique sempre distinguível o
que veio da coleta e o que foi inferido.

Uso (a partir de ml/):
    python -m src.corpus.validate_corpus --mode check
    python -m src.corpus.validate_corpus --mode build --input <arquivo>

Saída:
    0  consistente
    1  violação de regra
    2  erro de uso / entrada ausente
    3  ambiente insuficiente para o build (camada de embeddings indisponível)
"""
import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from src.corpus.clustering import EmbeddingIndisponivel, agrupar
from src.corpus.schema import (
    ARQUETIPOS,
    ARQUETIPOS_GOLPE,
    ARQUETIPOS_SEGURO,
    BASES_PUBLICAVEIS,
    CAMPOS,
    ESQUEMA_VERSAO,
    Registro,
    calcular_hash,
    normalizar,
)

ML_DIR = Path(__file__).resolve().parents[2]
PTBR = ML_DIR / "data" / "ptbr"
ENTRADA_PADRAO = PTBR / "processed_private" / "corpus_ptbr_v1.parquet"
REPORTS = ML_DIR / "reports"

PARTICOES_EXPERIMENTAIS = {"treino", "gold_test", "stress_test"}


@dataclass
class Violacao:
    regra: str
    gravidade: str          # erro | pendencia
    mensagem: str
    registro_id: str = ""

    def __str__(self) -> str:
        alvo = f" [{self.registro_id}]" if self.registro_id else ""
        return f"{self.gravidade.upper()}: {self.regra}{alvo} — {self.mensagem}"


@dataclass
class Relatorio:
    esquema_versao: str = ESQUEMA_VERSAO
    total_registros: int = 0
    violacoes: list[Violacao] = field(default_factory=list)
    resumo: dict = field(default_factory=dict)
    camada_embedding_ativa: bool = False
    camada_embedding_motivo: str = "nao solicitada"
    ambiente: dict = field(default_factory=dict)

    @property
    def erros(self) -> list[Violacao]:
        return [v for v in self.violacoes if v.gravidade == "erro"]

    @property
    def consistente(self) -> bool:
        return not self.erros


# ------------------------------------------------------------ regras por registro


def _limpar_nulos(bruto: dict) -> dict:
    """Parquet devolve None como NaN em coluna numérica, e NaN falha em qualquer
    comparação — `NaN <= 1` é falso, então o campo opcional seria rejeitado.
    Converte de volta para None antes da validação."""
    saida = {}
    for k in CAMPOS:
        valor = bruto.get(k)
        if valor is None or (isinstance(valor, float) and valor != valor):
            saida[k] = None
        elif pd.isna(valor) if not isinstance(valor, (list, dict, set)) else False:
            saida[k] = None
        else:
            saida[k] = valor
    return saida


def validar_registro(bruto: dict) -> list[Violacao]:
    """R01..R09 — regras do CORPUS_SCHEMA.md §4, cada uma identificável."""
    rid = str(bruto.get("id", "<sem id>"))
    v: list[Violacao] = []

    # R00 — tipos, enums e obrigatórios (delegado ao Pydantic)
    try:
        r = Registro(**_limpar_nulos(bruto))
    except ValidationError as e:
        for erro in e.errors():
            campo = ".".join(str(p) for p in erro["loc"])
            v.append(Violacao("R00", "erro", f"{campo}: {erro['msg']}", rid))
        return v  # sem registro válido não dá para checar semântica

    # R02 — hash coerente com o texto normalizado
    if r.hash != calcular_hash(r.texto):
        v.append(Violacao("R02", "erro", "hash nao corresponde ao texto normalizado", rid))

    # R03 — natureza real exige anonimização
    if r.natureza == "real" and not r.anonimizado:
        v.append(Violacao("R03", "erro", "natureza=real exige anonimizado=true", rid))

    # R03b — coerência entre as quatro dimensões de proveniência
    if r.natureza == "real" and r.metodo_geracao != "nenhum":
        v.append(Violacao(
            "R03b", "erro",
            f"natureza=real e incompativel com metodo_geracao={r.metodo_geracao}", rid))
    if r.natureza == "sintetico" and r.metodo_geracao == "nenhum":
        v.append(Violacao(
            "R03b", "erro", "natureza=sintetico exige metodo_geracao template ou llm", rid))
    if r.natureza == "sintetico" and r.fonte_aquisicao != "geracao_interna":
        v.append(Violacao(
            "R03b", "erro",
            f"natureza=sintetico e incompativel com fonte_aquisicao={r.fonte_aquisicao}", rid))
    if r.natureza == "real" and r.fonte_aquisicao == "geracao_interna":
        v.append(Violacao(
            "R03b", "erro", "natureza=real nao pode ter fonte_aquisicao=geracao_interna", rid))

    # R04 — template exige familia declarada
    if r.metodo_geracao == "template" and not r.familia_template:
        v.append(Violacao("R04", "erro", "metodo_geracao=template exige familia_template", rid))

    # R05 — real exige grupo de campanha (ainda que singleton)
    if r.natureza == "real" and not r.grupo_campanha:
        v.append(Violacao("R05", "erro", "natureza=real exige grupo_campanha atribuido", rid))
    if r.grupo_campanha and not r.grupo_campanha_metodo:
        v.append(Violacao("R05", "erro", "grupo_campanha exige grupo_campanha_metodo", rid))

    # R06 — Gold Test: real, revisado, proveniencia verificada
    if r.particao == "gold_test":
        if r.natureza != "real":
            v.append(Violacao("R06", "erro", "gold_test exige natureza=real", rid))
        if not r.revisado:
            v.append(Violacao("R06", "erro", "gold_test exige revisado=true", rid))
        if not r.proveniencia_verificada:
            v.append(Violacao("R06", "erro", "gold_test exige proveniencia_verificada=true", rid))

    # R07 — Stress Test exige revisao
    if r.particao == "stress_test" and not r.revisado:
        v.append(Violacao("R07", "erro", "stress_test exige revisado=true", rid))

    # R08 — licenciamento
    if r.redistribuivel:
        if r.base_juridica not in {b.value for b in BASES_PUBLICAVEIS}:
            v.append(Violacao(
                "R08", "erro",
                f"redistribuivel=true incompativel com base_juridica={r.base_juridica}", rid))
        if not r.uso_pesquisa:
            v.append(Violacao(
                "R08", "erro", "redistribuivel=true exige uso_pesquisa=true", rid))
    if not r.uso_pesquisa and not r.redistribuivel:
        v.append(Violacao("R08", "erro", "registro sem uso_pesquisa nao deve estar no corpus", rid))

    # R09 — arquetipo coerente com rotulo
    if r.arquetipo not in ARQUETIPOS:
        v.append(Violacao("R09", "erro", f"arquetipo '{r.arquetipo}' fora do vocabulario", rid))
    elif r.rotulo == "golpe" and r.arquetipo not in ARQUETIPOS_GOLPE:
        v.append(Violacao("R09", "erro", f"arquetipo '{r.arquetipo}' nao e de golpe", rid))
    elif r.rotulo == "seguro" and r.arquetipo not in ARQUETIPOS_SEGURO:
        v.append(Violacao("R09", "erro", f"arquetipo '{r.arquetipo}' nao e de mensagem legitima", rid))

    # R10 — assunto so faz sentido em e-mail
    if r.assunto and r.canal != "email":
        v.append(Violacao("R10", "erro", f"assunto preenchido em canal={r.canal}", rid))

    return v


# ------------------------------------------------------------ regras de conjunto


def validar_conjunto(df: pd.DataFrame) -> list[Violacao]:
    """R11..R14 — o que só se vê olhando o dataset inteiro."""
    v: list[Violacao] = []
    exp = df[df["particao"].isin(PARTICOES_EXPERIMENTAIS)]

    # R11 — familia_template nao atravessa particao
    for chave in ("familia_template", "grupo_campanha"):
        regra = "R11" if chave == "familia_template" else "R12"
        sub = exp[exp[chave].notna() & (exp[chave] != "")]
        for grupo, g in sub.groupby(chave):
            particoes = sorted(g["particao"].unique())
            if len(particoes) > 1:
                v.append(Violacao(
                    regra, "erro",
                    f"{chave} '{grupo}' ocorre em {' e '.join(particoes)} "
                    f"({len(g)} registros)"))

    # R13 — mesmo texto normalizado em particoes diferentes
    exp = exp.copy()
    exp["_norm"] = exp["texto"].fillna("").map(normalizar)
    for texto_norm, g in exp.groupby("_norm"):
        particoes = sorted(g["particao"].unique())
        if len(particoes) > 1:
            v.append(Violacao(
                "R13", "erro",
                f"texto identico apos normalizacao em {' e '.join(particoes)}: "
                f"{', '.join(g['id'].astype(str).head(3))}"))

    # R14 — id duplicado
    dups = df[df.duplicated("id", keep=False)]["id"].unique()
    for i in dups:
        v.append(Violacao("R14", "erro", f"id duplicado: {i}"))

    return v


def resumir(df: pd.DataFrame) -> dict:
    def contagem(col):
        return {str(k): int(x) for k, x in df[col].value_counts().items()}

    publicaveis = int(df["redistribuivel"].sum()) if "redistribuivel" in df else 0
    return {
        "por_particao": contagem("particao"),
        "por_canal": contagem("canal"),
        "por_rotulo": contagem("rotulo"),
        "por_natureza": contagem("natureza"),
        "redistribuiveis": publicaveis,
        "fora_da_versao_publica": int(len(df)) - publicaveis,
    }


# ------------------------------------------------------------ relatórios


def gravar_relatorios(rel: Relatorio) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)

    (REPORTS / "validation_report.json").write_text(
        json.dumps(
            {
                "esquema_versao": rel.esquema_versao,
                "consistente": rel.consistente,
                "total_registros": rel.total_registros,
                "total_erros": len(rel.erros),
                "camada_embedding_ativa": rel.camada_embedding_ativa,
                "camada_embedding_motivo": rel.camada_embedding_motivo,
                "ambiente": rel.ambiente,
                "resumo": rel.resumo,
                "violacoes": [asdict(v) for v in rel.violacoes],
            },
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    linhas = [
        "VALIDACAO DO CORPUS PT-BR",
        f"esquema v{rel.esquema_versao} | {rel.total_registros} registros",
        f"camada semantica (embeddings): "
        f"{'EXECUTADA' if rel.camada_embedding_ativa else 'NAO EXECUTADA'}"
        f" — {rel.camada_embedding_motivo}",
        "=" * 70,
        "",
    ]
    if rel.ambiente:
        linhas.append(f"modelo:   {rel.ambiente.get('modelo')}")
        linhas.append(
            f"revisao:  {rel.ambiente.get('revision')} "
            f"({rel.ambiente.get('origem_revisao')})"
        )
        for lib, ver in (rel.ambiente.get("versoes") or {}).items():
            linhas.append(f"  {lib}: {ver}")
        linhas.append("")
    elif not rel.camada_embedding_ativa:
        linhas.append(
            "AVISO: agrupamento semantico nao executado. Resultado valido para "
            "inspecao, NAO para geracao oficial do corpus (--mode build)."
        )
        linhas.append("")
    if rel.resumo:
        for chave, valor in rel.resumo.items():
            linhas.append(f"{chave}: {valor}")
        linhas.append("")

    if rel.consistente:
        linhas.append("OK: nenhuma violacao estrutural.")
    else:
        linhas.append(f"{len(rel.erros)} VIOLACAO(OES) ESTRUTURAL(IS):")
        linhas.append("")
        por_regra: dict[str, list[Violacao]] = {}
        for x in rel.erros:
            por_regra.setdefault(x.regra, []).append(x)
        for regra in sorted(por_regra):
            linhas.append(f"  [{regra}] {len(por_regra[regra])} ocorrencia(s)")
            for x in por_regra[regra][:10]:
                alvo = f" [{x.registro_id}]" if x.registro_id else ""
                linhas.append(f"      -{alvo} {x.mensagem}")
            if len(por_regra[regra]) > 10:
                linhas.append(f"      ... e mais {len(por_regra[regra]) - 10}")
            linhas.append("")

    pend = [v for v in rel.violacoes if v.gravidade == "pendencia"]
    if pend:
        linhas.append(f"{len(pend)} PENDENCIA(S) DE ADJUDICACAO — ver adjudication_pending.csv")

    (REPORTS / "validation_report.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")


# ------------------------------------------------------------ fluxo


def validar(
    df: pd.DataFrame,
    usar_embeddings: bool = False,
    obrigatorio: bool = False,
    encoder=None,
) -> tuple[Relatorio, object]:
    rel = Relatorio(total_registros=len(df))

    for bruto in df.to_dict("records"):
        rel.violacoes.extend(validar_registro(bruto))

    # Checagem de conjunto só depende da FORMA dos dados. Erro semântico (R02+)
    # não impede analisá-la — e reportar tudo de uma vez evita o ciclo de
    # corrigir-um-problema-e-rodar-de-novo. Só R00 (tipo/enum ausente ou
    # inválido) torna o dataframe não confiável para a análise de conjunto.
    if not any(x.regra == "R00" for x in rel.erros):
        rel.violacoes.extend(validar_conjunto(df))

    rel.resumo = resumir(df)

    agrupamento = agrupar(
        df.to_dict("records"),
        usar_embeddings=usar_embeddings,
        obrigatorio=obrigatorio,
        encoder=encoder,
    )
    rel.camada_embedding_ativa = agrupamento.camada_embedding_ativa
    rel.camada_embedding_motivo = agrupamento.camada_embedding_motivo
    rel.ambiente = agrupamento.ambiente
    for p in agrupamento.pendencias:
        rel.violacoes.append(Violacao(
            "R12p", "pendencia",
            f"{p['camada']} sim={p['similaridade']} faixa={p['faixa']} "
            f"{p['id_a']} ~ {p['id_b']}"))

    return rel, agrupamento


def construir(df: pd.DataFrame, agrupamento, destino: Path) -> None:
    """Artefatos derivados. Nunca sobrescreve a entrada."""
    destino.mkdir(parents=True, exist_ok=True)

    if agrupamento.grupos:
        pd.DataFrame(
            [
                {
                    "id": i,
                    "grupo_campanha_sugerido": g,
                    "metodo": agrupamento.metodos.get(i, ""),
                    "confianca": agrupamento.confianca.get(i, 0.0),
                }
                for i, g in agrupamento.grupos.items()
            ]
        ).to_parquet(destino / "candidate_clusters.parquet", index=False)

    pd.DataFrame(
        agrupamento.pendencias
        or [{"id_a": "", "id_b": "", "camada": "", "similaridade": "",
             "faixa": "", "decisao": ""}]
    ).to_csv(destino / "adjudication_pending.csv", index=False, encoding="utf-8-sig")

    df.to_parquet(destino / "corpus_ptbr_validado.parquet", index=False)

    publico = df[df["redistribuivel"] == True]  # noqa: E712
    pub_dir = PTBR / "public"
    pub_dir.mkdir(parents=True, exist_ok=True)
    publico.to_csv(pub_dir / "corpus_ptbr_publico.csv", index=False, encoding="utf-8")
    publico.to_json(
        pub_dir / "corpus_ptbr_publico.jsonl", orient="records",
        lines=True, force_ascii=False,
    )
    print(f"  versao publica: {len(publico)} de {len(df)} registros")


def main() -> int:
    p = argparse.ArgumentParser(description="Valida o corpus PT-BR contra o protocolo.")
    p.add_argument("--mode", choices=["check", "build"], default="check")
    p.add_argument("--input", type=Path, default=ENTRADA_PADRAO)
    p.add_argument("--output", type=Path, default=PTBR / "processed_private")
    p.add_argument("--embeddings", action="store_true",
                   help="ativa a camada 3 (exige sentence-transformers)")
    a = p.parse_args()

    if not a.input.exists():
        print(f"ERRO: entrada nao encontrada: {a.input}", file=sys.stderr)
        return 2

    df = pd.read_parquet(a.input) if a.input.suffix == ".parquet" else pd.read_csv(a.input)

    # O build gera o corpus oficial: a camada semantica e obrigatoria, senao
    # duas execucoes poderiam produzir agrupamentos diferentes.
    build = a.mode == "build"
    try:
        rel, agrupamento = validar(
            df, usar_embeddings=a.embeddings or build, obrigatorio=build
        )
    except EmbeddingIndisponivel as e:
        print(f"ERRO DE AMBIENTE: {e}", file=sys.stderr)
        return 3

    gravar_relatorios(rel)

    print(f"registros: {rel.total_registros} | erros: {len(rel.erros)}")
    for x in rel.erros[:20]:
        print(f"  {x}")
    if len(rel.erros) > 20:
        print(f"  ... e mais {len(rel.erros) - 20}")

    if not rel.consistente:
        print(f"\nFALHOU. Relatorios em {REPORTS}", file=sys.stderr)
        return 1

    if a.mode == "build":
        construir(df, agrupamento, a.output)
        print(f"artefatos em {a.output}")

    print(f"\nOK. Relatorios em {REPORTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
