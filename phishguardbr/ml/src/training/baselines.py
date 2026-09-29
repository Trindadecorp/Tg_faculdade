"""Baselines com DOIS protocolos de avaliação — Fase 3 (planejamento_tg.md §10).

O ponto do script não é bater um F1 alto. É medir a distância entre duas formas
de avaliar o mesmo modelo:

  A. SPLIT ALEATÓRIO — 80/20 estratificado. É o protocolo que quase toda a
     literatura de detecção de spam reporta. Treino e teste vêm das mesmas
     fontes, então o modelo pode acertar reconhecendo a fonte em vez da fraude.

  B. LEAVE-ONE-SOURCE-OUT (LOSO) — treina em todas as fontes menos uma, testa
     na que ficou de fora. O modelo enfrenta uma distribuição que nunca viu.

A diferença A − B é o resultado que interessa ao TG. O PhishGuard BR vai operar
sobre e-mail brasileiro, que não está em nenhuma das fontes de treino: a
condição real de uso é a do protocolo B, não a do A. Se A for muito otimista
frente a B, está medido — e não argumentado — por que construir o corpus PT-BR
é necessário, e não um capricho do trabalho.

Uso (a partir de ml/):
    python -m src.training.baselines                 # os dois protocolos
    python -m src.training.baselines --protocol random
    python -m src.training.baselines --max-features 30000
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import LinearSVC

from src.training.log_experiment import log_result

ML_DIR = Path(__file__).resolve().parents[2]
DATASET = ML_DIR / "data" / "processed" / "email_dataset_v2.parquet"
REPORT = ML_DIR / "reports" / "BASELINES_REPORT.md"

SEED = 42
DATASET_VERSION = "v2"


def _modelos() -> dict:
    """Baselines clássicos de classificação de texto.

    Sem árvores profundas nem gradient boosting sobre TF-IDF: em espaço esparso
    de dezenas de milhares de dimensões eles custam caro e não superam um linear
    bem regularizado. RandomForest entra como contraponto não linear.
    """
    return {
        "logreg": LogisticRegression(max_iter=1000, random_state=SEED),
        "linear_svc": LinearSVC(random_state=SEED),
        "multinomial_nb": MultinomialNB(),
        "random_forest": RandomForestClassifier(
            n_estimators=100, n_jobs=-1, random_state=SEED
        ),
    }


def carregar() -> pd.DataFrame:
    df = pd.read_parquet(
        DATASET, columns=["source", "channel", "raw_label", "subject", "body_text"]
    )
    df["texto"] = (
        df["subject"].fillna("") + " " + df["body_text"].fillna("")
    ).str.strip()
    df["y"] = (df["raw_label"] == "spam").astype(int)
    df = df[df["texto"].str.len() > 0].reset_index(drop=True)
    return df[["source", "channel", "texto", "y"]]


def _avaliar(modelo, X_tr, y_tr, X_te, y_te) -> dict:
    modelo.fit(X_tr, y_tr)
    pred = modelo.predict(X_te)

    # LinearSVC não tem predict_proba; a margem serve para a AUC.
    if hasattr(modelo, "predict_proba"):
        score = modelo.predict_proba(X_te)[:, 1]
    else:
        score = modelo.decision_function(X_te)

    precisao, recall, f1, _ = precision_recall_fscore_support(
        y_te, pred, average="binary", zero_division=0
    )
    auc = roc_auc_score(y_te, score) if len(np.unique(y_te)) > 1 else None
    return {
        "accuracy": accuracy_score(y_te, pred),
        "precision": precisao,
        "recall": recall,
        "f1": f1,
        "auc_roc": auc,
    }


def protocolo_aleatorio(df: pd.DataFrame, max_features: int) -> pd.DataFrame:
    print("\n=== PROTOCOLO A — split aleatorio 80/20 estratificado ===")
    tr, te = train_test_split(
        df, test_size=0.2, stratify=df["y"], random_state=SEED
    )
    vec = TfidfVectorizer(max_features=max_features, ngram_range=(1, 2), min_df=5)
    X_tr = vec.fit_transform(tr["texto"])
    X_te = vec.transform(te["texto"])
    print(f"treino {X_tr.shape[0]:,} x {X_tr.shape[1]:,} | teste {X_te.shape[0]:,}")

    linhas = []
    for nome, modelo in _modelos().items():
        m = _avaliar(modelo, X_tr, tr["y"], X_te, te["y"])
        print(f"  {nome:15s} F1={m['f1']:.4f}  P={m['precision']:.4f}  "
              f"R={m['recall']:.4f}  acc={m['accuracy']:.4f}")
        log_result(
            phase="fase3-baseline", dataset_version=DATASET_VERSION, model=nome,
            **m, notes="protocolo A: split aleatorio",
        )
        linhas.append({"modelo": nome, **m})
    return pd.DataFrame(linhas)


def protocolo_loso(df: pd.DataFrame, max_features: int) -> pd.DataFrame:
    print("\n=== PROTOCOLO B — leave-one-source-out ===")
    # Fonte sem as duas classes não serve de teste: sem spam não há o que medir.
    elegiveis = [
        f for f, g in df.groupby("source") if g["y"].nunique() == 2
    ]
    ignoradas = sorted(set(df["source"]) - set(elegiveis))
    if ignoradas:
        print(f"fontes fora do teste (uma classe so): {', '.join(ignoradas)}")

    linhas = []
    for fonte in elegiveis:
        tr = df[df["source"] != fonte]
        te = df[df["source"] == fonte]
        vec = TfidfVectorizer(max_features=max_features, ngram_range=(1, 2), min_df=5)
        X_tr = vec.fit_transform(tr["texto"])
        X_te = vec.transform(te["texto"])
        print(f"\n  teste em '{fonte}' ({len(te):,} msgs, "
              f"{te['y'].mean() * 100:.1f}% spam) | treino {len(tr):,}")

        for nome, modelo in _modelos().items():
            m = _avaliar(modelo, X_tr, tr["y"], X_te, te["y"])
            print(f"    {nome:15s} F1={m['f1']:.4f}  P={m['precision']:.4f}  "
                  f"R={m['recall']:.4f}")
            log_result(
                phase="fase3-baseline", dataset_version=DATASET_VERSION, model=nome,
                **m, notes=f"protocolo B: LOSO, teste={fonte}",
            )
            linhas.append(
                {
                    "fonte_teste": fonte,
                    "canal": te["channel"].iloc[0],
                    "modelo": nome,
                    **m,
                }
            )
    return pd.DataFrame(linhas)


def escrever_relatorio(rnd: pd.DataFrame, loso: pd.DataFrame) -> None:
    linhas = [
        "# Baselines — dois protocolos de avaliação",
        "",
        "> Gerado por `src/training/baselines.py` sobre `email_dataset_v2.parquet`.",
        "> Métricas na classe **spam**. Ver `reports/EDA_REPORT.md` para a base.",
        "",
        "## Protocolo A — split aleatório 80/20",
        "",
        "Treino e teste saem das mesmas fontes. É como a maior parte da literatura",
        "reporta, e é a condição **mais fácil** possível para o modelo.",
        "",
    ]
    if not rnd.empty:
        linhas += [rnd.round(4).to_markdown(index=False), ""]

    linhas += [
        "## Protocolo B — leave-one-source-out",
        "",
        "Cada linha treina sem aquela fonte e testa nela. O modelo enfrenta uma",
        "distribuição que nunca viu — a condição real do PhishGuard BR diante de",
        "e-mail brasileiro.",
        "",
    ]
    if not loso.empty:
        linhas += [loso.round(4).to_markdown(index=False), ""]

    if not rnd.empty and not loso.empty:
        f1_a = rnd["f1"].max()
        # Média sobre todas as fontes esconde o resultado: a distribuição é
        # bimodal, não uniforme. O agrupamento certo é por CANAL.
        melhor = (
            loso.loc[loso.groupby("fonte_teste")["f1"].idxmax()]
            [["fonte_teste", "canal", "modelo", "f1"]]
            .sort_values("f1", ascending=False)
        )
        linhas += [
            "## O achado",
            "",
            f"Melhor F1 no protocolo A (split aleatório): **{f1_a:.4f}**.",
            "",
            "Melhor F1 por fonte deixada de fora:",
            "",
            melhor.round(4).to_markdown(index=False),
            "",
        ]

        por_canal = melhor.groupby("canal")["f1"].mean()
        for canal, v in por_canal.items():
            linhas.append(f"- média do melhor F1, canal `{canal}`: **{v:.4f}**")
        linhas.append("")

        if len(por_canal) > 1:
            melhor_canal = por_canal.idxmax()
            pior_canal = por_canal.idxmin()
            linhas += [
                f"**A quebra é de canal, não de fonte.** Entre fontes de "
                f"`{melhor_canal}` o modelo transfere bem "
                f"({por_canal[melhor_canal]:.4f}), perto do que entrega no split "
                f"aleatório. Testado em `{pior_canal}`, cai para "
                f"{por_canal[pior_canal]:.4f}.",
                "",
                "Uma média sobre todas as fontes esconderia isso: ela misturaria as "
                "duas populações num único número que não descreve nenhuma delas.",
                "",
                "**Consequência para o TG.** Um modelo de texto treinado em e-mail "
                "não atende SMS — o registro é outro (mediana de 53 contra 750 "
                "caracteres). Canal precisa de modelo e de corpus próprios, e o "
                "escopo multicanal herdado do PTG depende disso.",
                "",
            ]

        linhas += [
            "### Ressalva de leitura",
            "",
            "As fontes não são independentes entre si: o `hf_seven_phishing` "
            "reempacota subconjuntos de Enron e SpamAssassin. Quando uma dessas é "
            "deixada de fora, parte da distribuição dela continua no treino, então "
            "o LOSO aqui é um limite **otimista** da transferência real.",
            "",
        ]

    REPORT.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"\nRelatorio: {REPORT}")


def reconstruir_do_csv() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Refaz o relatório a partir do results.csv, sem retreinar.

    Treinar os 4 modelos nos 2 protocolos leva ~45 min; quando só o texto do
    relatório muda, não faz sentido pagar isso de novo.
    """
    from src.training.log_experiment import RESULTS_CSV

    todos = pd.read_csv(RESULTS_CSV)
    todos = todos[todos["dataset_version"] == DATASET_VERSION]
    metricas = ["accuracy", "precision", "recall", "f1", "auc_roc"]

    rnd = todos[todos["notes"].str.contains("protocolo A", na=False)]
    rnd = rnd[["model"] + metricas].rename(columns={"model": "modelo"})

    loso = todos[todos["notes"].str.contains("protocolo B", na=False)].copy()
    loso["fonte_teste"] = loso["notes"].str.extract(r"teste=(\S+)")
    canais = (
        pd.read_parquet(DATASET, columns=["source", "channel"])
        .drop_duplicates()
        .set_index("source")["channel"]
    )
    loso["canal"] = loso["fonte_teste"].map(canais)
    loso = loso[["fonte_teste", "canal", "model"] + metricas].rename(
        columns={"model": "modelo"}
    )
    return rnd.reset_index(drop=True), loso.reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--protocol", choices=["random", "loso", "both"], default="both")
    p.add_argument("--max-features", type=int, default=30_000)
    p.add_argument(
        "--from-csv", action="store_true",
        help="so reescreve o relatorio a partir do results.csv, sem treinar",
    )
    a = p.parse_args()

    if not DATASET.exists():
        print(f"Falta {DATASET.name} — rode src.features.build_dataset primeiro.")
        return

    if a.from_csv:
        escrever_relatorio(*reconstruir_do_csv())
        return

    df = carregar()
    print(f"base: {len(df):,} mensagens | {df['y'].mean() * 100:.1f}% spam | "
          f"{df['source'].nunique()} fontes")

    rnd = pd.DataFrame()
    loso = pd.DataFrame()
    if a.protocol in ("random", "both"):
        rnd = protocolo_aleatorio(df, a.max_features)
    if a.protocol in ("loso", "both"):
        loso = protocolo_loso(df, a.max_features)

    escrever_relatorio(rnd, loso)


if __name__ == "__main__":
    main()
