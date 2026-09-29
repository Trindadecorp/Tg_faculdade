# Protocolo de Curadoria — Corpus PhishGuard BR

> Congelado antes da coleta, junto com `CORPUS_SCHEMA.md`.

---

## 1. Dois conjuntos de avaliação, com perguntas diferentes

| conjunto | composição | congelado | responde |
|---|---|---|---|
| **Gold Test BR** | 300–500 mensagens **reais** brasileiras (`natureza = real`), curadas, anonimizadas e com proveniência verificada | sim | *Funciona no mundo real?* |
| **Synthetic Stress Test** | cenários difíceis construídos de propósito | sim | *Resiste a variação adversarial?* |

Exemplo sintético revisado por humano continua sendo sintético. Para afirmar
desempenho sobre golpe brasileiro real, o conjunto principal precisa ser real.

O Stress Test cobre deliberadamente: erros de digitação, variação regional,
urgência extrema, apelo a autoridade, mistura de idiomas, ofuscação de marca,
mensagem curta sem contexto e golpe sem link.

### Consequência de cronograma

O Gold Test depende da coleta real, que é a mais lenta e a menos controlável do
projeto. **Ela está no caminho crítico e começa imediatamente**, em paralelo
com todo o resto. Se a vazão real ficar abaixo de 300 até a data-limite, o
relatório reporta o n obtido e o intervalo de confiança correspondente — não se
completa o conjunto com sintético.

---

## 2. Papel de cada tipo de dado

Nenhum é "melhor"; têm funções experimentais distintas.

**Dados reais** têm maior **validade ecológica** — refletem a distribuição que o
sistema encontrará em uso. Por isso sustentam a avaliação de generalização.

**Dados sintéticos** permitem ampliar de forma **controlada e mensurável** a
diversidade de cenários no treino, cobrindo vetores que a coleta real ainda não
capturou.

---

## 3. Fluxo por origem

### 3.1 Mensagens reais

1. Exportar da caixa de spam/entrada (Gmail: ⋮ → "Baixar mensagem original").
2. Salvar o `.eml` **cru** em `ml/data/ptbr/raw_private/eml/` — pasta não
   versionada. Ele é a evidência de proveniência e **nunca** entra no corpus
   nesse estado.
3. Passar pelo pipeline de anonimização: e-mails, telefones, CPF, nomes
   próprios, números de conta, tokens de rastreio e de descadastro viram
   marcadores. Cabeçalhos `Received`, `Message-ID` e assinaturas DKIM são
   descartados — carregam IP e identificador do titular.
4. Conferência manual da anonimização, **registro a registro**. Nenhum dado
   pessoal residual.
5. Classificar `arquetipo`, `marca`, `base_juridica`, `redistribuivel`,
   `proveniencia_verificada`.
6. Atribuir `grupo_campanha` pelo pipeline de agrupamento (§6 do esquema),
   com adjudicação humana dos casos na faixa de fronteira.
7. Dois revisores independentes atribuem `rotulo`.

> **Por que o `.eml` cru não vai para o repositório.** Ele carrega IPs em
> `Received`, `Message-ID`, assinaturas DKIM, nome e endereço do titular, tokens
> de rastreio, links personalizados e anexos. Subir isso e perceber depois é o
> acidente clássico de publicação de corpus. O `.gitignore` bloqueia
> `raw_private/`, `processed_private/`, `*.eml` e `*.mbox` — verificado com
> `git check-ignore`.

### 3.2 Curadoria assistida

1. Geração com variação deliberada de arquétipo, marca, registro e canal.
2. Revisão humana integral — plausibilidade, adequação ao arquétipo, ausência
   de repetição formulaica.
3. Descarte de exemplo que "soe artificial" mesmo estando correto.

### 3.3 Expansão por template

1. Template escrito à mão, com lacunas e `familia_template` declarada.
2. Expansão combinatória com semente fixa (reprodutível).
3. Amostragem de 5% para revisão humana; se ≥ 10% da amostra for rejeitada, a
   família inteira volta para reescrita.

---

## 4. Critérios de rótulo

**`golpe`** — a mensagem busca induzir o destinatário a ação prejudicial:
entregar credencial ou dado pessoal, efetuar pagamento indevido, instalar
programa, ou estabelecer contato por canal controlado pelo fraudador.

**`seguro`** — comunicação legítima, ainda que comercial, insistente ou
indesejada. **Marketing agressivo não é golpe.** Essa distinção é deliberada: é
o principal risco de falso positivo do produto.

### Casos de fronteira

| situação | decisão |
|---|---|
| Cobrança real com tom ameaçador | `seguro` |
| Promoção legítima com urgência falsa ("só hoje") | `seguro` |
| Phishing que imita marca inexistente | `golpe` |
| Corrente/boato sem pedido de ação | `seguro`, arquétipo `outro_legitimo` |
| Mensagem truncada, sem contexto para decidir | **descartar**, não rotular |

---

## 5. Concordância entre revisores

- Gold Test e Stress Test: **dois revisores independentes** em 100% dos
  registros.
- Treino: revisão simples, exceto amostra de 10% em dupla para aferição.
- Discordância resolvida por terceiro revisor; se persistir, o registro é
  **descartado** — não entra com rótulo duvidoso.
- Reportar **Kappa de Cohen** entre revisores no relatório final. Kappa abaixo
  de 0,70 indica critério mal definido e obriga revisão deste protocolo.

---

## 6. Congelamento

Gold Test e Stress Test são congelados **antes** de qualquer execução das
condições experimentais, e o hash do arquivo é registrado. Nenhum exemplo é
adicionado, removido ou rerrotulado depois — inclusive, e especialmente, quando
o modelo errar nele.
