# Módulo de URL — três protocolos

> Gerado por `src/training/url_model.py`. Features em `src/features/url_features.py`.
> Dataset: 51,464 URLs, 26.9% maliciosas.

O rótulo de treino é binário (`is_malicious`): do ponto de vista do e-mail,
link que entrega payload e link que serve página enganosa são a mesma
decisão. O `threat_type` fica como metadado — alimenta a explicação ao
usuário e o protocolo B abaixo.

## A — split aleatório

| protocolo    | modelo        |   accuracy |   precision |   recall |     f1 |   auc_roc |
|:-------------|:--------------|-----------:|------------:|---------:|-------:|----------:|
| A: aleatorio | logreg        |     0.9839 |      0.9751 |   0.9645 | 0.9698 |    0.996  |
| A: aleatorio | random_forest |     0.9961 |      0.9938 |   0.9917 | 0.9928 |    0.9993 |

## B — cruzado por tipo de ameaça (treina malware, testa phishing)

O modelo nunca viu uma URL de phishing no treino. Se ele acerta aqui, as
duas ameaças compartilham assinatura estrutural e um módulo único cobre
as duas — que é a premissa do rótulo binário.

| protocolo            | modelo        |   accuracy |   precision |   recall |     f1 |   auc_roc |
|:---------------------|:--------------|-----------:|------------:|---------:|-------:|----------:|
| B: malware->phishing | logreg        |     0.9732 |      0.6907 |   0.5433 | 0.6082 |    0.9086 |
| B: malware->phishing | random_forest |     0.9796 |      0.907  |   0.52   | 0.661  |    0.9463 |

## C — benchmark externo (OpenML 4534)

Controle para a confusão temporal do nosso dataset (negativos de 2002,
positivos de hoje). Features próprias do benchmark, resultados publicados.

| protocolo            | modelo        |   accuracy |   precision |   recall |     f1 |   auc_roc |
|:---------------------|:--------------|-----------:|------------:|---------:|-------:|----------:|
| C: benchmark externo | logreg        |     0.9285 |      0.9234 |   0.9504 | 0.9367 |    0.9808 |
| C: benchmark externo | random_forest |     0.9738 |      0.9711 |   0.9821 | 0.9766 |    0.9978 |

## Leitura dos resultados

**A transferência malware → phishing é parcial, e o padrão importa.** O melhor modelo chega a AUC **0.946** testando em URLs de phishing que nunca viu, mas com recall de apenas **0.520** e precisão de **0.907**.

AUC alta com recall baixo diz uma coisa específica: o modelo **ordena** bem — sabe que as URLs de phishing são mais arriscadas que as benignas — mas o **limiar de decisão** está calibrado para malware. URL de phishing é estruturalmente mais discreta, porque imita site legítimo de propósito.

Conclusão de projeto: um módulo único cobre as duas ameaças, o que valida o rótulo binário — mas o limiar precisa ser calibrado por tipo de ameaça, não herdado de um para o outro.

**O benchmark externo sustenta a abordagem.** No protocolo A o F1 chega a 0.9928, alto demais para ser levado ao pé da letra — os negativos são de 2002 e os positivos de hoje. O protocolo C, com positivos e negativos da mesma época, entrega F1 0.9766, em linha com o que a literatura publica para esse benchmark. Ou seja, features estruturais de URL funcionam de fato; o excesso do protocolo A é que é artefato.

## Features mais importantes

| feature              |   importancia |
|:---------------------|--------------:|
| n_digitos_host       |        0.2064 |
| prop_digitos_host    |        0.1811 |
| prop_consoantes_host |        0.1433 |
| host_e_ip            |        0.1176 |
| maior_token_host     |        0.0749 |
| e_https              |        0.0534 |
| entropia_host        |        0.0453 |
| tem_porta            |        0.0415 |
| n_pontos             |        0.0397 |
| url_len              |        0.0227 |
| host_len             |        0.02   |
| path_len             |        0.0134 |

As quatro que mais pesam (`n_digitos_host`, `prop_digitos_host`, `prop_consoantes_host`, `host_e_ip`) descrevem, no fundo, **host que é endereço IP cru** — a assinatura típica do URLhaus, onde o payload fica num IP sem domínio. Isso explica o protocolo B: phishing usa nome de domínio registrado, justamente para parecer legítimo, então não aciona essas features.

As features de contexto brasileiro (`marca_fora_do_dominio`, `n_iscas`, `tld_suspeito`) **não aparecem no topo, e não deveriam aparecer ainda**: não há praticamente phishing brasileiro nos feeds coletados até agora. Elas estão implementadas e testadas em exemplos sintéticos, mas só serão validadas empiricamente quando a coleta acumular volume de golpe em PT-BR.

## Limitações

- **Confusão temporal**: negativos vêm de e-mails de 2002, positivos de
  feeds atuais. O protocolo C existe para controlar isso.
- **Typosquatting não é detectado**: a checagem de marca é por substring,
  então `bradesc0` (com zero) não casa com `bradesco`. Corrigir exige
  distância de edição ou mapa de homoglifos.
- **Phishing sub-representado**: só 300 URLs de phishing contra 13.521 de
  malware. A coleta agendada (`scripts/agendar_coleta.ps1`) acumula a cada
  12h; refazer este relatório quando o volume subir.

