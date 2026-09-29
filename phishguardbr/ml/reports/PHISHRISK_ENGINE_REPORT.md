# PhishRisk Engine — validação end-to-end

> Gerado por `src/scoring/demo.py`. Motor em `src/scoring/engine.py`.

## Resultados

| caso | canal | score | classificação | esperado |
|---|---|---:|---|---|
| Golpe PT-BR com marca e link falso (e-mail) | email | 86.8 | golpe | golpe |
| Smishing PT-BR curto (SMS) | sms | 29.8 | seguro | golpe |
| Mensagem legitima com marca e link correto (e-mail) | email | 55.7 | suspeito | seguro |
| E-mail corporativo comum, sem link (e-mail) | email | 65.1 | suspeito | seguro |
| Com cabecalhos de autenticacao falhando + anexo executavel | email | 100.0 | golpe | golpe |

## O que a validação confirma

**A mecânica do motor está correta.** A renormalização de pesos opera como especificado: sem cabeçalhos, o módulo de autenticação sai da média e os outros três passam de 30/25/20% para 40,0/33,3/26,7%; sem links, o módulo de URL também sai e os dois restantes vão a 60,0/40,0%. Um módulo inaplicável nunca é tratado como risco zero. O modificador de anexo é aditivo e elevou o caso 5 ao teto de 100.

**Os módulos estruturais funcionam em português.** No caso 2, um smishing em PT-BR, o módulo de marca atribuiu 90 (cita «caixa», nenhum link aponta para caixa.gov.br) e o de URL identificou o encurtador. Esses módulos não dependem de modelo de idioma.

## O que a validação revela — o módulo NLP não opera em português

É o achado central desta bateria, e ele é negativo:

| caso | NLP diz | realidade | erro |
|---|---:|---|---|
| 2 — smishing PT-BR | 10% de golpe | é golpe | **falso negativo** |
| 3 — fatura legítima | 86% de golpe | é legítima | falso positivo |
| 4 — e-mail corporativo | 89% de golpe | é legítimo | falso positivo |

O caso 2 é o mais grave: um golpe real classificado como **seguro** pelo score final, porque o módulo NLP — o de maior peso — votou contra os módulos que acertaram.

A explicabilidade confirma o diagnóstico de forma independente. Ao filtrar palavras funcionais da lista de termos decisivos, **nenhum termo sobrou** em nenhum dos casos em português: as razões que o modelo tinha para suas predições eram preposições e artigos. O classificador foi treinado em corpus 100% em inglês (ver `EDA_REPORT.md`, seção 6) e, diante de texto em português, opera fora de distribuição — produz número, não decisão.

**Consequência.** A arquitetura do PhishRisk Engine está validada e os módulos estruturais são utilizáveis, mas o produto não é operável em português enquanto o módulo NLP não for treinado em corpus PT-BR. Isso não é limitação de implementação: é a lacuna de dados que este trabalho se propõe a preencher, aqui medida de ponta a ponta no produto final.

## Limitações registradas

- **Ambiguidade de marca curta.** No caso 4, «Oi pessoal» aciona a marca de telecomunicações «oi». A correspondência por fronteira de palavra já elimina o casamento dentro de outras palavras (antes, «foi» acionava «oi»), mas não resolve homonímia real. Exige desambiguação por contexto.
- **Limiares não calibrados.** Os cortes de 40 e 70 vêm de §6.7 e ainda não foram ajustados sobre conjunto de validação PT-BR.
- **Módulo de autenticação sem validação empírica.** A lógica está implementada, mas o corpus não preservou cabeçalhos SPF/DKIM/DMARC, então ela só foi exercitada com entrada sintética.

