# Esquema do Corpus PhishGuard BR — v1

> Congelado antes da coleta. Alteração posterior exige nova versão do esquema e
> registro do motivo em `CHANGELOG.md`, para que as regras não mudem depois de
> ver resultados.

---

## 1. Campos

### Conteúdo

| campo | tipo | obrig. | descrição |
|---|---|---|---|
| `id` | uuid4 | sim | identificador único |
| `texto` | string | sim | conteúdo já anonimizado |
| `assunto` | string | não | linha de assunto (só `canal = email`) |
| `canal` | enum | sim | `email` \| `sms` \| `whatsapp` |
| `rotulo` | enum | sim | `golpe` \| `seguro` |
| `arquetipo` | enum | sim | vetor de golpe ou tipo de mensagem legítima |
| `marca` | string | não | marca citada ou imitada |

### Proveniência — quatro dimensões independentes

O erro da v0 foi colapsar em um único campo `origem` coisas que respondem a
perguntas diferentes: *é real?*, *de onde veio?*, *como foi gerado?*, *sofreu
transformação?*. Separadas:

| campo | valores | pergunta |
|---|---|---|
| `natureza` | `real` \| `sintetico` | a mensagem circulou de verdade? |
| `fonte_aquisicao` | `doacao` \| `corpus_publico` \| `coleta_propria` \| `geracao_interna` | de onde veio? |
| `metodo_geracao` | `nenhum` \| `template` \| `llm` | como foi produzida? |
| `transformacao` | `original` \| `traduzido` \| `normalizado` | foi alterada depois? |

`natureza = real` não é amarrado a `fonte_aquisicao = doacao`: uma fonte pública
de mensagens brasileiras reais é perfeitamente possível e não deve ser excluída
por definição.

### Agrupamento — controle de vazamento

| campo | tipo | descrição |
|---|---|---|
| `familia_template` | string | agrupa variantes de um mesmo template |
| `grupo_campanha` | string | agrupa mensagens **reais** da mesma campanha |

Ambos são unidades de particionamento. Ver §6.

### Governança

| campo | tipo | descrição |
|---|---|---|
| `anonimizado` | bool | passou pelo pipeline LGPD |
| `proveniencia_verificada` | bool | origem confirmada e documentada |
| `uso_pesquisa` | bool | pode ser usado internamente |
| `redistribuivel` | bool | pode ser publicado |
| `base_juridica` | enum | `consentimento` \| `legitimo_interesse` \| `pesquisa_academica` \| `dado_proprio` \| `fonte_publica` |
| `revisado` | bool | revisão humana concluída |
| `revisor` | string | iniciais |
| `particao` | enum | `treino` \| `gold_test` \| `stress_test` \| `reserva` |
| `criado_em` | date | entrada no corpus |
| `hash` | sha256 | do texto normalizado |

---

## 2. Licenciamento — dois eixos, não um

Receber um e-mail de golpe **não confere direito de republicar o texto**, que
foi escrito por terceiro. Isso é questão autoral, distinta de privacidade.

| `uso_pesquisa` | `redistribuivel` | situação típica |
|---|---|---|
| ✅ | ✅ | texto que produzimos (curado, template) |
| ✅ | ✅ | fonte pública com licença permissiva |
| ✅ | ❌ | mensagem real doada — analisável, não publicável |
| ❌ | ❌ | não entra no corpus |

O corpus publicado contém apenas `redistribuivel = true`. Os experimentos podem
usar todo o conjunto `uso_pesquisa = true`, desde que o relatório informe
quantos registros ficaram fora da versão pública, por canal e por rótulo.

---

## 3. Vocabulário controlado de `arquetipo`

**Golpe:** `pix` · `boleto` · `serasa_spc` · `receita_restituicao` · `inss` ·
`correios_taxa` · `bloqueio_bancario` · `cartao_clonado` · `premio_sorteio` ·
`whatsapp_clonado` · `vaga_emprego` · `delivery` · `conta_consumo` ·
`multa_detran` · `auxilio_governo` · `cobranca_falsa` · `suporte_tecnico` ·
`investimento` · `outro_golpe`

**Legítimo:** `transacional_banco` · `nota_fiscal` · `confirmacao_compra` ·
`newsletter` · `marketing_legitimo` · `cobranca_real` · `notificacao_servico` ·
`comunicacao_pessoal` · `comunicacao_corporativa` · `outro_legitimo`

Arquétipo novo exige acréscimo ao vocabulário e nota no `CHANGELOG.md`.

---

## 4. Regras de validação

1. `texto` não vazio, mínimo 10 caracteres.
2. `hash` inédito — dedup por texto **normalizado**. *Regra 1.*
3. `natureza = real` exige `anonimizado = true`.
4. `metodo_geracao = template` exige `familia_template` preenchida.
5. `natureza = real` exige `grupo_campanha` atribuído (ainda que singleton).
6. **`particao = gold_test` exige:**
   `natureza = real` **e** `revisado = true` **e**
   `proveniencia_verificada = true`.
   *Sintético não entra no Gold Test por construção, não por disciplina.*
7. `particao = stress_test` exige `revisado = true`.
8. `redistribuivel = true` exige `base_juridica` compatível com publicação.
9. `arquetipo` coerente com `rotulo`.

---

## 5. Tetos de balanceamento

*Regra 2 — nenhuma célula domina.*

| dimensão | teto |
|---|---|
| `arquetipo` × `rotulo` | ≤ 15% do canal |
| `marca` | ≤ 12% do canal |
| `familia_template` | ≤ 8% da partição de treino |
| `grupo_campanha` | ≤ 5% da partição de treino |

Excedente vai para `particao = reserva` e não entra em nenhum conjunto até que
outras células cresçam.

---

## 6. Particionamento e controle de vazamento

**Nenhuma `familia_template` e nenhum `grupo_campanha` pode atravessar
partições.** Verificação automática antes de cada treino; se algum grupo cruzar,
o build falha.

### Por que `grupo_campanha` é necessário

`familia_template` resolve o vazamento do sintético. O dado **real** tem o mesmo
problema, sem template para amarrá-lo. Três SMS reais da mesma campanha —
*"Sua encomenda foi taxada. Regularize…"*, *"Sua entrega foi taxada.
Regularize…"*, *"Objeto retido. Regularize…"* — não são duplicatas exatas, não
têm `template_id`, e se dois caírem no treino e um no Gold Test a métrica infla.

É a versão brasileira do que descobrimos com a Enron.

### Como o agrupamento é detectado

Pipeline em quatro camadas, em ordem de custo:

| camada | método | limiar | decide |
|---|---|---|---|
| 1 | hash do texto normalizado | igualdade | duplicata exata → descarte |
| 2 | MinHash sobre 5-gramas de caractere | Jaccard ≥ 0,70 | mesma campanha |
| 3 | similaridade de cosseno sobre embeddings | ≥ 0,90 | mesma campanha |
| 4 | revisão humana | — | casos entre 0,55–0,70 (camada 2) e 0,80–0,90 (camada 3) |

Os limiares são **pré-registrados** e não podem ser ajustados depois de ver o
resultado experimental. Alterá-los exige nova versão do esquema.

---

## 7. Formato, localização e publicação

```
ml/data/ptbr/
├── raw_private/eml/        .eml crus — NÃO VERSIONADO, dado pessoal
├── processed_private/      corpus completo anonimizado (uso_pesquisa)
└── public/                 apenas redistribuivel=true  ← versionável
```

O `.eml` cru carrega muito além do corpo: IPs em `Received`, `Message-ID`,
assinaturas DKIM, nome e endereço do titular, tokens de rastreio e de
descadastro, anexos. Ele é **evidência de proveniência** e fica fora do
versionamento — idealmente fora da árvore do Git. O corpus trabalha sobre a
representação extraída e higienizada.

**Formato de trabalho:** Parquet (`processed_private/`).
**Formato de publicação:** CSV e JSONL (`public/`) — portáveis, legíveis e
padrão em liberação de dataset. O `.gitignore` raiz bloqueia `*.parquet`, o que
já força essa separação.

**Destino da publicação:** HuggingFace Datasets ou Zenodo, com DOI. O
repositório de código não é o lugar de hospedar o corpus.

A tabela no PostgreSQL só quando a API da Fase 5 precisar ler.
