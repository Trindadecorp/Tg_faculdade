# Registro de experimentos

`results.csv` acumula uma linha por rodada de treino/validação (baseline, deep
learning, retreinos). É a evidência de evolução da ferramenta para o TG —
mesma tabela vira gráfico de evolução de métricas no relatório final.

Uso em qualquer notebook/script de treino:

```python
from src.training.log_experiment import log_result

log_result(
    phase="fase3_baseline",
    dataset_version="v1",
    model="random_forest",
    accuracy=0.94, precision=0.92, recall=0.95, f1=0.935, auc_roc=0.97,
    notes="baseline inicial, sem tuning",
)
```

Regra de regressão (herdada do cronograma do PTG): se um novo treino resultar
em F1 mais de 5% abaixo do melhor já registrado (`best_f1()` em
`log_experiment.py`), não substituir o modelo em produção — investigar antes.
