"""Demonstração end-to-end do PhishRisk Engine sobre casos que exercitam cada módulo.

Serve de verificação manual e de material para a defesa: mostra o score, a
classificação, os pesos efetivos após renormalização e a explicação em
linguagem natural.

Uso (a partir de ml/):
    python -m src.scoring.demo
"""
from pathlib import Path

from src.scoring.engine import PhishRiskEngine

REPORT = Path(__file__).resolve().parents[2] / "reports" / "PHISHRISK_ENGINE_REPORT.md"

CASOS = [
    {
        "titulo": "Golpe PT-BR com marca e link falso (e-mail)",
        "esperado": "golpe",
        "canal": "email",
        "texto": (
            "Prezado cliente Bradesco, detectamos uma movimentacao suspeita na sua "
            "conta. Por seguranca, seu acesso foi bloqueado. Para desbloquear, "
            "confirme seus dados em http://bradesc0-seguranca.tk/login/atualizar.php "
            "ate hoje as 18h, sob pena de encerramento da conta."
        ),
    },
    {
        "titulo": "Smishing PT-BR curto (SMS)",
        "esperado": "golpe",
        "canal": "sms",
        "texto": (
            "CAIXA: seu CPF foi bloqueado no programa. Regularize agora em "
            "http://bit.ly/3xK9aB ou perca o beneficio."
        ),
    },
    {
        "titulo": "Mensagem legitima com marca e link correto (e-mail)",
        "esperado": "seguro",
        "canal": "email",
        "texto": (
            "Ola, sua fatura do Nubank ja esta disponivel. Voce pode consultar o "
            "valor e a data de vencimento no aplicativo ou em "
            "https://nubank.com.br/minhas-faturas . Qualquer duvida, estamos a "
            "disposicao."
        ),
    },
    {
        "titulo": "E-mail corporativo comum, sem link (e-mail)",
        "esperado": "seguro",
        "canal": "email",
        "texto": (
            "Oi pessoal, segue o resumo da reuniao de ontem. Ficou definido que o "
            "relatorio trimestral sera entregue na sexta e que o Joao fica "
            "responsavel pela revisao dos numeros. Abracos."
        ),
    },
    {
        "titulo": "Com cabecalhos de autenticacao falhando + anexo executavel",
        "esperado": "golpe",
        "canal": "email",
        "texto": (
            "Segue em anexo a segunda via do seu boleto em aberto. "
            "Regularize para evitar a negativacao do seu CPF no Serasa."
        ),
        "cabecalhos": {"spf": "fail", "dkim": "none", "dmarc": "fail"},
        "anexos": ["boleto_2via.pdf.exe"],
    },
]


def escrever_relatorio(resultados: list) -> None:
    linhas = [
        "# PhishRisk Engine — validação end-to-end",
        "",
        "> Gerado por `src/scoring/demo.py`. Motor em `src/scoring/engine.py`.",
        "",
        "## Resultados",
        "",
        "| caso | canal | score | classificação | esperado |",
        "|---|---|---:|---|---|",
    ]
    for caso, r in resultados:
        linhas.append(
            f"| {caso['titulo']} | {r.canal} | {r.score:.1f} | "
            f"{r.classificacao} | {caso['esperado']} |"
        )

    linhas += [
        "",
        "## O que a validação confirma",
        "",
        "**A mecânica do motor está correta.** A renormalização de pesos opera como "
        "especificado: sem cabeçalhos, o módulo de autenticação sai da média e os "
        "outros três passam de 30/25/20% para 40,0/33,3/26,7%; sem links, o módulo "
        "de URL também sai e os dois restantes vão a 60,0/40,0%. Um módulo "
        "inaplicável nunca é tratado como risco zero. O modificador de anexo é "
        "aditivo e elevou o caso 5 ao teto de 100.",
        "",
        "**Os módulos estruturais funcionam em português.** No caso 2, um smishing "
        "em PT-BR, o módulo de marca atribuiu 90 (cita «caixa», nenhum link aponta "
        "para caixa.gov.br) e o de URL identificou o encurtador. Esses módulos não "
        "dependem de modelo de idioma.",
        "",
        "## O que a validação revela — o módulo NLP não opera em português",
        "",
        "É o achado central desta bateria, e ele é negativo:",
        "",
        "| caso | NLP diz | realidade | erro |",
        "|---|---:|---|---|",
        "| 2 — smishing PT-BR | 10% de golpe | é golpe | **falso negativo** |",
        "| 3 — fatura legítima | 86% de golpe | é legítima | falso positivo |",
        "| 4 — e-mail corporativo | 89% de golpe | é legítimo | falso positivo |",
        "",
        "O caso 2 é o mais grave: um golpe real classificado como **seguro** pelo "
        "score final, porque o módulo NLP — o de maior peso — votou contra os "
        "módulos que acertaram.",
        "",
        "A explicabilidade confirma o diagnóstico de forma independente. Ao filtrar "
        "palavras funcionais da lista de termos decisivos, **nenhum termo sobrou** "
        "em nenhum dos casos em português: as razões que o modelo tinha para suas "
        "predições eram preposições e artigos. O classificador foi treinado em "
        "corpus 100% em inglês (ver `EDA_REPORT.md`, seção 6) e, diante de texto "
        "em português, opera fora de distribuição — produz número, não decisão.",
        "",
        "**Consequência.** A arquitetura do PhishRisk Engine está validada e os "
        "módulos estruturais são utilizáveis, mas o produto não é operável em "
        "português enquanto o módulo NLP não for treinado em corpus PT-BR. Isso "
        "não é limitação de implementação: é a lacuna de dados que este trabalho "
        "se propõe a preencher, aqui medida de ponta a ponta no produto final.",
        "",
        "## Limitações registradas",
        "",
        "- **Ambiguidade de marca curta.** No caso 4, «Oi pessoal» aciona a marca "
        "de telecomunicações «oi». A correspondência por fronteira de palavra já "
        "elimina o casamento dentro de outras palavras (antes, «foi» acionava "
        "«oi»), mas não resolve homonímia real. Exige desambiguação por contexto.",
        "- **Limiares não calibrados.** Os cortes de 40 e 70 vêm de §6.7 e ainda "
        "não foram ajustados sobre conjunto de validação PT-BR.",
        "- **Módulo de autenticação sem validação empírica.** A lógica está "
        "implementada, mas o corpus não preservou cabeçalhos SPF/DKIM/DMARC, "
        "então ela só foi exercitada com entrada sintética.",
        "",
    ]
    REPORT.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"Relatorio: {REPORT}")


def main() -> None:
    engine = PhishRiskEngine()
    resultados = []

    for caso in CASOS:
        r = engine.analisar(
            caso["texto"],
            canal=caso["canal"],
            cabecalhos=caso.get("cabecalhos"),
            anexos=caso.get("anexos"),
        )
        print("=" * 78)
        print(f"{caso['titulo']}  [canal: {r.canal}]")
        print("-" * 78)
        print(f"SCORE: {r.score:5.1f}/100   ->   {r.classificacao.upper()}")
        if r.modificador_anexo:
            print(f"  (inclui +{r.modificador_anexo:.0f} do modificador de anexo)")
        print()
        print("  modulo   aplicavel  score  peso efetivo")
        for m in r.modulos:
            if m.nome == "anexo":
                continue
            if m.aplicavel:
                print(f"  {m.nome:8s} {'sim':9s}  {m.score:5.1f}  "
                      f"{m.peso_efetivo * 100:5.1f}%")
            else:
                print(f"  {m.nome:8s} {'nao':9s}      -      -   ({m.motivo})")
        print()
        print("  Explicacao ao usuario:")
        for s in r.explicacao():
            print(f"    - {s}")
        print()
        resultados.append((caso, r))

    escrever_relatorio(resultados)


if __name__ == "__main__":
    main()
