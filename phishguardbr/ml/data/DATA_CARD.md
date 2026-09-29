# Data Card — Corpus PhishGuard BR

> Ver planejamento_tg.md §1.1 e §5.1-§5.3.

## Contribuição — gap de corpus público em PT-BR

Não existe corpus público de phishing/smishing em português brasileiro. Todos os datasets
consolidados abaixo são em inglês, sobre contexto americano/europeu. Este TG assume a
construção do corpus PT-BR (linha "Doações/sintético PT-BR" abaixo) como contribuição própria
do trabalho, não apenas como insumo de treino — validada ao final pelo desempenho do
PhishGuard BR sobre ela.

## Fontes coletadas

| Fonte | Status | Volume | Licença | Idioma |
|---|---|---|---|---|
| SMS Spam Collection (UCI) | ✅ baixado `ml/data/raw/sms_spam_collection/` | 5.574 (4.827 ham / 747 spam) | CC BY 4.0 | EN |
| SpamAssassin Public Corpus | ✅ baixado `ml/data/raw/spamassassin/` | 9.354 arquivos | Apache | EN |
| Enron Email Dataset (cru, host CMU) | ✅ baixado `ml/data/raw/enron/` | 517.401 (100% ham — correspondência corporativa) | público (litígio FERC) | EN |
| Enron-Spam (AUEB — Metsis/Androutsopoulos/Paliouras) | ✅ baixado `ml/data/raw/enron_spam/` | 33.716 (ham+spam pré-rotulado) | acadêmica | EN |
| Hugging Face `seven-phishing-email-datasets` (unifica Assassin+CEAS-08+Enron+**Ling**+**TREC-05/06/07**) | ✅ baixado `ml/data/raw/hf_seven_phishing/` | 203.017 | verificar por sub-fonte | EN |
| Hugging Face `phishing-email-dataset` (zefang-liu, espelho Kaggle) | ✅ baixado `ml/data/raw/hf_zefang_phishing/` | 18.650 | LGPL-3.0 | EN |
| OpenPhish (feed de URLs ativas) | ✅ baixado `ml/data/raw/openphish/` → `malicious_urls_v1.csv` | 300 URLs (snapshot; feed muda a cada 12h) | comunitária | — |
| URLhaus / abuse.ch (feed de URLs) | ✅ baixado `ml/data/raw/urlhaus/` → `malicious_urls_v1.csv` | 13.494 URLs — **malware, não phishing** (ver `threat_type`) | comunitária | — |
| Mishra & Soni — DSmishSMS (Mendeley) | ⬜ baixar manualmente ([link](https://data.mendeley.com/datasets/f45bkkt8pr/1)) | ~5.971 | CC BY 4.0 | EN |
| Nazario Phishing Corpus | ⬜ manual — Academic Torrents (exige cliente torrent, [link](https://academictorrents.com/details/a77cda9a9d89a60dbdfbe581adf6e2df9197995a)) | ~4.500–11.500 | verificar | EN |
| Fraudulent E-mail Corpus (419) | ⬜ manual — só via Kaggle com conta ([link](https://www.kaggle.com/datasets/rtatman/fraudulent-email-corpus)) | ~4.000 | CC0 | EN |
| CSDMC2010 SPAM Corpus | ⬜ manual — sem host oficial estável, buscar espelho e confirmar licença | ~4.300 | acadêmica (ICONIP 2010) | EN |
| **Corpus sintético PT-BR** | ⬜ script pronto (`generate_synthetic.py`), aguardando `ANTHROPIC_API_KEY` + revisão humana | meta ~6.000 | própria | **PT-BR** |
| **Doações consentidas PT-BR** | ⬜ depende do fluxo LGPD (Fase 5/6) | meta ~1.000 | própria (consentimento) | **PT-BR** |

**Consolidado** (`email_dataset_v1.parquet`, dedupe por texto **exato**): 782.741 registros.

## Volume real após a EDA — atenção ao ler os números acima

A coluna "Volume" da tabela é o volume **bruto** de cada fonte. A EDA
(`reports/EDA_REPORT.md`) mostrou que a dedupe por texto exato deixou passar
**293.368 cópias** (37,5% da base): o mesmo texto com diferença só de
capitalização ou espaçamento contava como registro novo. Deduplicando por texto
normalizado, o corpus real é de **489.369 textos distintos**, não 782.741.

| Fonte | Bruto | Texto novo que acrescenta | % duplicado |
|---|---:|---:|---:|
| enron | 517.401 | **244.429** | 52,8% |
| hf_seven_phishing | 203.008 | **195.991** | 3,5% |
| enron_spam | 30.494 | **30.112** | 1,3% |
| hf_zefang_phishing | 17.502 | **7.739** | 55,8% |
| spamassassin | 9.165 | **5.957** | 35,0% |
| sms_spam_collection | 5.171 | **5.145** | 0,5% |

Causas, por fonte:

- **enron (52,8%)** — estrutura de maildir: o mesmo e-mail está na pasta `sent`
  do remetente e na `inbox` de cada destinatário.
- **hf_zefang_phishing (55,8%)** — espelho de Kaggle que reempacota material já
  presente em outras fontes; acrescenta só 7.739 textos próprios.
- **spamassassin (35,0%)** — causado pelo nosso `download_datasets.py`, que baixa
  9 arquivos do corpus com sobreposição entre si (`20021010_easy_ham` ×
  `20030228_easy_ham`, `spam_2` em duas datas).

> A duplicata é atribuída à fonte lida **depois**, então a coluna "% duplicado"
> mistura repetição interna com sobreposição entre fontes. O número confiável é
> "texto novo que acrescenta".

**Viés documentado.** O Enron é 66,1% do bruto e continua sendo ~50% do corpus
deduplicado, com **zero spam**. A seção 7 da EDA mostra que os termos mais
preditivos de "legítimo" são vocabulário interno da Enron (`ect`, `hou`,
`kaminski`, `forwarded`) — não marcadores de legitimidade. Por isso o dataset de
treino (`email_dataset_v2.parquet`) aplica **teto por célula fonte × rótulo**,
via `src/features/build_dataset.py`.

## Benchmarks (vetores de features — não entram no corpus de texto)

Não contêm o texto das mensagens, apenas features numéricas já extraídas, então
não alimentam TF-IDF/LLM. Valem como **comparação com a literatura** (ambos têm
resultados publicados) e, no caso do PhishingWebsites, por descrever features de
URL alinhadas ao módulo §6.3. Baixados via `download_benchmarks.py` (OpenML).

| Benchmark | OpenML id | Volume | Distribuição |
|---|---|---|---|
| Spambase | 44 | 4.601 × 58 | 2.788 ham / 1.813 spam |
| PhishingWebsites | 4534 | 11.055 × 31 | 6.157 legítimo / 4.898 phishing |

## Pendências antes do treino

- **Anonimização** obrigatória (LGPD) em qualquer dado real antes de persistir em disco.
- **Split**: teste final sempre exclusivamente e-mail PT-BR (nunca visto em treino).
- **Licença**: confirmar termo de uso de cada fonte antes de publicar o corpus final.
