"""Treina e persiste os modelos que o PhishRisk Engine carrega em produção.

Diferente de `baselines.py`, que compara alternativas e descarta os modelos,
aqui cada artefato é salvo em `ml/models/` junto com os metadados necessários
para auditoria (versão do dataset, métricas, data, distribuição de treino).

Duas decisões de projeto ficam registradas aqui:

1. MODELO POR CANAL. O experimento de transferência
   (`reports/CHANNEL_TRANSFER_REPORT.md`) mostrou colapso simétrico entre e-mail
   e SMS — F1 cai de 0,97 para 0,35 e de 0,96 para 0,38 nas duas direções. Um
   modelo único não atende os dois canais, então são treinados dois, e o motor
   roteia pela origem da mensagem.

2. REGRESSÃO LOGÍSTICA NO MÓDULO NLP, apesar de a SVM linear ter obtido F1
   ligeiramente maior (0,9723 contra 0,9642). O motor combina módulos por média
   ponderada, o que exige probabilidade calibrada, e não margem de decisão. Uma
   SVM entrega margem sem escala probabilística; usá-la exigiria calibração
   posterior, com custo adicional e sem ganho prático nesse delta.

Uso (a partir de ml/):
    python -m src.training.train_production
"""
import datetime
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from src.features.url_features import extrair_lote
from src.training.log_experiment import log_result

ML_DIR = Path(__file__).resolve().parents[2]
CORPUS = ML_DIR / "data" / "processed" / "email_dataset_v2.parquet"
URLS = ML_DIR / "data" / "processed" / "url_dataset_v1.parquet"
MODELS = ML_DIR / "models"

SEED = 42


def _metricas(modelo, X_te, y_te) -> dict:
    pred = modelo.predict(X_te)
    prob = modelo.predict_proba(X_te)[:, 1]
    p, r, f1, _ = precision_recall_fscore_support(
        y_te, pred, average="binary", zero_division=0
    )
    return {
        "accuracy": float((pred == y_te).mean()),
        "precision": float(p),
        "recall": float(r),
        "f1": float(f1),
        "auc_roc": float(roc_auc_score(y_te, prob)),
    }


def _salvar(modelo, nome: str, metricas: dict, extra: dict) -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, MODELS / f"{nome}.joblib")
    meta = {
        "nome": nome,
        "treinado_em": datetime.date.today().isoformat(),
        "metricas_holdout": metricas,
        **extra,
    }
    (MODELS / f"{nome}.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  salvo: models/{nome}.joblib")


def treinar_nlp(df: pd.DataFrame, canal: str) -> None:
    sub = df[df["channel"] == canal]
    if len(sub) < 200:
        print(f"[{canal}] amostras insuficientes ({len(sub)}) — pulado")
        return

    print(f"\n=== NLP / canal {canal} ({len(sub):,} msgs, "
          f"{sub['y'].mean() * 100:.1f}% golpe) ===")
    tr, te = train_test_split(sub, test_size=0.2, stratify=sub["y"], random_state=SEED)

    # min_df menor no SMS: o corpus é ~20x menor, min_df=5 descartaria quase tudo.
    min_df = 5 if canal == "email" else 2
    pipe = Pipeline(
        [
            ("tfidf", TfidfVectorizer(max_features=30_000, ngram_range=(1, 2), min_df=min_df)),
            ("clf", LogisticRegression(max_iter=1000, random_state=SEED)),
        ]
    )
    pipe.fit(tr["texto"], tr["y"])
    m = _metricas(pipe, te["texto"], te["y"])
    print(f"  F1={m['f1']:.4f}  P={m['precision']:.4f}  R={m['recall']:.4f}  "
          f"AUC={m['auc_roc']:.4f}")

    log_result(
        phase="fase4-producao", dataset_version="v2", model=f"nlp_{canal}", **m,
        notes=f"modelo de producao, canal={canal}",
    )
    _salvar(
        pipe, f"nlp_{canal}", m,
        {
            "canal": canal,
            "dataset": CORPUS.name,
            "n_treino": len(tr),
            "n_teste": len(te),
            "prop_golpe_treino": float(tr["y"].mean()),
            "algoritmo": "TF-IDF(1-2gram) + LogisticRegression",
        },
    )


def treinar_url() -> None:
    if not URLS.exists():
        print("\n[url] dataset ausente — rode src.features.build_url_dataset")
        return

    df = pd.read_parquet(URLS).reset_index(drop=True)
    print(f"\n=== URL ({len(df):,} URLs, {df['is_malicious'].mean() * 100:.1f}% maliciosas) ===")
    X = extrair_lote(df["url"])
    y = df["is_malicious"]
    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=SEED
    )

    # Floresta aqui, e não modelo linear: as features de URL são poucas (26),
    # densas e com interação forte (IP + porta + TLD), onde a árvore ganha.
    rf = RandomForestClassifier(n_estimators=300, n_jobs=-1, random_state=SEED)
    rf.fit(Xtr, ytr)
    m = _metricas(rf, Xte, yte)
    print(f"  F1={m['f1']:.4f}  P={m['precision']:.4f}  R={m['recall']:.4f}  "
          f"AUC={m['auc_roc']:.4f}")

    log_result(
        phase="fase4-producao", dataset_version="url_v1", model="url_rf", **m,
        notes="modelo de producao, modulo de URL",
    )
    _salvar(
        rf, "url", m,
        {
            "dataset": URLS.name,
            "n_treino": len(Xtr),
            "n_teste": len(Xte),
            "features": list(X.columns),
            "algoritmo": "RandomForest(300) sobre features lexico-estruturais",
            "ressalva": (
                "Negativos vem de corpora de 2002 e positivos de feeds atuais; "
                "ver URL_MODEL_REPORT.md. O limiar deve ser calibrado por tipo "
                "de ameaca (recall 0,52 em phishing quando treinado so em malware)."
            ),
        },
    )


def main() -> None:
    if not CORPUS.exists():
        print(f"Falta {CORPUS.name} — rode src.features.build_dataset.")
        return

    df = pd.read_parquet(
        CORPUS, columns=["channel", "raw_label", "subject", "body_text"]
    )
    df["texto"] = (df["subject"].fillna("") + " " + df["body_text"].fillna("")).str.strip()
    df["y"] = (df["raw_label"] == "spam").astype(int)
    df = df[df["texto"].str.len() > 0]

    for canal in sorted(df["channel"].unique()):
        treinar_nlp(df, canal)
    treinar_url()

    print(f"\nArtefatos em {MODELS}")


if __name__ == "__main__":
    main()
