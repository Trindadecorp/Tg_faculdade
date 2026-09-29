# Baselines — dois protocolos de avaliação

> Gerado por `src/training/baselines.py` sobre `email_dataset_v2.parquet`.
> Métricas na classe **spam**. Ver `reports/EDA_REPORT.md` para a base.

## Protocolo A — split aleatório 80/20

Treino e teste saem das mesmas fontes. É como a maior parte da literatura
reporta, e é a condição **mais fácil** possível para o modelo.

| modelo         |   accuracy |   precision |   recall |     f1 |   auc_roc |
|:---------------|-----------:|------------:|---------:|-------:|----------:|
| logreg         |     0.9615 |      0.9527 |   0.9384 | 0.9455 |    0.9936 |
| linear_svc     |     0.9712 |      0.9559 |   0.9635 | 0.9597 |    0.9952 |
| multinomial_nb |     0.944  |      0.923  |   0.9194 | 0.9212 |    0.9864 |
| random_forest  |     0.9692 |      0.969  |   0.9436 | 0.9562 |    0.9949 |

## Protocolo B — leave-one-source-out

Cada linha treina sem aquela fonte e testa nela. O modelo enfrenta uma
distribuição que nunca viu — a condição real do PhishGuard BR diante de
e-mail brasileiro.

| fonte_teste         | canal   | modelo         |   accuracy |   precision |   recall |     f1 |   auc_roc |
|:--------------------|:--------|:---------------|-----------:|------------:|---------:|-------:|----------:|
| enron_spam          | email   | logreg         |     0.9627 |      0.9947 |   0.9278 | 0.9601 |    0.9969 |
| enron_spam          | email   | linear_svc     |     0.9716 |      0.9944 |   0.9465 | 0.9699 |    0.9971 |
| enron_spam          | email   | multinomial_nb |     0.953  |      0.9915 |   0.9106 | 0.9493 |    0.9968 |
| enron_spam          | email   | random_forest  |     0.9405 |      0.9944 |   0.8818 | 0.9348 |    0.9948 |
| hf_seven_phishing   | email   | logreg         |     0.8662 |      0.966  |   0.759  | 0.8501 |    0.9748 |
| hf_seven_phishing   | email   | linear_svc     |     0.8776 |      0.9614 |   0.7869 | 0.8654 |    0.9692 |
| hf_seven_phishing   | email   | multinomial_nb |     0.8758 |      0.9535 |   0.7901 | 0.8641 |    0.9753 |
| hf_seven_phishing   | email   | random_forest  |     0.8397 |      0.9699 |   0.7012 | 0.814  |    0.9647 |
| hf_zefang_phishing  | email   | logreg         |     0.9734 |      0.937  |   0.9475 | 0.9422 |    0.9952 |
| hf_zefang_phishing  | email   | linear_svc     |     0.9823 |      0.956  |   0.9673 | 0.9616 |    0.9974 |
| hf_zefang_phishing  | email   | multinomial_nb |     0.9608 |      0.884  |   0.9543 | 0.9178 |    0.9901 |
| hf_zefang_phishing  | email   | random_forest  |     0.9823 |      0.9789 |   0.943  | 0.9606 |    0.9979 |
| sms_spam_collection | sms     | logreg         |     0.4344 |      0.1584 |   0.8424 | 0.2666 |    0.6776 |
| sms_spam_collection | sms     | linear_svc     |     0.4457 |      0.1583 |   0.8201 | 0.2653 |    0.6852 |
| sms_spam_collection | sms     | multinomial_nb |     0.6476 |      0.2164 |   0.7197 | 0.3327 |    0.7505 |
| sms_spam_collection | sms     | random_forest  |     0.4645 |      0.1329 |   0.6131 | 0.2184 |    0.5141 |
| spamassassin        | email   | logreg         |     0.9028 |      0.9545 |   0.7156 | 0.818  |    0.9809 |
| spamassassin        | email   | linear_svc     |     0.8828 |      0.9828 |   0.6271 | 0.7656 |    0.967  |
| spamassassin        | email   | multinomial_nb |     0.9416 |      0.8589 |   0.9675 | 0.91   |    0.989  |
| spamassassin        | email   | random_forest  |     0.903  |      0.9928 |   0.687  | 0.8121 |    0.9954 |

## O achado

Melhor F1 no protocolo A (split aleatório): **0.9597**.

Melhor F1 por fonte deixada de fora:

| fonte_teste         | canal   | modelo         |     f1 |
|:--------------------|:--------|:---------------|-------:|
| enron_spam          | email   | linear_svc     | 0.9699 |
| hf_zefang_phishing  | email   | linear_svc     | 0.9616 |
| spamassassin        | email   | multinomial_nb | 0.91   |
| hf_seven_phishing   | email   | linear_svc     | 0.8654 |
| sms_spam_collection | sms     | multinomial_nb | 0.3327 |

- média do melhor F1, canal `email`: **0.9267**
- média do melhor F1, canal `sms`: **0.3327**

**A quebra é de canal, não de fonte.** Entre fontes de `email` o modelo transfere bem (0.9267), perto do que entrega no split aleatório. Testado em `sms`, cai para 0.3327.

Uma média sobre todas as fontes esconderia isso: ela misturaria as duas populações num único número que não descreve nenhuma delas.

**Consequência para o TG.** Um modelo de texto treinado em e-mail não atende SMS — o registro é outro (mediana de 53 contra 750 caracteres). Canal precisa de modelo e de corpus próprios, e o escopo multicanal herdado do PTG depende disso.

### Ressalva de leitura

As fontes não são independentes entre si: o `hf_seven_phishing` reempacota subconjuntos de Enron e SpamAssassin. Quando uma dessas é deixada de fora, parte da distribuição dela continua no treino, então o LOSO aqui é um limite **otimista** da transferência real.

