# PhishGuard BR — Briefing do TG

> Documento de contexto. Última atualização: 25/09/2026.
> Autores: Pedro Trindade e Leonardo Trindade — Fatec Indaiatuba, ADS.
> Orientação: Prof. Michel Moron Munhoz.

---

## O que estamos construindo

**Um corpus público para detecção de phishing e smishing no contexto
brasileiro** — organizado por canal, com proveniência rastreável por registro e
protocolo de particionamento à prova de vazamento.

Os conjuntos amplamente usados na literatura são em inglês e descrevem golpes
americanos e europeus dos anos 2000. Nenhum deles contém PIX, boleto, Serasa,
gov.br, INSS ou Correios — que são os vetores usados contra brasileiros.

Um detector acompanha a base, mas o papel dele é **instrumento de validação**:
serve para medir, por comparação controlada, o que a base acrescenta. A entrega
central do trabalho é o corpus.

> **Sobre a alegação de novidade.** O trabalho **não** afirma ser o primeiro
> corpus em português. Existem conjuntos adjacentes — traduções automáticas do
> SMS Spam Collection, corpora de smishing lusófonos de outros países, e
> coletâneas multilíngues recentes de golpes. O diferencial reivindicado é a
> combinação de: contexto **brasileiro** (marcas, órgãos e vetores locais),
> separação **por canal**, **proveniência** rastreável por registro e
> **metodologia de construção documentada**. Antes da redação final é
> obrigatório levantar sistematicamente os trabalhos relacionados e preencher a
> tabela comparativa da seção correspondente — citações de terceiros não
> verificadas na fonte não entram na monografia.

---

## Arquitetura de dados — três conjuntos com papéis distintos

O corpus brasileiro **não substitui** os corpora estrangeiros. Eles são o grupo
de controle, e sem eles a pergunta central do trabalho deixa de existir: *quanto
se ganha ao acrescentar contexto brasileiro ao que já existe?*

| conjunto | volume | papel |
|---|---:|---|
| **Corpus estrangeiro** | 108.951 | baseline e controle — treina A e C, e também entra em B e D |
| **Corpus PT-BR** | meta ~6.000 | mede o ganho de contexto brasileiro — entra em B e D |
| **Gold Test PT-BR** | 300–500 | prova final; real, brasileiro, **nunca usado em treino** |

```
CORPUS ESTRANGEIRO (108.951, congelado)
         │
         ├────────────────────────────► A  (TF-IDF + estrangeiro)
         ├────────────────────────────► C  (E5     + estrangeiro)
         │
         └──┐
            │   CORPUS PT-BR (em construção)
            │        ├── .eml brasileiros ── parser ── anonimização ── curadoria
            │        ├── SMS / WhatsApp reais
            │        ├── templates e sintéticos PT-BR
            │        └── legítimos brasileiros (controle de falso positivo)
            │              │
            └──────────────┴───────────► B  (TF-IDF + estrangeiro + PT-BR)
                                        ► D  (E5     + estrangeiro + PT-BR)

                    GOLD TEST PT-BR  ──►  A, B, C e D fazem a MESMA prova
```

**O pipeline de `.eml` é uma das fontes do corpus PT-BR, não o corpus inteiro.**
Os corpora estrangeiros já passaram por coleta, parsing, deduplicação e
balanceamento próprios; eles **não** são reprocessados pelo parser de `.eml`.

### O corpus estrangeiro tem dois papéis, não um

**Dado experimental.** Continua treinando as quatro condições.

**Evidência metodológica.** Foi trabalhando nele que as regras de construção do
corpus brasileiro foram descobertas — deduplicação normalizada, teto por
origem × rótulo, separação por canal, `familia_template` e `grupo_campanha`.
Cada regra da seção seguinte veio de um problema encontrado ali.

Por isso o percurso em inglês não é trabalho descartado nem etapa anterior: é a
fundamentação do que se constrói agora.

---

## Por que essa é a entrega certa

O trabalho começou tentando construir o detector. Foi tentando isso que ficou
claro que o problema não era algoritmo — era dado. O percurso abaixo é o que
fundamenta a decisão, e cada tropeço virou uma regra de construção.

### Etapa 1 — Reunir o que existe

Para ensinar um computador a reconhecer golpe é preciso mostrar milhares de
exemplos já rotulados. Buscamos as bases públicas que pesquisadores montaram:
**7 fontes, 782.741 mensagens**.

Algumas vieram fáceis, outras deram trabalho — um servidor universitário grego
com certificado quebrado, um arquivo de 423 MB que caía no meio do download.

### Etapa 2 — Limpar, e a primeira surpresa

Das 782 mil, **293.368 eram cópias repetidas — 37,5%**. A maior causa: a base
Enron guarda o mesmo e-mail na pasta "enviados" de quem mandou *e* na "caixa de
entrada" de cada destinatário. Sobraram **489.369** mensagens distintas.

Importa porque, se a mesma mensagem aparece no material de estudo *e* na prova,
o sistema parece melhor do que é.

> **Regra 1.** Deduplicação por texto exato não basta. Normalizar (minúsculas,
> espaços) antes de comparar.

### Etapa 3 — Descobrir que a base estava viciada

A surpresa mais séria. Olhando quais palavras mais indicavam "mensagem
legítima", apareceram: `enron`, `houston`, `kaminski`, `jeff`, `ect`. São nomes
de funcionários e siglas internas de **uma empresa que faliu em 2001**.

O sistema não aprendia a reconhecer fraude. Aprendia a reconhecer *a Enron* —
que sozinha era 66% da base e não tinha um único golpe dentro.

Corrigimos limitando quanto cada fonte pode contribuir. A base caiu para
**108.951** mensagens, a Enron de 66% para 18%, e a proporção de golpes subiu
de 15% para 36%. Menos dados, muito mais confiáveis.

> **Regra 2.** Nenhuma origem pode dominar, e o teto tem de ser por
> **origem × rótulo** — não por origem. A Enron era 100% legítima, então limitar
> só o volume dela deixaria a correlação "escreve assim = é legítimo" intacta.

### Etapa 4 — Descobrir que os canais não conversam

Testamos o sistema treinado em e-mail aplicando-o a SMS. Desempenho **de moeda
jogada para o alto**. E o contrário também: treinado em SMS, aplicado em
e-mail, falha igual. Mas cada um sozinho, no seu canal, funciona muito bem.

Não é que SMS seja difícil — é que e-mail e SMS são línguas diferentes. SMS tem
53 caracteres de mediana; e-mail tem 750. Não têm vocabulário em comum.

> **Regra 3.** O corpus precisa ser construído **por canal**, com volume próprio
> em cada um, e cada canal reportado separadamente. Vale inclusive para separar
> SMS de WhatsApp: a diferença entre e-mail e SMS está demonstrada, a diferença
> entre SMS e WhatsApp é hipótese em aberto que o corpus permite testar.

### Etapa 5 — Descobrir o que *não* precisa de português

Links maliciosos são analisados à parte. Esse módulo olha a **forma** do
endereço: é um IP em vez de um domínio? o domínio é de registro gratuito? a
marca aparece fora do domínio real (`site.tk/bradesco/login`)?

Forma não depende de idioma. **Esse módulo já funciona em português hoje**, sem
nenhum dado brasileiro (F1 0,977 no benchmark externo OpenML PhishingWebsites).

> **Regra 4.** Nem tudo precisa de dado em PT-BR. O corpus deve concentrar
> esforço no que é específico de idioma — **texto e engenharia social** — e não
> gastar coleta no que já transfere.

### Etapa 6 — Dimensionar o buraco

Montamos o detector completo e testamos em 5 mensagens brasileiras.
**Acertou 2.**

O caso mais grave: um golpe real de SMS em português classificado como
**seguro**. Os módulos de marca e de link acertaram; o módulo de texto — o de
maior peso — puxou para baixo, porque foi treinado 100% em inglês.

A explicabilidade confirmou de forma independente: ao filtrar palavras
funcionais da lista de "termos de risco", **nenhum termo sobrou** em nenhum
caso em português. As razões do modelo eram preposições e artigos.

> **Estatuto deste resultado.** Com n=5, isto é **evidência exploratória** da
> falha de transferência para o contexto brasileiro — não uma medida do tamanho
> da lacuna. A mensuração propriamente dita vem depois, sobre o conjunto de
> teste curado de 300–500 exemplos. A sequência é: 5 casos → evidência
> exploratória → construção do corpus → 300–500 curados → mensuração definitiva.

---

## O que vamos construir, em números

| canal | rótulo | meta |
|---|---|---:|
| E-mail | golpe | 2.000 |
| E-mail | legítimo | 2.000 |
| SMS | golpe | 600 |
| SMS | legítimo | 600 |
| WhatsApp | golpe | 400 |
| WhatsApp | legítimo | 400 |
| **Total** | | **~6.000** |

SMS e WhatsApp são reportados separadamente mesmo somando a meta de mensagem
curta, pela Regra 3. WhatsApp tem meta menor por ser mais difícil de obter e por
exigir consentimento mais forte — conversas de WhatsApp são pessoais, não
correspondência comercial, e o tratamento LGPD é mais restritivo.

Dentro do total, um **conjunto de teste curado de 300–500 exemplos**, revisado
manualmente um a um, que nunca entra em treino. É ele que permite afirmar
qualquer coisa com número.

### De onde vem cada parte

| origem | volume | natureza |
|---|---:|---|
| Curadoria assistida por LLM | 500–800 | escritos e revisados um a um |
| Expansão por template | 3.000–4.000 | combinatória controlada |
| Caixas de spam reais dos autores | 200–1.000 | **dado real brasileiro** |
| E-mail transacional/marketing BR legítimo | 1.000+ | **dado real** — controle de falso positivo |

Dado real vale mais que sintético e não custa nada além do trabalho de
exportar. Dado legítimo brasileiro é tão necessário quanto o golpe: nota fiscal,
boleto real e newsletter de banco usam o mesmo vocabulário de urgência que a
fraude, e sem eles o modelo aprende que "boleto vencendo" é golpe.

> **OpenPhish e URLhaus não compõem este corpus.** Os feeds entregam **URLs, não
> texto de mensagem** — não é possível montar corpus textual a partir deles. Eles
> continuam sendo coletados automaticamente a cada 12h (acumulado atual:
> **16.154** endereços) como insumo do **módulo de URL** e da inteligência de
> ameaças, que é frente separada. Só entrariam no corpus textual se viesse junto
> o conteúdo da campanha, o que os feeds não fornecem.

---

## Como a base será construída de forma assertiva

As quatro regras viram requisitos de engenharia:

**1. Proveniência obrigatória.** Cada exemplo carrega de onde veio, por qual
processo, qual arquétipo representa, se foi revisado por humano e **sob qual
licença pode ser redistribuído**. Para um corpus que será publicado, saber se
cada registro pode ser redistribuído é tão importante quanto saber de onde veio.

**2. Divisão por família de template, não por template nem aleatória.** Se o
mesmo template gerar exemplos no treino e no teste, a métrica infla — é a
armadilha da Etapa 2 em outra roupa. Mas dividir por `template_id` ainda vaza
quando dois templates da mesma família são quase idênticos. A separação é por
`familia_template`.

**3. Teto por célula.** Nenhum arquétipo (PIX, boleto, Serasa…) nem nenhuma
marca pode dominar, pelo mesmo motivo que a Enron não podia.

**4. Nada sintético entra no teste sem revisão humana.** O conjunto de avaliação
é curado; o sintético serve para treino.

**5. Balanceamento e reporte por canal.** Volume próprio para e-mail, SMS e
WhatsApp, com métricas reportadas por canal.

### Estrutura de cada registro

```
id                identificador único
texto             conteúdo da mensagem
canal             email | sms | whatsapp
rotulo            golpe | seguro
origem            curado | template | doacao | traduzido
template_id       nulo quando não veio de template
familia_template  agrupa variantes próximas  ← chave da divisão
arquetipo         pix | boleto | serasa | inss | correios | premio | ...
marca             bradesco | caixa | gov | nubank | ...
anonimizado       bool — passou pelo pipeline LGPD
licenca           condição de redistribuição do registro
revisado          bool
revisor           quem revisou
criado_em         data
hash              SHA-256, para deduplicação
```

---

## Trabalhos relacionados — tabela a preencher

Substitui a alegação de primazia. A pergunta da banca passa a ser "como o seu
difere?", e a resposta é linha a linha.

| trabalho | idioma | país | canal(is) | proveniência por registro | protocolo antileakage | público |
|---|---|---|---|---|---|---|
| SMS Spam Collection (UCI) | EN | — | SMS | não | não | sim |
| *traduções automáticas do UCI* | PT | — | SMS | não | não | sim |
| *corpora de smishing lusófonos não-BR* | PT | a verificar | SMS | a verificar | a verificar | a verificar |
| *coletâneas multilíngues recentes de golpes* | multi | multi | a verificar | a verificar | a verificar | a verificar |
| **PhishGuard BR** | **PT-BR** | **BR** | **e-mail, SMS, WhatsApp** | **sim** | **sim (família de template)** | **sim** |

> Cada linha em itálico exige levantamento na fonte primária antes de entrar na
> monografia. Nenhuma entrada é citada com base em indicação de terceiros.

---

## Validação — por comparação controlada

A validação não é autovalidação, e não exige que o detector já funcione em
português. É um experimento controlado com o instrumento que já está pronto:

| condição | treino | teste |
|---|---|---|
| **A — controle** | 108.951 mensagens, só inglês | conjunto curado PT-BR |
| **B — tratamento** | inglês + corpus PT-BR | mesmo conjunto curado PT-BR |

O **delta entre A e B é o valor da base**, medido. O conjunto de teste é o mesmo
nas duas condições e nunca entra em nenhum dos treinos.

Há ainda uma terceira condição de custo zero que separa duas causas distintas:

| condição | representação | pergunta que responde |
|---|---|---|
| **C** | codificador multilíngue, treino só em inglês | quanto do problema é **idioma**? |

Se C recuperar boa parte da queda, o problema era representação. O que sobrar
depois de C é o que só o **contexto brasileiro** resolve — e essa separação é,
por si só, um resultado publicável.

---

## Estado atual

```
✅ Coleta e parsing de 7 fontes públicas      782.741 mensagens
✅ Limpeza, dedup e correção de viés          108.951 de treino
✅ Protocolo de avaliação e achados           5 relatórios
✅ Detector completo (instrumento)            motor + 3 modelos
👉 ESQUEMA DO CORPUS + PROTOCOLO DE CURADORIA
⬜ Construção da base PT-BR                   0 → ~6.000
⬜ Validação por comparação controlada
⬜ Levantamento de trabalhos relacionados
⬜ Publicação do corpus
```

---

## Consequência para a monografia

O documento atual ainda está centrado no detector. Sete elementos precisam ser
reorganizados:

| elemento | de | para |
|---|---|---|
| Título | Detecção de Phishing e Smishing com IA | Construção e validação de um corpus brasileiro para detecção de phishing e smishing |
| Problemática | golpes crescem e a detecção falha | corpora existentes não representam linguagem, canais e engenharia social do contexto brasileiro |
| Pergunta | LLMs podem aprimorar a detecção? | em que medida um corpus contextualizado em PT-BR melhora a detecção frente ao treino apenas com corpora estrangeiros? |
| Hipótese | IA + PLN melhora a identificação | modelos treinados com corpus PT-BR com controle de proveniência, canal e viés generalizam melhor sobre mensagens brasileiras |
| Objetivo geral | construir um detector | construir, documentar e validar o corpus |
| Objetivos específicos | coletar, treinar, explicar | coletar, curar, deduplicar, balancear, particionar sem vazamento, publicar e validar |
| Detector | o projeto | seção de instrumento experimental |

Isso também resolve um problema da versão anterior: o TG tentava entregar
arquitetura, agente de IA, CNN-BiGRU, XGBoost, XAI, retreinamento e add-on ao
mesmo tempo. O novo recorte tem uma contribuição única e defensável.

---

## Parágrafo de contexto (para colar em outra IA)

> **Projeto PhishGuard BR** — TG de graduação (Fatec Indaiatuba, ADS). **A
> entrega central é a construção de um corpus público para detecção de phishing
> e smishing no contexto brasileiro**, organizado por canal, com proveniência
> rastreável por registro e protocolo de particionamento à prova de vazamento; o
> detector acompanha como instrumento de validação, não como produto principal.
> O trabalho **não reivindica primazia** ("primeiro corpus em português") — o
> diferencial é a combinação de contexto brasileiro, separação por canal,
> proveniência e metodologia documentada, a ser sustentada por tabela
> comparativa de trabalhos relacionados. **Percurso já concluído, que fornece
> tanto a justificativa quanto a metodologia:** coleta de 7 corpora públicos
> totalizando **782.741 mensagens** (Enron, Enron-Spam/AUEB, SpamAssassin, SMS
> Spam Collection/UCI e dois agregados do HuggingFace que reempacotam
> TREC-05/06/07, CEAS-08 e Ling-Spam); parsing MIME e anonimização LGPD;
> deduplicação por texto normalizado que removeu **293.368 cópias (37,5%)**,
> revelando que a dedup por texto exato é insuficiente; análise exploratória que
> expôs viés grave de origem — a base Enron era 66,1% do total com **zero**
> exemplos positivos, e os termos mais preditivos de "legítimo" eram vocabulário
> interno dela (`enron`, `ect`, `houston`, `kaminski`); correção por **teto de
> amostragem por célula origem×rótulo** — e não por origem, já que a majoritária
> era class-pure —, resultando em base de treino de **108.951 mensagens** (64,4%
> legítimo / 35,6% golpe). **Quatro achados viram regras de construção:** (1)
> deduplicação precisa ser normalizada; (2) teto por célula origem×rótulo; (3) a
> transferência entre canais não ocorre — matriz e-mail/SMS com diagonal alta
> (F1 0,972 e 0,955) e fora-da-diagonal em colapso simétrico (0,353 e 0,379) —,
> logo o corpus precisa de volume próprio e reporte separado por canal,
> incluindo SMS e WhatsApp distintos; (4) o módulo de URL, com 26 features
> léxico-estruturais independentes de idioma, **já opera em português sem dado
> brasileiro** (F1 0,977 no benchmark externo OpenML PhishingWebsites), então a
> coleta deve concentrar-se em texto e engenharia social. **Evidência
> exploratória (n=5, não é medida):** o detector completo acertou 2 de 5 casos
> brasileiros, com um smishing real classificado como "seguro"; filtradas
> palavras funcionais, nenhum termo de risco sobrou em português — o
> classificador usa TF-IDF treinado em corpus 100% inglês, travado em idioma por
> construção. **Meta do corpus:** ~6.000 exemplos (2.000 e-mail golpe, 2.000
> e-mail legítimo, 600+600 SMS, 400+400 WhatsApp), com teste curado de 300–500
> revisado manualmente, proveniência por registro (origem, `template_id`,
> `familia_template`, arquétipo, marca, `anonimizado`, `licenca`, revisor) e
> **divisão por família de template**, não aleatória nem por template isolado.
> **Fontes do corpus textual:** curadoria assistida por LLM, expansão
> combinatória por template, doação das caixas de spam dos autores e e-mail
> transacional brasileiro legítimo como controle de falso positivo. Os feeds
> OpenPhish/URLhaus **não** compõem o corpus textual — entregam URLs, não
> mensagens — e seguem como insumo do módulo de URL (coleta automática a cada
> 12h, acumulado em **16.154** endereços). **Validação por comparação
> controlada:** condição A treina só com inglês, condição B com inglês + PT-BR,
> ambas medidas no mesmo conjunto curado; o delta é o valor da base. Uma
> condição C, com codificador multilíngue treinado só em inglês, separa quanto
> do problema é idioma e quanto é contexto brasileiro. **Ambiente:** Python 3.12
> + scikit-learn em Windows, GPU RTX 4050 local, PostgreSQL 16 + Prisma
> previstos para a API.
