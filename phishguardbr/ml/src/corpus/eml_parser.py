"""Parser de `.eml` → registro de estágio para curadoria.

Transforma uma mensagem real bruta em um registro anonimizado, rastreável e
pronto para revisão humana. **Não classifica nada**: `rotulo`, `arquetipo`,
`marca`, `revisado` e `particao` não são decididos aqui — só um humano decide,
e o parser existe para preparar o material dessa decisão.

Escopo — onde este pipeline se encaixa
--------------------------------------
Esta esteira alimenta **uma das fontes** do corpus PT-BR. Não é a origem de todo
o dado do projeto:

    corpus estrangeiro (108.951, congelado)  -> condicoes A e C, e tambem B e D
    corpus PT-BR .................. .eml reais  <- ESTE PIPELINE
                                    SMS/WhatsApp reais
                                    templates e sinteticos
                                    legitimos brasileiros
    Gold Test PT-BR ............... real, curado, nunca em treino

Os corpora estrangeiros já passaram por coleta, parsing, deduplicação e
balanceamento próprios (`src/parsing/`, `src/features/build_dataset.py`) e
**não** são reprocessados aqui. Ver `docs/PROTOCOLO_EXPERIMENTAL.md`.

Por que o parser não produz um `Registro` do schema
---------------------------------------------------
O schema (`CORPUS_SCHEMA.md` v1) está congelado com `extra="forbid"` e exige
campos que só a curadoria determina. O parser produz um **registro de estágio**,
que carrega os metadados de proveniência do parsing e as lacunas explícitas.
Ele vira `Registro` quando o humano preenche o que falta — e só então passa pelo
validador.

Privacidade
-----------
- O `.eml` bruto **nunca é modificado** e nunca sai de `raw_private/`.
- Cabeçalho sensível não é copiado: `Received`, `Message-ID`, `Return-Path`,
  `DKIM-Signature`, `To`, `Cc` e afins ficam de fora. Do remetente guarda-se
  apenas o **hash do domínio**, que serve para agrupar campanha sem identificar
  ninguém.
- A rastreabilidade até o arquivo bruto é feita por `origem_ref` — o SHA-256 do
  arquivo —, nunca pelo caminho. O mapa `origem_ref → nome do arquivo` fica em
  `raw_private/mapa_origem.csv`, que não é versionado.

Uso (a partir de ml/):
    python -m src.corpus.eml_parser
    python -m src.corpus.eml_parser --fonte coleta_propria
"""
import argparse
import csv
import hashlib
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from email import message_from_bytes, policy
from email.utils import parseaddr
from pathlib import Path

from bs4 import BeautifulSoup

from src.corpus.anonimizacao import anonimizar
from src.corpus.schema import calcular_hash

ML_DIR = Path(__file__).resolve().parents[2]
PTBR = ML_DIR / "data" / "ptbr"
EML_DIR = PTBR / "raw_private" / "eml"
PRIVADO = PTBR / "processed_private"
MAPA_ORIGEM = PTBR / "raw_private" / "mapa_origem.csv"
FILA = PRIVADO / "fila_curadoria.csv"

# Campos que o parser deliberadamente NÃO preenche: dependem de julgamento.
PENDENTES_CURADORIA = [
    "rotulo", "arquetipo", "marca", "base_juridica",
    "redistribuivel", "proveniencia_verificada", "particao", "revisor",
]

TIPOS_ANEXO_IGNORADOS = {"application", "image", "audio", "video"}


@dataclass
class RegistroEstagio:
    """Ainda não é um `Registro`: faltam os campos de curadoria."""

    # determinados pelo parser
    id: str
    texto: str
    assunto: str
    canal: str = "email"
    natureza: str = "real"
    fonte_aquisicao: str = "doacao"
    metodo_geracao: str = "nenhum"
    transformacao: str = "normalizado"   # anonimização é transformação
    anonimizado: bool = True
    uso_pesquisa: bool = True
    criado_em: str = field(default_factory=lambda: date.today().isoformat())
    hash: str = ""

    # proveniência do parsing (não fazem parte do schema congelado)
    origem_ref: str = ""                 # sha256 do .eml bruto
    remetente_dominio_hash: str = ""
    data_mensagem: str = ""
    tipo_corpo: str = ""                 # plain | html | plain+html
    n_anexos: int = 0
    n_caracteres: int = 0
    categorias_anonimizadas: str = ""
    parse_erro: str = ""

    # lacunas explícitas — preenchidas na curadoria
    rotulo: str = ""
    arquetipo: str = ""
    marca: str = ""
    base_juridica: str = ""
    redistribuivel: str = ""             # vazio = indeciso; humano resolve
    proveniencia_verificada: str = ""
    particao: str = ""
    revisor: str = ""
    revisado: bool = False

    def pendencias(self) -> list[str]:
        return [c for c in PENDENTES_CURADORIA if not getattr(self, c)]


def _hash_dominio(endereco: str) -> str:
    _, addr = parseaddr(endereco or "")
    dominio = addr.split("@")[-1].lower() if "@" in addr else ""
    return hashlib.sha256(dominio.encode()).hexdigest()[:16] if dominio else ""


def _html_para_texto(html: str) -> str:
    sopa = BeautifulSoup(html or "", "html.parser")
    for tag in sopa(["script", "style", "head"]):
        tag.decompose()
    return sopa.get_text(separator=" ", strip=True)


def _extrair_corpo(msg) -> tuple[str, str, int]:
    """Devolve (texto, tipo_corpo, n_anexos).

    Prefere `text/plain`. HTML só é convertido quando não há alternativa em
    texto. Anexo nunca entra no corpo — só é contado.
    """
    partes_plain, partes_html, anexos = [], [], 0

    for parte in msg.walk():
        if parte.is_multipart():
            continue

        disp = (parte.get_content_disposition() or "").lower()
        tipo = parte.get_content_maintype()
        if disp == "attachment" or tipo in TIPOS_ANEXO_IGNORADOS:
            anexos += 1
            continue

        try:
            conteudo = parte.get_content()
        except Exception:
            try:
                conteudo = (parte.get_payload(decode=True) or b"").decode(
                    parte.get_content_charset() or "utf-8", errors="replace")
            except Exception:
                continue
        if not isinstance(conteudo, str):
            continue

        sub = (parte.get_content_subtype() or "").lower()
        if sub == "plain":
            partes_plain.append(conteudo)
        elif sub == "html":
            partes_html.append(conteudo)

    if partes_plain and partes_html:
        tipo_corpo = "plain+html"
    elif partes_plain:
        tipo_corpo = "plain"
    elif partes_html:
        tipo_corpo = "html"
    else:
        tipo_corpo = "vazio"

    texto = "\n".join(partes_plain).strip()
    if not texto and partes_html:
        texto = _html_para_texto("\n".join(partes_html))

    return texto.strip(), tipo_corpo, anexos


def parse_eml(caminho: Path, fonte_aquisicao: str = "doacao") -> RegistroEstagio:
    """Lê um `.eml` sem modificá-lo e devolve o registro de estágio."""
    bruto = caminho.read_bytes()
    origem_ref = hashlib.sha256(bruto).hexdigest()

    erro = ""
    try:
        msg = message_from_bytes(bruto, policy=policy.default)
    except Exception as e:
        # Mensagem malformada não pode derrubar o lote inteiro.
        return RegistroEstagio(
            id=f"eml_{origem_ref[:16]}", texto="", assunto="",
            fonte_aquisicao=fonte_aquisicao, origem_ref=origem_ref,
            parse_erro=f"{type(e).__name__}: {e}", tipo_corpo="erro",
            hash=calcular_hash(""),
        )

    try:
        assunto_bruto = str(msg.get("Subject") or "")
    except Exception:
        assunto_bruto, erro = "", "subject ilegivel"

    try:
        texto_bruto, tipo_corpo, n_anexos = _extrair_corpo(msg)
    except Exception as e:
        texto_bruto, tipo_corpo, n_anexos = "", "erro", 0
        erro = f"{type(e).__name__}: {e}"

    # Nome e endereço do destinatário costumam aparecer personalizados no corpo.
    # São conhecidos pelo cabeçalho, então podem ser mascarados diretamente —
    # e os cabeçalhos em si NÃO são copiados para o registro.
    termos = []
    for campo in ("To", "Cc", "Delivered-To", "X-Original-To"):
        nome, addr = parseaddr(str(msg.get(campo) or ""))
        termos.extend([t for t in (nome, addr) if t])

    an_texto = anonimizar(texto_bruto, termos_diretos=termos)
    an_assunto = anonimizar(assunto_bruto, termos_diretos=termos)
    categorias = sorted(an_texto.categorias | an_assunto.categorias)

    return RegistroEstagio(
        id=f"eml_{origem_ref[:16]}",          # estável: deriva do conteúdo
        texto=an_texto.texto,
        assunto=an_assunto.texto,
        fonte_aquisicao=fonte_aquisicao,
        hash=calcular_hash(an_texto.texto),   # mesma normalização do schema
        origem_ref=origem_ref,
        remetente_dominio_hash=_hash_dominio(str(msg.get("From") or "")),
        data_mensagem=str(msg.get("Date") or "")[:40],
        tipo_corpo=tipo_corpo,
        n_anexos=n_anexos,
        n_caracteres=len(an_texto.texto),
        categorias_anonimizadas=",".join(categorias),
        parse_erro=erro,
    )


def processar_lote(
    origem: Path = EML_DIR,
    fonte_aquisicao: str = "doacao",
    mapa: Path | None = None,
) -> list[RegistroEstagio]:
    """`mapa` acompanha a origem por padrão: processar uma pasta de teste não
    pode escrever no mapa de produção."""
    if not origem.exists():
        return []
    if mapa is None:
        # Dentro de raw_private -> mapa de producao. Fora (pasta de teste,
        # diretorio temporario) -> mapa local, para nao contaminar a producao.
        try:
            origem.resolve().relative_to(MAPA_ORIGEM.parent.resolve())
            mapa = MAPA_ORIGEM
        except ValueError:
            mapa = origem / "mapa_origem.csv"

    registros, vistos = [], set()
    for caminho in sorted(origem.glob("*.eml")):
        r = parse_eml(caminho, fonte_aquisicao)
        # Dedup por hash do texto anonimizado, coerente com a Regra 1.
        if r.hash in vistos and r.texto:
            continue
        vistos.add(r.hash)
        registros.append(r)
        _registrar_origem(r.origem_ref, caminho.name, mapa)
    return registros


def _registrar_origem(origem_ref: str, nome_arquivo: str, mapa: Path) -> None:
    """Mapa privado origem_ref → arquivo. Fica em raw_private, não versionado."""
    mapa.parent.mkdir(parents=True, exist_ok=True)
    existentes = set()
    if mapa.exists():
        with open(mapa, encoding="utf-8", newline="") as f:
            existentes = {linha["origem_ref"] for linha in csv.DictReader(f)}
    if origem_ref in existentes:
        return
    novo = not mapa.exists()
    with open(mapa, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["origem_ref", "arquivo", "registrado_em"])
        if novo:
            w.writeheader()
        w.writerow({"origem_ref": origem_ref, "arquivo": nome_arquivo,
                    "registrado_em": date.today().isoformat()})


def gravar_fila(registros: list[RegistroEstagio], destino: Path = FILA) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    linhas = []
    for r in registros:
        d = asdict(r)
        d["pendencias"] = ",".join(r.pendencias())
        linhas.append(d)
    if not linhas:
        return
    with open(destino, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)


def main() -> int:
    p = argparse.ArgumentParser(description="Converte .eml em fila de curadoria.")
    p.add_argument("--origem", type=Path, default=EML_DIR)
    p.add_argument("--fonte", default="doacao",
                   choices=["doacao", "corpus_publico", "coleta_propria"])
    a = p.parse_args()

    if not a.origem.exists():
        print(f"ERRO: pasta nao encontrada: {a.origem}", file=sys.stderr)
        return 2

    registros = processar_lote(a.origem, a.fonte)
    if not registros:
        print(f"nenhum .eml em {a.origem}")
        return 0

    gravar_fila(registros)

    com_erro = [r for r in registros if r.parse_erro]
    categorias: dict[str, int] = {}
    for r in registros:
        for c in filter(None, r.categorias_anonimizadas.split(",")):
            categorias[c] = categorias.get(c, 0) + 1

    print(f"processados: {len(registros)} | com erro de parsing: {len(com_erro)}")
    print(f"tipos de corpo: "
          f"{ {t: sum(1 for r in registros if r.tipo_corpo == t) for t in {r.tipo_corpo for r in registros} } }")
    print(f"anexos ignorados: {sum(r.n_anexos for r in registros)}")
    print(f"categorias anonimizadas: {categorias or 'nenhuma'}")
    print(f"\nfila de curadoria: {FILA}")
    print(f"mapa de origem (privado): {MAPA_ORIGEM}")
    print(f"\npendente de revisao humana em cada registro: "
          f"{', '.join(PENDENTES_CURADORIA)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
