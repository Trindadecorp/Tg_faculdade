# Protocolo Experimental — Validação do Corpus

> **Versão 1.1** — pré-registrado, congelado antes de qualquer execução. O
> objetivo é impedir que as regras de análise sejam escolhidas depois de ver os
> resultados.

## Histórico de versões

| versão | data | alteração |
|---|---|---|
| 1.0 | 25/09/2026 | Redação inicial. Desenho fatorial, métricas, bootstrap pareado, controles, política de resultado nulo. |
| 1.1 | 28/09/2026 | **Acrescenta a §8** — controle de reprodutibilidade do corpus estrangeiro de controle. Nenhuma hipótese, métrica, limiar ou interpretação pré-registrada dos contrastes foi alterada. |

> A alteração da v1.1 foi definida **antes** de qualquer execução de A/B/C/D.
> Trata-se de controle adicional, não de revisão de resultados.

---

## 1. Pergunta

Em que medida um corpus contextualizado em PT-BR melhora a detecção de
phishing/smishing brasileiro frente ao treino apenas com corpora estrangeiros —
e quanto disso é problema de **idioma** e quanto é de **contexto brasileiro**?

---

## 2. Desenho fatorial 2 × 2

|  | **TF-IDF** | **E5 multilíngue (congelado)** |
|---|---|---|
| **Só inglês** (108.951) | **A** | **C** |
| **Inglês + PT-BR** | **B** | **D** |

Muda **apenas** a representação e a presença do corpus brasileiro. Classificador,
hiperparâmetros, partições, limiar e conjunto de teste são idênticos nas quatro
condições.

| contraste | isola |
|---|---|
| **A → B** | efeito do corpus PT-BR, mantida a representação |
| **A → C** | efeito da representação, sem corpus PT-BR |
| **C → D** | **quanto o corpus ainda acrescenta depois de resolvido o idioma** |
| **A → D** | efeito combinado |

`C → D` responde antecipadamente à melhor pergunta que a banca pode fazer:
*"vocês precisavam construir um corpus? não bastava um modelo multilíngue?"*

### Interação, como variável formal

$$I = (D - C) - (B - A)$$

| resultado | leitura |
|---|---|
| `I ≈ 0` | contribuições **independentes** — corpus e representação atacam problemas distintos e somam |
| `I < 0` | **redundância parcial** — o encoder multilíngue já captura parte do que o corpus traria |
| `I > 0` | **sinergia** — o corpus só rende plenamente sobre representação capaz de aproveitá-lo |

`I` recebe intervalo de confiança pelo mesmo bootstrap pareado da §4. As três
leituras estão registradas **antes** da execução; escolher a narrativa depois de
ver os números invalida o pré-registro.

---

## 3. Representação — congelada

| condição | representação |
|---|---|
| A, B | TF-IDF, 30.000 features, 1–2 gramas, `min_df` 5 |
| C, D | `intfloat/multilingual-e5-base`, **congelado**, embeddings de 768 dimensões |

**Sem *fine-tuning* do encoder.** Ajustar os pesos mudaria duas coisas ao mesmo
tempo — representação *e* capacidade de aprendizado — e o fatorial deixaria de
ser interpretável. O E5 é usado só como extrator de features.

Decisões que acompanham o E5 e ficam congeladas junto:

- **Prefixo `query: `** em cada texto, conforme o *model card*.
- **Truncamento em 512 tokens.** A mediana do e-mail (752 caracteres ≈ 190
  tokens) cabe; o p90 (4.108 caracteres) não. Truncar é decisão registrada, não
  acidente — e o mesmo truncamento se aplica a todas as condições.
- **Revisão do modelo fixada por commit** no HuggingFace, registrada no
  relatório, para que a execução seja reproduzível.

Classificador em todas as condições: `LogisticRegression`, `max_iter=1000`,
semente 42.

---

## 4. Métrica e inferência estatística

- **Principal:** F1 sobre a classe `golpe`.
- **Secundárias:** precisão, recall, AUC-ROC e **FPR sobre o subconjunto
  legítimo transacional/marketing** — principal risco do produto.
- **Reporte obrigatório por canal** (`email`, `sms`, `whatsapp`) além do
  agregado. *Regra 3: canal importa.*

### Bootstrap pareado

F1 **não é uma proporção binomial** — é razão entre quantidades dependentes, e
sua distribuição amostral não tem forma fechada. Fórmula de margem de erro
binomial não se aplica a ele.

Como A, B, C e D classificam **as mesmas mensagens**, o pareamento é a escolha
correta e reduz a variância entre itens:

1. Reamostrar **itens do Gold Test** com reposição, 10.000 vezes.
2. Em cada reamostra, recalcular a métrica das quatro condições **sobre os
   mesmos itens**.
3. Registrar a distribuição de cada métrica, de cada diferença (`B−A`, `C−A`,
   `D−C`, `D−A`) e de `I`.
4. IC de 95% pelos percentis 2,5 e 97,5.

**Uma diferença só é afirmada quando o IC dela não contém zero.** O IC da
*diferença* é o que decide — não a sobreposição dos ICs individuais, que é
critério mais conservador e inadequado para dados pareados.

### Teste complementar

**McNemar** sobre a tabela de acerto/erro entre pares de condições, para a
decisão binária. Complementa o bootstrap e é o teste padrão para classificadores
comparados no mesmo conjunto.

### Sobre tamanho de amostra

Margem de erro de uma **proporção** a 95%, para calibrar expectativa sobre o
tamanho do Gold Test:

| n | p ≈ 0,50 | p ≈ 0,90 |
|---:|---:|---:|
| 150 | ±8,0 pp | ±4,8 pp |
| 300 | ±5,7 pp | ±3,4 pp |
| 500 | ±4,4 pp | ±2,6 pp |

> Esta tabela vale para **proporções** (acurácia, por exemplo) e serve apenas de
> referência de ordem de grandeza. **Não** descreve o IC do F1 nem o das
> diferenças entre condições. O IC do pareamento sobre diferenças tende a ser
> **mais estreito**, porque a variância entre itens se cancela — o poder real
> para detectar `B−A` é maior do que a tabela sugere, e será estimado
> empiricamente no bootstrap.

---

## 5. Controles

1. **Mesmo Gold Test** nas quatro condições, congelado, com hash registrado.
2. **Mesma semente** (42) em toda partição e amostragem.
3. **Vocabulário/embedding ajustado só no treino** de cada condição — ajustar no
   corpus inteiro deixaria A conhecer o léxico português.
4. **Nenhuma `familia_template` nem `grupo_campanha`** cruza partições;
   verificação automática antes de cada treino.
5. **Sem ajuste de hiperparâmetro sobre o Gold Test.** Qualquer ajuste usa
   validação interna ao treino.
6. **Limiar 0,5** em todas as condições.

---

## 6. Resultados nulos

Se `B ≈ A`, isto é, se o corpus PT-BR **não** melhorar o desempenho, o resultado
é reportado como está.

Um corpus construído com proveniência, controle de viés e protocolo
antivazamento que **não** produz ganho mensurável é achado legítimo e
informativo — indica que o gargalo é outro. A entrega do trabalho é o corpus e a
metodologia; não depende do sinal do resultado.

---

## 7. Congelamento

Este protocolo está fechado. A partir daqui, as regras não mudam — nem se A, B,
C ou D surpreenderem, nem se o resultado for nulo. Alteração exige nova versão
numerada, com data e justificativa, e a versão anterior permanece no histórico.

---

## 8. Congelamento do corpus estrangeiro de controle *(v1.1)*

**Invariante.** Antes de qualquer execução oficial de A, B, C ou D, o pipeline
verifica que o corpus estrangeiro de controle corresponde exatamente à versão
congelada. Havendo divergência, o experimento **falha antes do treinamento**.

### Por que

Se o corpus estrangeiro mudar entre execuções — por alteração de `cap`,
semente, amostragem ou reconstrução do dataset —, os contrastes `A → B` e
`C → D` deixam de isolar o efeito do corpus PT-BR. A mudança seria silenciosa: os
números continuariam saindo, apenas não significariam mais o que a §2 diz que
significam.

### A mesma versão congelada é usada em todas as condições

| condição | papel do corpus estrangeiro |
|---|---|
| **A**, **C** | conjunto de treinamento estrangeiro |
| **B**, **D** | parcela estrangeira do conjunto combinado |

### Dois hashes, com autoridades diferentes

| hash | o que é | papel na validação |
|---|---|---|
| `content_sha256` | identidade **lógica**: hash por linha sobre os campos que o experimento usa, lista ordenada, hash do conjunto — independente da ordem das linhas | **autoridade**; divergir é falha fatal |
| `artifact_sha256` | SHA-256 dos bytes do arquivo | evidência adicional; divergir com conteúdo idêntico é registrado como aviso, não falha |

A separação existe porque recompressão, nova ordem de gravação ou mudança de
versão do parquet alteram os bytes sem alterar o conjunto experimental. Tratar
isso como falha bloquearia execuções legítimas; ignorá-lo perderia evidência.

Campos que compõem o `content_sha256`: `source`, `channel`, `raw_label`,
`subject`, `body_text`. Colunas derivadas (`id`, `char_count`, contagens) não
entram — não alteram a identidade lógica do conjunto.

### O lock registra

- `linhas` e `schema` completo do dataset;
- `content_sha256` e `artifact_sha256`;
- `parametros_geracao`: script, estágio, `cap_por_celula`, semente e arquivo de
  entrada que produziram os 108.951 registros;
- `papel` de cada conjunto nas condições experimentais.

### Alteração deliberada

Substituir o lock é ato explícito e registrado: exige motivo, e o
`content_sha256` anterior fica gravado no campo `substitui`. Uma troca de
corpus de controle passa a ser, por construção, auditável.

```
python -m src.corpus.corpus_lock --gerar --motivo "<justificativa>"
python -m src.corpus.corpus_lock --verificar
```

Implementação em `src/corpus/corpus_lock.py`; a função
`exigir_corpus_congelado()` é a chamada obrigatória antes de treinar qualquer
condição. Cobertura em `tests/test_corpus_lock.py`.
