"""Esquema do corpus PT-BR como código — docs/CORPUS_SCHEMA.md v1.

As restrições metodológicas do corpus viram invariantes executáveis. Um registro
que viola o protocolo não entra: não por disciplina de quem digita, mas porque o
validador recusa.

Tipos e enums ficam aqui; as regras semânticas ficam em `validate_corpus.py`,
cada uma com identificador estável (R01..R12) para poder ser reportada e testada
individualmente.
"""
import hashlib
import re
from enum import Enum

from pydantic import BaseModel, Field

WS_RE = re.compile(r"\s+")

ESQUEMA_VERSAO = "1.0"


class Canal(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class Rotulo(str, Enum):
    GOLPE = "golpe"
    SEGURO = "seguro"


class Natureza(str, Enum):
    REAL = "real"
    SINTETICO = "sintetico"


class FonteAquisicao(str, Enum):
    DOACAO = "doacao"
    CORPUS_PUBLICO = "corpus_publico"
    COLETA_PROPRIA = "coleta_propria"
    GERACAO_INTERNA = "geracao_interna"


class MetodoGeracao(str, Enum):
    NENHUM = "nenhum"
    TEMPLATE = "template"
    LLM = "llm"


class Transformacao(str, Enum):
    ORIGINAL = "original"
    TRADUZIDO = "traduzido"
    NORMALIZADO = "normalizado"


class BaseJuridica(str, Enum):
    CONSENTIMENTO = "consentimento"
    LEGITIMO_INTERESSE = "legitimo_interesse"
    PESQUISA_ACADEMICA = "pesquisa_academica"
    DADO_PROPRIO = "dado_proprio"
    FONTE_PUBLICA = "fonte_publica"


class Particao(str, Enum):
    TREINO = "treino"
    GOLD_TEST = "gold_test"
    STRESS_TEST = "stress_test"
    RESERVA = "reserva"


class MetodoAgrupamento(str, Enum):
    """Como `grupo_campanha` foi atribuído — mantém a clusterização auditável."""
    MANUAL = "manual"
    HASH = "hash"
    MINHASH = "minhash"
    EMBEDDING = "embedding"
    ADJUDICACAO = "adjudicacao"
    SINGLETON = "singleton"


# Base jurídica que admite republicação do registro.
BASES_PUBLICAVEIS = {
    BaseJuridica.CONSENTIMENTO,
    BaseJuridica.DADO_PROPRIO,
    BaseJuridica.FONTE_PUBLICA,
}

ARQUETIPOS_GOLPE = {
    "pix", "boleto", "serasa_spc", "receita_restituicao", "inss",
    "correios_taxa", "bloqueio_bancario", "cartao_clonado", "premio_sorteio",
    "whatsapp_clonado", "vaga_emprego", "delivery", "conta_consumo",
    "multa_detran", "auxilio_governo", "cobranca_falsa", "suporte_tecnico",
    "investimento", "outro_golpe",
}

ARQUETIPOS_SEGURO = {
    "transacional_banco", "nota_fiscal", "confirmacao_compra", "newsletter",
    "marketing_legitimo", "cobranca_real", "notificacao_servico",
    "comunicacao_pessoal", "comunicacao_corporativa", "outro_legitimo",
}

ARQUETIPOS = ARQUETIPOS_GOLPE | ARQUETIPOS_SEGURO


def normalizar(texto: str) -> str:
    """Minúsculas e espaços colapsados — a mesma normalização da dedupe."""
    return WS_RE.sub(" ", (texto or "").lower()).strip()


def calcular_hash(texto: str) -> str:
    return hashlib.sha256(normalizar(texto).encode("utf-8")).hexdigest()


class Registro(BaseModel):
    """Um registro do corpus. Tipos e enums; semântica em validate_corpus.py."""

    model_config = {"use_enum_values": True, "extra": "forbid"}

    # conteúdo
    id: str
    texto: str = Field(min_length=10)
    assunto: str | None = None
    canal: Canal
    rotulo: Rotulo
    arquetipo: str
    marca: str | None = None

    # proveniência — quatro dimensões independentes
    natureza: Natureza
    fonte_aquisicao: FonteAquisicao
    metodo_geracao: MetodoGeracao
    transformacao: Transformacao

    # agrupamento (controle de vazamento)
    familia_template: str | None = None
    grupo_campanha: str | None = None
    grupo_campanha_metodo: MetodoAgrupamento | None = None
    grupo_campanha_confianca: float | None = Field(default=None, ge=0.0, le=1.0)

    # governança
    anonimizado: bool
    proveniencia_verificada: bool
    uso_pesquisa: bool
    redistribuivel: bool
    base_juridica: BaseJuridica
    revisado: bool
    revisor: str | None = None

    # organização
    particao: Particao
    criado_em: str
    hash: str


CAMPOS = list(Registro.model_fields.keys())
