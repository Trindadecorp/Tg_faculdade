"""Registro de experimentos — evidência de evolução do modelo para o TG.

Cada chamada a log_result() grava uma linha em ml/experiments/results.csv.
Convenção do PTG (§3.2.5, §3.2.7): toda rodada de treino/validação registra
suas métricas para permitir comparação entre versões e detectar regressão
(gatilho de retreino: queda de F1 > 5% em relação à melhor versão registrada).
"""
import csv
import datetime
from pathlib import Path

RESULTS_CSV = Path(__file__).resolve().parents[2] / "experiments" / "results.csv"


def log_result(
    phase: str,
    dataset_version: str,
    model: str,
    accuracy: float,
    precision: float,
    recall: float,
    f1: float,
    auc_roc: float | None = None,
    notes: str = "",
) -> None:
    with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(
            [
                datetime.date.today().isoformat(),
                phase,
                dataset_version,
                model,
                accuracy,
                precision,
                recall,
                f1,
                auc_roc if auc_roc is not None else "",
                notes,
            ]
        )


def best_f1() -> float:
    """Maior F1 já registrado — usar como referência para o gatilho de regressão."""
    with open(RESULTS_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return 0.0
    return max(float(r["f1"]) for r in rows)
