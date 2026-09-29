"""Features léxicas/estruturais de URL — módulo de URL (planejamento_tg.md §6.3).

Princípio: extrair **forma**, nunca **identidade**. O modelo não deve aprender
que `iiq.us` é ruim e `cnet.com` é bom — para isso bastaria consultar o feed, e
a resposta envelhece em dias. Ele deve aprender que host-que-é-IP, punycode,
marca no caminho em vez do domínio e hostname de alta entropia são sinais de
ataque, porque isso vale para uma URL que ninguém nunca viu.

Consequência que interessa ao TG: essas características são **independentes de
idioma**. `bradesc0-seguranca.tk/login` tem os mesmos sinais estruturais de um
equivalente em inglês. É plausível que o módulo de URL transfira para PT-BR sem
precisar de corpus em português — diferente dos módulos de texto/NLP. As listas
de marca e de termo-isca incluem o vocabulário brasileiro justamente para isso.

Uso:
    from src.features.url_features import extrair_features, FEATURE_NAMES
    features = extrair_features("http://bradesc0-seguranca.tk/login")
"""
import math
import re
from collections import Counter
from urllib.parse import urlparse

# Marcas visadas por golpe no Brasil. Entram como feature de POSIÇÃO: marca no
# caminho/subdomínio com domínio registrável diferente é o padrão clássico de
# imitação (`santander.golpe.tk` ou `site.tk/itau/login`).
MARCAS = {
    # bancos e financeiro
    "bradesco", "itau", "santander", "caixa", "nubank", "inter", "bancodobrasil",
    "banrisul", "sicredi", "sicoob", "safra", "original", "c6bank", "picpay",
    "mercadopago", "pagseguro", "stone", "pix",
    # governo e serviços
    "gov", "receita", "serasa", "spc", "detran", "inss", "correios", "enel",
    "cpfl", "sabesp", "vivo", "claro", "tim", "oi",
    # varejo e plataformas
    "mercadolivre", "magazineluiza", "americanas", "casasbahia", "shopee",
    "netflix", "spotify", "whatsapp", "instagram", "facebook", "google",
    "microsoft", "apple", "amazon", "paypal", "steam",
}

# Termos-isca, PT-BR e EN. Aparecem no caminho/query de páginas de captura.
ISCAS = {
    # português
    "login", "entrar", "acesso", "senha", "conta", "cadastro", "atualizar",
    "atualizacao", "verificar", "verificacao", "confirmar", "confirmacao",
    "seguranca", "recadastramento", "desbloqueio", "bloqueado", "premio",
    "sorteio", "fatura", "boleto", "segundavia", "nota", "restituicao",
    # inglês
    "signin", "logon", "account", "verify", "update", "secure", "security",
    "confirm", "password", "banking", "webscr", "recover", "unlock", "billing",
    "invoice", "suspended", "limited",
}

# TLDs com registro gratuito ou barato e histórico de abuso.
TLDS_SUSPEITOS = {
    "tk", "ml", "ga", "cf", "gq", "top", "xyz", "club", "online", "site",
    "website", "space", "icu", "live", "cyou", "rest", "fit", "sbs", "cfd",
}

ENCURTADORES = {
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd", "buff.ly",
    "cutt.ly", "rebrand.ly", "shorturl.at", "encurtador.com.br", "bit.do",
    "rb.gy", "tiny.cc", "shorte.st", "t.ly",
}

IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
HEX_RE = re.compile(r"%[0-9a-fA-F]{2}")
TOKEN_RE = re.compile(r"[a-z0-9]+")

FEATURE_NAMES = [
    "url_len", "host_len", "path_len", "query_len",
    "n_pontos", "n_hifens", "n_subdominios", "n_segmentos_path", "n_params",
    "host_e_ip", "tem_porta", "tem_arroba", "e_https", "tem_punycode",
    "tem_hex_encoding", "tem_barra_dupla_path",
    "n_digitos_host", "prop_digitos_host", "entropia_host",
    "maior_token_host", "prop_consoantes_host",
    "tld_suspeito", "e_encurtador",
    "marca_no_host", "marca_fora_do_dominio", "n_iscas",
]


def _entropia(texto: str) -> float:
    """Entropia de Shannon: hostname gerado por algoritmo tende a ser alto."""
    if not texto:
        return 0.0
    contagem = Counter(texto)
    n = len(texto)
    return -sum((c / n) * math.log2(c / n) for c in contagem.values())


def _dominio_registravel(host: str) -> str:
    """Aproximação de eTLD+1 sem depender da Public Suffix List.

    Trata o caso comum de TLD composto (`com.br`, `co.uk`) olhando o penúltimo
    rótulo. Não é exato para todos os sufixos, mas erra pouco no que importa
    aqui, que é distinguir "marca no domínio" de "marca no subdomínio".
    """
    partes = host.split(".")
    if len(partes) < 2:
        return host
    if len(partes) >= 3 and len(partes[-2]) <= 3:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def _porta_segura(p) -> bool:
    """urlparse avalia a porta só no acesso ao atributo, e levanta ValueError
    em porta não numérica (`http://host:The/...`). URL extraída de e-mail vem
    malformada com frequência, então o acesso precisa ser protegido aqui —
    proteger só o urlparse() não basta."""
    try:
        return p.port is not None
    except ValueError:
        return True  # porta presente e inválida já é sinal por si só


def _host_seguro(p) -> str:
    try:
        return (p.hostname or "").lower()
    except ValueError:
        return ""


def extrair_features(url: str) -> dict:
    try:
        p = urlparse(url if "://" in url else f"http://{url}")
    except ValueError:
        p = urlparse("http://")

    host = _host_seguro(p)
    path = p.path or ""
    query = p.query or ""
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    dominio = _dominio_registravel(host)
    fora_do_dominio = f"{host[: max(0, len(host) - len(dominio))]}{path}{query}".lower()

    tokens_host = TOKEN_RE.findall(host)
    letras = [c for c in host if c.isalpha()]
    consoantes = [c for c in letras if c not in "aeiou"]

    return {
        "url_len": len(url),
        "host_len": len(host),
        "path_len": len(path),
        "query_len": len(query),
        "n_pontos": host.count("."),
        "n_hifens": host.count("-"),
        "n_subdominios": max(0, host.count(".") - dominio.count(".")),
        "n_segmentos_path": len([s for s in path.split("/") if s]),
        "n_params": len([q for q in query.split("&") if q]),
        "host_e_ip": int(bool(IPV4_RE.match(host)) or ":" in host),
        "tem_porta": int(_porta_segura(p)),
        "tem_arroba": int("@" in url),
        "e_https": int(p.scheme == "https"),
        "tem_punycode": int("xn--" in host),
        "tem_hex_encoding": int(bool(HEX_RE.search(url))),
        # `//` no meio do caminho é usado para confundir parser e usuário.
        "tem_barra_dupla_path": int("//" in path),
        "n_digitos_host": sum(c.isdigit() for c in host),
        "prop_digitos_host": (
            sum(c.isdigit() for c in host) / len(host) if host else 0.0
        ),
        "entropia_host": _entropia(host),
        "maior_token_host": max((len(t) for t in tokens_host), default=0),
        "prop_consoantes_host": len(consoantes) / len(letras) if letras else 0.0,
        "tld_suspeito": int(tld in TLDS_SUSPEITOS),
        "e_encurtador": int(dominio in ENCURTADORES),
        "marca_no_host": int(any(m in host for m in MARCAS)),
        # O sinal forte: a marca aparece, mas NÃO no domínio registrável.
        "marca_fora_do_dominio": int(
            any(m in fora_do_dominio for m in MARCAS)
            and not any(m in dominio for m in MARCAS)
        ),
        "n_iscas": sum(1 for i in ISCAS if i in path.lower() or i in query.lower()),
    }


def extrair_lote(urls) -> "pd.DataFrame":  # noqa: F821
    import pandas as pd

    return pd.DataFrame([extrair_features(u) for u in urls], columns=FEATURE_NAMES)


if __name__ == "__main__":
    exemplos = [
        "http://bradesc0-seguranca.tk/login/atualizar.php",
        "https://www.bradesco.com.br/html/classic/index.shtm",
        "http://192.168.4.11:8080/bins/mozi.m",
        "http://secure-itau.com.br.verificacao.xyz/conta?id=99",
        "https://github.com/anthropics/claude-code",
        "http://bit.ly/3xK9aB",
    ]
    for u in exemplos:
        f = extrair_features(u)
        ativos = {k: v for k, v in f.items() if v not in (0, 0.0)}
        print(f"\n{u}")
        print(f"  {ativos}")
