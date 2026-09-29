"""Anonimização auditável — LGPD, aplicada antes de qualquer artefato derivado.

Princípio: o dataset processado registra **quais categorias** de dado pessoal
foram encontradas e mascaradas, e **nunca** o valor original. Saber que um
registro continha um CPF é informação de auditoria; saber qual CPF era, não.

Ordem de aplicação importa. Padrões numéricos se sobrepõem — um CPF sem
pontuação são 11 dígitos, e um telefone com DDD também. As categorias mais
específicas são aplicadas primeiro, e cada marcador já substituído deixa de ser
candidato para as seguintes.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MARCADOR = {
    "email": "<EMAIL>",
    "cartao": "<CARTAO>",
    "cnpj": "<CNPJ>",
    "cpf": "<CPF>",
    "telefone": "<TEL>",
    "cep": "<CEP>",
    "nome_destinatario": "<NOME>",
    "url_param": "<PARAM>",
}

# Ordem deliberada: mais específico primeiro. Cartão (16 dígitos) antes de CNPJ
# (14), que vem antes de CPF (11), que vem antes de telefone (10-11) — senão o
# padrão mais curto consome parte do mais longo.
PADROES: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("cartao", re.compile(r"\b\d{4}[ .-]?\d{4}[ .-]?\d{4}[ .-]?\d{4}\b")),
    ("cnpj", re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")),
    ("cpf", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-?\d{2}\b|\b\d{11}\b")),
    ("telefone", re.compile(
        r"(?:\+55\s?)?(?:\(\d{2}\)|\b\d{2})[\s.-]?9?\d{4}[\s.-]?\d{4}\b")),
    ("cep", re.compile(r"\b\d{5}-\d{3}\b")),
]

# Chaves de query que costumam carregar identificador do destinatário.
PARAMS_SENSIVEIS = {
    "email", "e-mail", "mail", "user", "usuario", "id", "uid", "cpf", "doc",
    "token", "t", "key", "hash", "ref", "rcpt", "recipient", "subscriber",
    "sid", "session", "auth", "code", "codigo", "cliente", "customer",
}

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")


@dataclass
class ResultadoAnonimizacao:
    texto: str
    categorias: set[str] = field(default_factory=set)
    ocorrencias: dict[str, int] = field(default_factory=dict)

    def resumo(self) -> str:
        """Categorias encontradas, em ordem estável. Nunca os valores."""
        return ",".join(sorted(self.categorias))


def _mascarar_url(url: str, res: ResultadoAnonimizacao) -> str:
    """Preserva esquema, host e caminho; mascara valores de query sensíveis.

    A estrutura da URL é sinal de risco (módulo de URL, §6.3) e precisa
    sobreviver. O valor do parâmetro é que identifica o destinatário.
    """
    try:
        partes = urlsplit(url)
    except ValueError:
        return url
    if not partes.query:
        return url

    pares = parse_qsl(partes.query, keep_blank_values=True)
    if not pares:
        return url

    novo, mudou = [], False
    for chave, valor in pares:
        sensivel = chave.lower() in PARAMS_SENSIVEIS or len(valor) >= 20
        if sensivel and valor:
            novo.append((chave, MARCADOR["url_param"]))
            mudou = True
        else:
            novo.append((chave, valor))

    if not mudou:
        return url
    res.categorias.add("url_param")
    res.ocorrencias["url_param"] = res.ocorrencias.get("url_param", 0) + 1
    return urlunsplit(
        (partes.scheme, partes.netloc, partes.path,
         urlencode(novo, safe="<>"), partes.fragment)
    )


def anonimizar(texto: str, termos_diretos: list[str] | None = None) -> ResultadoAnonimizacao:
    """Mascara dado pessoal e devolve o texto junto com as categorias afetadas.

    `termos_diretos` são strings conhecidas do cabeçalho — nome e endereço do
    destinatário — que aparecem personalizadas no corpo ("Olá João Silva").
    Não há como detectá-las por padrão genérico, mas sabemos quais são.
    """
    res = ResultadoAnonimizacao(texto=texto or "")
    if not res.texto:
        return res

    # 1. URLs primeiro: o mascaramento genérico destruiria a estrutura antes de
    #    conseguirmos distinguir chave de valor.
    res.texto = URL_RE.sub(lambda m: _mascarar_url(m.group(0), res), res.texto)

    # 2. Termos conhecidos do cabeçalho, categorizados pelo que de fato são.
    #    Um endereço vindo do `To` continua sendo um e-mail: registrá-lo como
    #    "nome" esconderia do auditor que havia endereço no corpo.
    for termo in termos_diretos or []:
        termo = (termo or "").strip()
        if len(termo) < 3:
            continue
        categoria = "email" if "@" in termo else "nome_destinatario"
        padrao = re.compile(re.escape(termo), re.IGNORECASE)
        texto_novo, n = padrao.subn(MARCADOR[categoria], res.texto)
        if n:
            res.texto = texto_novo
            res.categorias.add(categoria)
            res.ocorrencias[categoria] = res.ocorrencias.get(categoria, 0) + n

    # 3. Padrões genéricos, do mais específico ao mais amplo.
    for nome, padrao in PADROES:
        texto_novo, n = padrao.subn(MARCADOR[nome], res.texto)
        if n:
            res.texto = texto_novo
            res.categorias.add(nome)
            res.ocorrencias[nome] = res.ocorrencias.get(nome, 0) + n

    return res
