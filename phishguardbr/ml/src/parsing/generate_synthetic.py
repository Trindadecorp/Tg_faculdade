"""Gera exemplos sintéticos PT-BR de golpe (smishing/phishing) e mensagens
legítimas via Claude, para o corpus de treino (planejamento_tg.md §5.1, §5.3
etapa 1) — a contribuição central deste TG: preencher o gap de corpus público
em português brasileiro (ver ml/data/DATA_CARD.md).

Requer ANTHROPIC_API_KEY em phishguardbr/.env (nunca commitar essa chave).
Custo estimado e fluxo de revisão: ver ml/data/synthetic/README.md.

Uso (a partir de ml/):
    python -m src.parsing.generate_synthetic --count 60
"""
import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel

OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "raw_v1.jsonl"
MODEL = "claude-sonnet-5"  # decisão do projeto — planejamento_tg.md §4.2

GOLPE_CATEGORIES = [
    "urgencia", "medo", "autoridade", "escassez", "confianca",
    "financeiro_br", "acao_solicitada",
]
BRAND_CONTEXTS = [
    "Banco do Brasil", "Itaú", "Bradesco", "Nubank", "Caixa Econômica",
    "Correios", "Receita Federal", "gov.br", "DETRAN", "INSS", "Serasa",
]

SYSTEM_PROMPT = """Você gera dados de treino sintéticos para um classificador \
DEFENSIVO de phishing/smishing em português brasileiro (projeto acadêmico PhishGuard BR). \
Cada exemplo deve imitar o estilo real de golpes ou mensagens legítimas no Brasil, mas o \
conteúdo é inteiramente fictício: nunca use nomes de pessoas reais, telefones, CPF, links \
funcionais ou dados verídicos. Varie vocabulário, estrutura e comprimento a cada exemplo — \
não repita frases-modelo. Responda somente com o JSON pedido."""


class SyntheticExample(BaseModel):
    channel: Literal["email", "sms", "whatsapp"]
    label: Literal["golpe", "suspeito", "seguro"]
    category: str  # uma de GOLPE_CATEGORIES, ou "legitimo" quando label == "seguro"
    brand_context: Optional[str] = None
    text: str


class SyntheticBatch(BaseModel):
    examples: list[SyntheticExample]


def _build_prompt(batch_size: int) -> str:
    golpe_n = round(batch_size * 0.6)
    seguro_n = batch_size - golpe_n
    return (
        f"Gere {batch_size} mensagens em português brasileiro para um dataset de "
        f"treino de detecção de fraude:\n"
        f"- {golpe_n} mensagens de GOLPE (label=golpe), distribuídas entre as categorias "
        f"{GOLPE_CATEGORIES}, citando contexto brasileiro real como PIX e marcas/órgãos "
        f"como {', '.join(BRAND_CONTEXTS)} — sempre com dados fictícios.\n"
        f"- {seguro_n} mensagens LEGÍTIMAS (label=seguro, category=legitimo): "
        f"transacionais e notificações reais de banco/e-commerce/governo, usando "
        f"vocabulário de urgência de forma genuína (confirmação de compra, código de "
        f"verificação, cobrança real) — para servir de contraste e reduzir falso "
        f"positivo.\n"
        f"Varie o canal entre email, sms e whatsapp. Não repita estrutura entre exemplos."
    )


def generate_batch(client: anthropic.Anthropic, batch_size: int) -> list[SyntheticExample]:
    response = client.messages.parse(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_prompt(batch_size)}],
        output_format=SyntheticBatch,
    )
    return response.parsed_output.examples


def _hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()


def load_seen_hashes() -> set[str]:
    if not OUT_PATH.exists():
        return set()
    seen = set()
    with open(OUT_PATH, encoding="utf-8") as f:
        for line in f:
            seen.add(json.loads(line)["text_hash"])
    return seen


def main(target: int, batch_size: int = 20) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic()
    seen = load_seen_hashes()
    written = 0

    with open(OUT_PATH, "a", encoding="utf-8") as f:
        while written < target:
            n = min(batch_size, target - written)
            for ex in generate_batch(client, n):
                h = _hash(ex.text)
                if h in seen:
                    continue
                seen.add(h)
                row = {
                    "id": str(uuid.uuid4()),
                    "text_hash": h,
                    "channel": ex.channel,
                    "label": ex.label,
                    "category": ex.category,
                    "brand_context": ex.brand_context,
                    "text": ex.text,
                    "model": MODEL,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "reviewed": False,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
            print(f"{written}/{target} gerados")

    print(
        f"OK: {OUT_PATH}\n"
        "Lembrete (obrigatório — planejamento_tg.md §5.3): revisar manualmente cada "
        "linha nova (reviewed=false) antes de usar em treino. Nunca treinar sobre "
        "exemplo não revisado."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=60, help="total de exemplos a gerar")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()
    main(args.count, args.batch_size)
