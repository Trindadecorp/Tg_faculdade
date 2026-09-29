"""PhishRisk Engine — combinação ponderada dos módulos de risco (§6.5).

Score final de 0 a 100 a partir de quatro módulos e um modificador:

    autenticação 25% | NLP 30% | URL 25% | marca 20% | anexo (modificador)

**Renormalização de pesos.** Nem todo módulo se aplica a toda mensagem: um texto
colado no painel não tem cabeçalho para autenticar, e uma mensagem sem link não
tem URL para analisar. Um módulo inaplicável não contribui com zero — zero seria
afirmar "não há risco", o que é diferente de "não há como verificar". Ele é
retirado da média e os pesos dos demais são reescalados para somar 1.

**Roteamento por canal.** O experimento de transferência
(`reports/CHANNEL_TRANSFER_REPORT.md`) mostrou que um modelo de e-mail aplicado
a SMS cai de F1 0,97 para 0,35, e vice-versa. O módulo NLP carrega, portanto, o
modelo do canal da mensagem — não um modelo único.

Uso:
    from src.scoring.engine import PhishRiskEngine
    engine = PhishRiskEngine()
    r = engine.analisar("Sua conta sera bloqueada...", canal="sms")
    print(r.score, r.classificacao)
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import joblib

from src.features.url_features import (
    ISCAS,
    MARCAS,
    _dominio_registravel,
    extrair_features,
    extrair_lote,
)

ML_DIR = Path(__file__).resolve().parents[2]
MODELS = ML_DIR / "models"

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")

PESOS = {"auth": 0.25, "nlp": 0.30, "url": 0.25, "marca": 0.20}

# Limiares de §6.7. A faixa "suspeito" existe para não forçar binário numa
# decisão que o usuário precisa poder julgar.
LIMIAR_SUSPEITO = 40
LIMIAR_GOLPE = 70

# Domínio oficial de cada marca, para detectar imitação: marca citada no texto
# mas com link apontando para outro domínio registrável.
DOMINIOS_OFICIAIS = {
    "bradesco": "bradesco.com.br", "itau": "itau.com.br",
    "santander": "santander.com.br", "caixa": "caixa.gov.br",
    "nubank": "nubank.com.br", "bancodobrasil": "bb.com.br",
    "correios": "correios.com.br", "serasa": "serasa.com.br",
    "mercadolivre": "mercadolivre.com.br", "mercadopago": "mercadopago.com.br",
    "pagseguro": "pagseguro.uol.com.br", "picpay": "picpay.com",
    "netflix": "netflix.com", "spotify": "spotify.com",
    "whatsapp": "whatsapp.com", "instagram": "instagram.com",
    "facebook": "facebook.com", "google": "google.com",
    "microsoft": "microsoft.com", "apple": "apple.com",
    "amazon": "amazon.com", "paypal": "paypal.com", "steam": "steampowered.com",
    "gov": "gov.br", "receita": "gov.br", "inss": "gov.br", "detran": "gov.br",
}

# Palavras funcionais PT/EN — nunca são explicação útil de risco.
FUNCIONAIS = {
    "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas", "para", "por",
    "com", "sem", "que", "se", "os", "as", "um", "uma", "ao", "aos", "e", "ou",
    "seu", "sua", "seus", "suas", "este", "esta", "isso", "mais", "ja", "ser",
    "the", "and", "for", "you", "that", "this", "with", "from", "not", "are",
    "was", "will", "your", "can", "all", "has", "but", "our", "they", "http",
    "https", "www", "com", "br", "org", "net",
}

EXTENSOES_PERIGOSAS = {
    ".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".vbs", ".js", ".jar",
    ".msi", ".ps1", ".lnk", ".hta", ".iso", ".img",
}


@dataclass
class ResultadoModulo:
    nome: str
    aplicavel: bool
    score: float = 0.0            # 0-100
    peso_efetivo: float = 0.0     # após renormalização
    sinais: list[str] = field(default_factory=list)
    motivo: str = ""              # por que não se aplica


@dataclass
class Analise:
    score: float
    classificacao: str            # seguro | suspeito | golpe
    canal: str
    modulos: list[ResultadoModulo]
    modificador_anexo: float = 0.0

    def explicacao(self) -> list[str]:
        """Sinais de todos os módulos aplicáveis, para exibição ao usuário."""
        out = []
        for m in self.modulos:
            if m.aplicavel:
                out.extend(m.sinais)
            elif m.motivo:
                out.append(f"[{m.nome}] não verificável: {m.motivo}")
        return out


class PhishRiskEngine:
    def __init__(self, models_dir: Path = MODELS):
        self.models_dir = models_dir
        self._nlp: dict = {}
        self._url = None

    # ---------------------------------------------------------- carga preguiçosa
    def _modelo_nlp(self, canal: str):
        if canal not in self._nlp:
            caminho = self.models_dir / f"nlp_{canal}.joblib"
            self._nlp[canal] = joblib.load(caminho) if caminho.exists() else None
        return self._nlp[canal]

    def _modelo_url(self):
        if self._url is None:
            caminho = self.models_dir / "url.joblib"
            self._url = joblib.load(caminho) if caminho.exists() else False
        return self._url or None

    # ---------------------------------------------------------------- módulos
    def _mod_nlp(self, texto: str, canal: str) -> ResultadoModulo:
        modelo = self._modelo_nlp(canal)
        if modelo is None:
            return ResultadoModulo(
                "nlp", False, motivo=f"sem modelo treinado para o canal '{canal}'"
            )
        if not texto.strip():
            return ResultadoModulo("nlp", False, motivo="mensagem sem texto")

        prob = float(modelo.predict_proba([texto])[0][1])
        sinais = [f"[nlp] probabilidade de golpe pelo texto: {prob * 100:.0f}%"]
        for termo in self._termos_decisivos(modelo, texto):
            sinais.append(f"[nlp] termo de risco: «{termo}»")
        return ResultadoModulo("nlp", True, prob * 100, sinais=sinais)

    @staticmethod
    def _termos_decisivos(modelo, texto: str, n: int = 4) -> list[str]:
        """Termos presentes no texto com maior coeficiente positivo (XAI, §3.2.6).

        Palavras funcionais são descartadas da explicação: quando o modelo é
        aplicado a um idioma fora do seu treino, preposições e artigos recebem
        coeficiente alto por acidente e não explicam nada ao usuário. Filtrar
        aqui é paliativo — a correção real é ter modelo do idioma da mensagem.
        """
        try:
            vec, clf = modelo.named_steps["tfidf"], modelo.named_steps["clf"]
            nomes = vec.get_feature_names_out()
            coefs = clf.coef_[0]
            presentes = vec.transform([texto]).nonzero()[1]
            ranked = sorted(presentes, key=lambda i: -coefs[i])
            out = []
            for i in ranked:
                if coefs[i] <= 0 or len(out) >= n:
                    break
                termo = nomes[i]
                if len(termo) < 4 or all(t in FUNCIONAIS for t in termo.split()):
                    continue
                out.append(termo)
            return out
        except Exception:
            return []

    def _mod_url(self, texto: str) -> ResultadoModulo:
        urls = URL_RE.findall(texto)
        if not urls:
            return ResultadoModulo("url", False, motivo="mensagem sem links")

        modelo = self._modelo_url()
        if modelo is None:
            return ResultadoModulo("url", False, motivo="modelo de URL não treinado")

        probs = modelo.predict_proba(extrair_lote(urls))[:, 1]
        pior = int(probs.argmax())
        # A pior URL define o risco: uma mensagem com nove links legítimos e um
        # malicioso é perigosa, e a média diluiria exatamente o que importa.
        score = float(probs[pior]) * 100

        sinais = [f"[url] {len(urls)} link(s); pior risco {score:.0f}% em {urls[pior][:70]}"]
        f = extrair_features(urls[pior])
        if f["host_e_ip"]:
            sinais.append("[url] endereço IP no lugar do domínio")
        if f["tld_suspeito"]:
            sinais.append("[url] domínio de topo associado a abuso")
        if f["e_encurtador"]:
            sinais.append("[url] encurtador de link — destino oculto")
        if f["tem_punycode"]:
            sinais.append("[url] punycode: caracteres que imitam letras latinas")
        if f["marca_fora_do_dominio"]:
            sinais.append("[url] marca aparece fora do domínio real do link")
        return ResultadoModulo("url", True, score, sinais=sinais)

    @staticmethod
    def _marcas_citadas(baixo: str) -> set[str]:
        """Marcas citadas como PALAVRA, não como subcadeia.

        Busca por subcadeia produz falso positivo em marca curta embutida em
        palavra comum: «oi» casa dentro de «foi», «bb» dentro de «abba». A
        fronteira de palavra elimina essa classe de erro.
        """
        return {
            m for m in MARCAS
            if re.search(rf"(?<![0-9a-zà-ú]){re.escape(m)}(?![0-9a-zà-ú])", baixo)
        }

    def _mod_marca(self, texto: str) -> ResultadoModulo:
        baixo = texto.lower()
        citadas = self._marcas_citadas(baixo)
        if not citadas:
            return ResultadoModulo("marca", False, motivo="nenhuma marca citada")

        urls = URL_RE.findall(texto)
        dominios = {_dominio_registravel((urlparse(u).hostname or "").lower()) for u in urls}
        dominios.discard("")

        sinais = [f"[marca] cita: {', '.join(sorted(citadas))}"]
        score = 0.0

        for marca in citadas:
            oficial = DOMINIOS_OFICIAIS.get(marca)
            if not oficial or not dominios:
                continue
            if not any(d == oficial or d.endswith("." + oficial) for d in dominios):
                score = max(score, 85.0)
                sinais.append(
                    f"[marca] cita «{marca}» mas nenhum link aponta para {oficial}"
                )

        if score == 0.0 and dominios:
            score = 10.0
            sinais.append("[marca] links conferem com a marca citada")
        elif score == 0.0:
            # Marca citada sem link nenhum: não dá para confirmar nem negar.
            score = 30.0
            sinais.append("[marca] marca citada sem link para conferir")

        iscas = [i for i in ISCAS if i in baixo]
        if iscas and score >= 30:
            score = min(100.0, score + 5 * len(iscas[:3]))
            sinais.append(f"[marca] pedido típico de captura: {', '.join(iscas[:3])}")
        return ResultadoModulo("marca", True, score, sinais=sinais)

    @staticmethod
    def _mod_auth(cabecalhos: dict | None) -> ResultadoModulo:
        if not cabecalhos:
            return ResultadoModulo(
                "auth", False,
                motivo="cabeçalhos SPF/DKIM/DMARC não disponíveis nesta mensagem",
            )
        score, sinais = 0.0, []
        for campo, peso in (("spf", 30), ("dkim", 35), ("dmarc", 35)):
            valor = str(cabecalhos.get(campo, "")).lower()
            if valor in ("fail", "softfail", "none", "permerror"):
                score += peso
                sinais.append(f"[auth] {campo.upper()} = {valor}")
            elif valor == "pass":
                sinais.append(f"[auth] {campo.upper()} válido")
        return ResultadoModulo("auth", True, min(score, 100.0), sinais=sinais)

    @staticmethod
    def _modificador_anexo(anexos: list[str] | None) -> tuple[float, list[str]]:
        """Modificador aditivo, não módulo: anexo perigoso agrava, ausência não absolve."""
        if not anexos:
            return 0.0, []
        sinais, bonus = [], 0.0
        for nome in anexos:
            ext = Path(nome).suffix.lower()
            if ext in EXTENSOES_PERIGOSAS:
                bonus = max(bonus, 25.0)
                sinais.append(f"[anexo] extensão executável: {nome}")
            elif ext in (".zip", ".rar", ".7z"):
                bonus = max(bonus, 10.0)
                sinais.append(f"[anexo] arquivo compactado (conteúdo não inspecionado): {nome}")
        return bonus, sinais

    # ----------------------------------------------------------------- score
    def analisar(
        self,
        texto: str,
        canal: str = "email",
        cabecalhos: dict | None = None,
        anexos: list[str] | None = None,
    ) -> Analise:
        modulos = [
            self._mod_auth(cabecalhos),
            self._mod_nlp(texto, canal),
            self._mod_url(texto),
            self._mod_marca(texto),
        ]

        aplicaveis = [m for m in modulos if m.aplicavel]
        if not aplicaveis:
            return Analise(0.0, "seguro", canal, modulos)

        # Renormalização: os pesos dos módulos aplicáveis passam a somar 1.
        soma = sum(PESOS[m.nome] for m in aplicaveis)
        score = 0.0
        for m in aplicaveis:
            m.peso_efetivo = PESOS[m.nome] / soma
            score += m.score * m.peso_efetivo

        bonus, sinais_anexo = self._modificador_anexo(anexos)
        score = min(100.0, score + bonus)
        if sinais_anexo:
            modulos[0].sinais.extend(sinais_anexo) if modulos[0].aplicavel else None

        classificacao = (
            "golpe" if score >= LIMIAR_GOLPE
            else "suspeito" if score >= LIMIAR_SUSPEITO
            else "seguro"
        )
        analise = Analise(round(score, 1), classificacao, canal, modulos, bonus)
        if sinais_anexo:
            analise.modulos.append(
                ResultadoModulo("anexo", True, bonus, sinais=sinais_anexo)
            )
        return analise
