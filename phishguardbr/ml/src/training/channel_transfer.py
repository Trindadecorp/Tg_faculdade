"""Matriz de transferência entre canais — e-mail x SMS.

Contribuição central do trabalho. A bateria de baselines (`baselines.py`) mostrou
que um modelo treinado em e-mail colapsa ao ser testado em SMS. Isso sozinho não
basta: pode ser que SMS simplesmente seja uma tarefa difícil. O experimento aqui
separa as duas explicações, variando o conjunto de TREINO e mantendo fixos os
conjuntos de TESTE:

                    | teste: e-mail | teste: SMS
    treino: e-mail  |      (a)      |    (b)        <- se (a) alto e (b) baixo,
    treino: SMS     |      (c)      |    (d)           a falha é de transferência
    treino: ambos   |      (e)      |    (f)           e não de dificuldade

Leitura esperada: (d) alto prova que SMS é aprendível; (b) baixo com (d) alto
prova que o conhecimento de e-mail não transfere. A linha "ambos" verifica se
juntar os canais num único modelo recupera o desempenho ou se degrada os dois.

Uso (a partir de ml/):
    python -m src.training.channel_transfer
"""
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import LinearSVC

from src.training.log_experiment import log_result

ML_DIR = Path(__file__).resolve().parents[2]
DATASET = ML_DIR / "data" / "processed" / "email_dataset_v2.parquet"
REPORT = ML_DIR / "reports" / "CHANNEL_TRANSFER_REPORT.md"

SEED = 42
MAX_FEATURES = 30_000


def _modelos() -> dict:
    # Só modelos lineares/NB: são rápidos em matriz esparsa e a bateria roda
    # 3 treinos x 2 testes x N modelos.
    return {
        "logreg": LogisticRegression(max_iter=1000, random_state=SEED),
        "linear_svc": LinearSVC(random_state=SEED),
        "multinomial_nb": MultinomialNB(),
    }


def carregar() -> pd.DataFrame:
    df = pd.read_parquet(
        DATASET, columns=["source", "channel", "raw_label", "subject", "body_text"]
    )
    df["texto"] = (df["subject"].fillna("") + " " + df["body_text"].fillna("")).str.strip()
    df["y"] = (df["raw_label"] == "spam").astype(int)
    return df[df["texto"].str.len() > 0][["channel", "texto", "y"]].reset_index(drop=True)


def _avaliar(modelo, X_tr, y_tr, X_te, y_te) -> dict:
    modelo.fit(X_tr, y_tr)
    pred = modelo.predict(X_te)
    score = (
        modelo.predict_proba(X_te)[:, 1]
        if hasattr(modelo, "predict_proba")
        else modelo.decision_function(X_te)
    )
    p, r, f1, _ = precision_recall_fscore_support(
        y_te, pred, average="binary", zero_division=0
    )
    return {
        "accuracy": (pred == y_te).mean(),
        "precision": p,
        "recall": r,
        "f1": f1,
        "auc_roc": roc_auc_score(y_te, score) if y_te.nunique() > 1 else None,
    }


def main() -> None:
    if not DATASET.exists():
        print(f"Falta {DATASET.name} — rode src.features.build_dataset.")
        return

    df = carregar()
    email = df[df["channel"] == "email"]
    sms = df[df["channel"] == "sms"]
    print(f"e-mail: {len(email):,} ({email['y'].mean() * 100:.1f}% spam)")
    print(f"SMS:    {len(sms):,} ({sms['y'].mean() * 100:.1f}% spam)")

    # Testes fixos: toda linha da matriz é avaliada no MESMO conjunto, senão os
    # números das linhas não são comparáveis entre si.
    em_tr, em_te = train_test_split(
        email, test_size=0.2, stratify=email["y"], random_state=SEED
    )
    sm_tr, sm_te = train_test_split(
        sms, test_size=0.2, stratify=sms["y"], random_state=SEED
    )
    ambos_tr = pd.concat([em_tr, sm_tr])
    print(f"\ntreinos: e-mail {len(em_tr):,} | SMS {len(sm_tr):,} | ambos {len(ambos_tr):,}")
    print(f"testes:  e-mail {len(em_te):,} | SMS {len(sm_te):,}")

    treinos = {"e-mail": em_tr, "SMS": sm_tr, "ambos": ambos_tr}
    testes = {"e-mail": em_te, "SMS": sm_te}

    linhas = []
    for nome_tr, tr in treinos.items():
        # Vocabulário ajustado só no treino daquela célula — se fosse ajustado
        # no corpus inteiro, o modelo de SMS já conheceria o léxico do e-mail.
        vec = TfidfVectorizer(max_features=MAX_FEATURES, ngram_range=(1, 2), min_df=2)
        X_tr = vec.fit_transform(tr["texto"])
        print(f"\n=== treino: {nome_tr} ({X_tr.shape[0]:,} x {X_tr.shape[1]:,}) ===")

        for nome_te, te in testes.items():
            X_te = vec.transform(te["texto"])
            print(f"  -> teste: {nome_te} ({len(te):,})")
            for nome_m, modelo in _modelos().items():
                m = _avaliar(modelo, X_tr, tr["y"], X_te, te["y"])
                print(f"     {nome_m:15s} F1={m['f1']:.4f}  P={m['precision']:.4f}  "
                      f"R={m['recall']:.4f}  AUC={m['auc_roc']:.4f}")
                log_result(
                    phase="fase3-canal", dataset_version="v2", model=nome_m, **m,
                    notes=f"treino={nome_tr}, teste={nome_te}",
                )
                linhas.append(
                    {"treino": nome_tr, "teste": nome_te, "modelo": nome_m, **m}
                )

    res = pd.DataFrame(linhas)
    matriz = (
        res.loc[res.groupby(["treino", "teste"])["f1"].idxmax()]
        .pivot(index="treino", columns="teste", values="f1")
        .reindex(index=["e-mail", "SMS", "ambos"], columns=["e-mail", "SMS"])
    )
    print("\n=== MATRIZ (melhor F1 por celula) ===")
    print(matriz.round(4).to_string())

    escrever_relatorio(res, matriz, em_tr, sm_tr, em_te, sm_te)


def escrever_relatorio(res, matriz, em_tr, sm_tr, em_te, sm_te) -> None:
    b = matriz.loc["e-mail", "SMS"]
    d = matriz.loc["SMS", "SMS"]
    a = matriz.loc["e-mail", "e-mail"]
    f = matriz.loc["ambos", "SMS"]
    e = matriz.loc["ambos", "e-mail"]

    linhas = [
        "# Transferência entre canais — e-mail × SMS",
        "",
        "> Gerado por `src/training/channel_transfer.py`. Métricas na classe spam.",
        f"> Treino: e-mail {len(em_tr):,} | SMS {len(sm_tr):,}. "
        f"Teste: e-mail {len(em_te):,} | SMS {len(sm_te):,}.",
        "",
        "Os conjuntos de teste são fixos em todas as linhas; varia apenas o treino.",
        "O vocabulário TF-IDF é ajustado somente sobre o treino de cada célula.",
        "",
        "## Matriz (melhor F1 por célula)",
        "",
        matriz.round(4).to_markdown(),
        "",
        "## Leitura",
        "",
        f"**SMS é aprendível.** Treinado no próprio canal, o modelo atinge F1 "
        f"**{d:.4f}** sobre SMS. A falha do modelo de e-mail nesse canal não se "
        f"explica por dificuldade intrínseca da tarefa.",
        "",
        f"**O conhecimento de e-mail não transfere.** O mesmo teste de SMS, "
        f"servido por um modelo treinado em e-mail, cai para F1 **{b:.4f}** — "
        f"contra **{a:.4f}** que esse modelo entrega no seu próprio canal. A "
        f"queda é de transferência, não de tarefa.",
        "",
        f"**Treinar nos dois canais junto.** O modelo misto entrega F1 "
        f"**{f:.4f}** em SMS e **{e:.4f}** em e-mail.",
        "",
    ]

    if f >= d * 0.95 and e >= a * 0.95:
        linhas.append(
            "Juntar os canais preserva o desempenho em ambos, o que sugere que um "
            "único modelo com corpus dos dois canais é viável — desde que o corpus "
            "de cada canal exista. O que não funciona é extrapolar de um canal "
            "para o outro sem dados."
        )
    else:
        prop_sms = len(sm_tr) / (len(em_tr) + len(sm_tr)) * 100
        linhas += [
            "O modelo misto não recupera o desempenho dos modelos dedicados em "
            "pelo menos um dos canais.",
            "",
            f"**Diagnóstico da linha `ambos`.** O SMS representa apenas "
            f"{prop_sms:.1f}% do treino misto ({len(sm_tr):,} de "
            f"{len(em_tr) + len(sm_tr):,}). A queda em SMS pode, portanto, ser "
            "efeito do mesmo desbalanceamento que a §5.5 trata por teto de "
            "amostragem — e não uma incompatibilidade de fundo entre os canais. "
            "Distinguir as duas hipóteses exige repetir esta linha com o corpus "
            "de SMS ampliado ou com reponderação por canal; enquanto isso não "
            "for feito, a conclusão segura é a da diagonal: **cada canal precisa "
            "do seu próprio corpus**.",
        ]

    linhas += [
        "",
        "## Consequência para o produto",
        "",
        "O escopo multicanal exige **corpus por canal**, não apenas modelo por "
        "canal. Como não existe corpus público de phishing/smishing em PT-BR para "
        "nenhum dos dois, a construção do corpus brasileiro é pré-requisito do "
        "escopo multicanal, e não um complemento dele.",
        "",
        "## Limitação",
        "",
        f"O corpus de SMS disponível é pequeno ({len(sm_tr) + len(sm_te):,} "
        "mensagens, fonte única — SMS Spam Collection/UCI) e em inglês. Os "
        "resultados da linha SMS devem ser lidos como indicativos; sua "
        "confirmação depende do corpus PT-BR de SMS previsto na Fase 5.",
        "",
        "## Detalhamento",
        "",
        res.round(4).to_markdown(index=False),
        "",
    ]
    REPORT.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"\nRelatorio: {REPORT}")


if __name__ == "__main__":
    main()
