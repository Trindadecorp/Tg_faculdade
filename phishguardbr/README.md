# PhishGuard BR

Plataforma de detecção de phishing por e-mail com contexto brasileiro (PIX, bancos, órgãos
públicos). TCC — Fatec Indaiatuba, ADS 2026. Autores: Leonardo & Pedro Trindade.

Documentação completa em `../planejamento_tg.md` (produto) e `../arquitetura_tecnica.md`
(banco de dados e infraestrutura).

## Stack

- **Frontend/API**: Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui
- **Banco**: PostgreSQL 16 + Prisma + PgBouncer
- **Autenticação**: Firebase Auth (validação de ID token no backend)
- **ML**: Python 3.11 (scikit-learn, TensorFlow, spaCy pt_core_news_lg)
- **Add-on**: Google Apps Script (CardService, Gmail contextual trigger)

## Estrutura

```
frontend/     Next.js — API routes, painel RiskOps, PhishRisk Engine (TS)
gmail-addon/  Google Apps Script — Add-on Gmail
ml/           Pipeline Python — dados, features, treino, modelos
data/         Base de marcas/domínios BR (versionada como dado)
docs/         Política de privacidade, modelo de ameaças
tests/        Unitários, integração, adversarial
```

## Bootstrap (Fase 1 — Fundação)

```bash
cp .env.example .env
docker compose up -d
cd frontend && npm install
npx prisma migrate deploy
npx prisma db seed
```

pgAdmin em `http://localhost:5050`. Preencher as chaves em `.env` (Firebase Admin SDK,
Anthropic, VirusTotal, Google Safe Browsing) antes de subir a API.

```bash
cd ml && pip install -r requirements.txt
python -m spacy download pt_core_news_lg
```

## Roteiro

Ver `planejamento_tg.md` §10 para o roteiro completo (Fase 1 a 7) e
`arquitetura_tecnica.md` §10 para o checklist de banco de dados por fase.
