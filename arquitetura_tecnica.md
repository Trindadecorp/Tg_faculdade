# PhishGuard BR — Arquitetura Técnica e Modelo de Dados

> Documento complementar ao `planejamento_tg.md`
> Fatec Indaiatuba — ADS | 2026 | Autores: Leonardo & Pedro Trindade | Orientador: Prof. Michel Moron Munhoz
> Escopo deste documento: **banco de dados (PostgreSQL), modelo relacional, relacionamentos e
> requisitos técnicos de desenvolvimento.**

---

## 0. Decisões que este documento fixa

| Tema | `planejamento_tg.md` (v2.0) | **Este documento** | Motivo |
|---|---|---|---|
| Banco de dados | Firebase / Firestore (NoSQL) | **PostgreSQL 16 (relacional)** | Os dados do produto são relacionais (análise → componentes → sinais → feedback → curadoria → retreino). Um modelo ER explícito é mais defensável na banca e mais simples de auditar para LGPD. |
| Autenticação | Firebase Auth | **Firebase Auth (mantido)** | Login social, MFA e verificação de e-mail resolvidos. O backend só valida o *ID token* e mapeia para uma linha em `users`. |
| ORM / migrações | — | **Prisma** (TypeScript, já combina com Next.js 14) | Migrações versionadas, tipos gerados, `prisma migrate` no CI. |
| Administração | — | **pgAdmin 4** | Inspeção, consultas ad-hoc e diagrama ER durante o desenvolvimento. |
| Hospedagem | Firebase / GCP | **PostgreSQL auto-gerenciado** — Docker no desenvolvimento, servidor dedicado/VPS na entrega, administrado via pgAdmin | *(Premissa — confirmar. Se preferir serviço gerenciado, ver §9.9.)* |

> ⚠️ **Pendência de consistência.** O `planejamento_tg.md` ainda cita Firestore nas seções
> §3.1, §4.3, §8.2 e §13. Após validação deste documento, essas seções devem ser atualizadas
> para "PostgreSQL para dados + Firebase Auth para identidade".

---

## 1. Princípios do modelo de dados

1. **Nunca persistir conteúdo de mensagem.** Nenhuma tabela armazena corpo, assunto, HTML,
   anexo ou remetente em claro. Só entram: score, componentes, tipos de sinal, *hashes*
   SHA-256, timestamps e canal. Regra herdada de `planejamento_tg.md` §8.2 (AMEAÇA 3 — LGPD).
2. **Identificadores.** Chave primária `uuid` gerada por `gen_random_uuid()` em todas as
   tabelas de domínio; `bigint identity` apenas em tabelas de log de alto volume.
3. **Tempo.** `timestamptz` sempre, valor padrão `now()`, fuso de referência `America/Sao_Paulo`
   apenas na apresentação.
4. **Hashes.** `text` em hexadecimal (SHA-256), 64 caracteres. Coluna sempre sufixada `_hash`
   ou `_sha256`.
5. **Enumerações** são tipos `ENUM` nativos do PostgreSQL (§4). Catálogos que crescem com o
   tempo (tipos de sinal) são tabela de referência, não `ENUM`.
6. **Exclusão.** FKs de dados efêmeros usam `ON DELETE CASCADE`; FKs de dados que sobrevivem à
   retenção de 90 dias (feedback, curadoria) usam `ON DELETE SET NULL` + *snapshot* (§8).
7. **Multi-tenant.** Toda linha de dado operacional carrega `org_id`. Isolamento por
   `org_id` na camada de aplicação; RLS opcional descrita em §9.7.

---

## 2. Domínios (agrupamento lógico das tabelas)

| Domínio | Tabelas | Entra em |
|---|---|---|
| **Identidade & acesso** | `organizations`, `users`, `org_settings` | Núcleo (MVP) |
| **Análise** | `model_versions`, `analyses`, `analysis_module_scores`, `analysis_signals`, `signal_catalog` | Núcleo (MVP) |
| **Feedback & curadoria** | `feedback`, `curation_items` | Núcleo (MVP) |
| **Base de conhecimento** | `brands`, `brand_domains` | Núcleo (MVP) |
| **Acesso programático** | `api_keys` | Extensão |
| **LGPD & auditoria** | `consents`, `data_subject_requests`, `audit_log`, `email_donations` | Extensão |
| **Inteligência de campanha** | `detected_campaigns`, `campaign_analyses` | Extensão |

---

## 3. Diagrama Entidade-Relacionamento (núcleo)

```mermaid
erDiagram
    organizations ||--o{ users : "possui"
    organizations ||--|| org_settings : "configura"
    organizations ||--o{ analyses : "gera"
    organizations ||--o{ api_keys : "emite"

    users ||--o{ analyses : "solicita (opcional)"
    users ||--o{ feedback : "envia"
    users ||--o{ curation_items : "cura"
    users ||--o{ consents : "concede"
    users ||--o{ data_subject_requests : "abre"

    model_versions ||--o{ analyses : "produz score"
    model_versions ||--o{ curation_items : "consome no retreino"

    analyses ||--o{ analysis_module_scores : "decompõe em"
    analyses ||--o{ analysis_signals : "dispara"
    analyses ||--o{ feedback : "recebe"
    analyses ||--o{ curation_items : "origina"

    signal_catalog ||--o{ analysis_signals : "tipifica"

    feedback ||--o| curation_items : "encaminha para"

    brands ||--o{ brand_domains : "tem domínios"
    brands ||--o{ detected_campaigns : "é impersonada em"

    detected_campaigns ||--o{ campaign_analyses : "agrupa"
    analyses ||--o{ campaign_analyses : "pertence a"

    consents ||--o{ email_donations : "autoriza"
```

### Visão textual das cardinalidades

```
organizations 1───N users
organizations 1───1 org_settings
organizations 1───N analyses
organizations 1───N api_keys

users        1───N analyses           (analyses.user_id NULLABLE — análise via API não tem usuário)
users        1───N feedback
model_versions 1─N analyses           (qual modelo gerou o score)

analyses     1───N analysis_module_scores   (sempre 4: auth, nlp, url, brand)
analyses     1───N analysis_signals
analyses     1───N feedback
analyses     1───N curation_items
feedback     1───0..1 curation_items

signal_catalog 1─N analysis_signals

brands       1───N brand_domains
brands       1───N detected_campaigns  (brand impersonada — NULLABLE)

detected_campaigns N───M analyses      (via campaign_analyses)
consents     1───N email_donations
```

---

## 4. Tipos enumerados

```sql
CREATE TYPE org_type          AS ENUM ('pessoa_fisica', 'pme', 'parceiro');
CREATE TYPE user_role         AS ENUM ('end_user', 'analyst', 'admin');
CREATE TYPE analysis_source   AS ENUM ('addon', 'api', 'upload', 'watch');
CREATE TYPE channel           AS ENUM ('email', 'sms', 'whatsapp', 'outro');
CREATE TYPE classification    AS ENUM ('seguro', 'suspeito', 'golpe', 'indeterminado');
CREATE TYPE score_module      AS ENUM ('auth', 'nlp', 'url', 'brand');
CREATE TYPE feedback_verdict  AS ENUM ('falso_positivo', 'golpe_confirmado', 'nao_sei');
CREATE TYPE curation_status   AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE model_status      AS ENUM ('training', 'active', 'archived', 'rolled_back');
CREATE TYPE brand_category    AS ENUM ('banco', 'governo', 'logistica', 'varejo', 'email', 'outro');
CREATE TYPE consent_purpose   AS ENUM ('uso_produto', 'doacao_corpus');
CREATE TYPE dsr_type          AS ENUM ('exclusao', 'portabilidade', 'revogacao');
CREATE TYPE dsr_status        AS ENUM ('pending', 'in_progress', 'fulfilled', 'rejected');
```

---

## 5. Núcleo (MVP)

### 5.1 `organizations`

Tenant. Uma pessoa física é uma organização de um usuário só.

```sql
CREATE TABLE organizations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text        NOT NULL,
    type        org_type    NOT NULL DEFAULT 'pessoa_fisica',
    created_at  timestamptz NOT NULL DEFAULT now()
);
```

### 5.2 `users`

Espelho local da identidade do Firebase Auth. Criada *just-in-time* no primeiro acesso.

```sql
CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firebase_uid  text        NOT NULL UNIQUE,
    org_id        uuid        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email         citext      NOT NULL,
    display_name  text,
    role          user_role   NOT NULL DEFAULT 'end_user',
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz
);
CREATE INDEX idx_users_org ON users(org_id);
```

> `email` é dado pessoal — é o único PII no banco, coberto por `consents` e sujeito a
> `data_subject_requests`. Necessário para notificação e para o direito de exclusão.

### 5.3 `org_settings`

Threshold configurável por organização (`planejamento_tg.md` §6.7).

```sql
CREATE TABLE org_settings (
    org_id              uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    threshold_suspeito  int  NOT NULL DEFAULT 45 CHECK (threshold_suspeito BETWEEN 1 AND 99),
    threshold_golpe     int  NOT NULL DEFAULT 75 CHECK (threshold_golpe   BETWEEN 1 AND 99),
    updated_by          uuid REFERENCES users(id) ON DELETE SET NULL,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (threshold_golpe > threshold_suspeito)
);
```

### 5.4 `model_versions`

Cada modelo treinado e sua ficha de métricas (`planejamento_tg.md` §5.3 etapa 12).

```sql
CREATE TABLE model_versions (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version               text        NOT NULL UNIQUE,          -- '2.0.1'
    algorithm             text        NOT NULL,                 -- 'xgboost' | 'cnn_bigru' | 'ensemble'
    status                model_status NOT NULL DEFAULT 'training',
    metrics               jsonb       NOT NULL DEFAULT '{}',    -- {auc, ks, f1, precision, recall, fpr_marketing, ...}
    model_card_url        text,
    training_dataset_ref  text,                                 -- ex.: 'email_dataset_v3.parquet'
    trained_at            timestamptz,
    deployed_at           timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_model_active ON model_versions(status) WHERE status = 'active';
```

### 5.5 `analyses`

Uma linha por mensagem analisada. **Somente metadados.**

```sql
CREATE TABLE analyses (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              uuid        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id             uuid        REFERENCES users(id) ON DELETE SET NULL,
    model_version_id    uuid        NOT NULL REFERENCES model_versions(id),
    source              analysis_source NOT NULL,
    channel             channel     NOT NULL DEFAULT 'email',

    final_score         int         NOT NULL CHECK (final_score BETWEEN 0 AND 100),
    classification      classification NOT NULL,
    attachment_modifier numeric(4,1) NOT NULL DEFAULT 0,
    degraded_mode       boolean     NOT NULL DEFAULT false,
    processing_time_ms  int,

    sender_domain_hash  text        NOT NULL,   -- SHA-256 do domínio do remetente
    subject_hash        text,                   -- SHA-256 do assunto normalizado (dedupe/campanha)
    body_sha256         text,                   -- SHA-256 do corpo normalizado (§5.3 etapa 3)
    links_count         int         NOT NULL DEFAULT 0,
    attachments_count   int         NOT NULL DEFAULT 0,

    received_at         timestamptz,            -- header Date da mensagem
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_analyses_org_time   ON analyses(org_id, created_at DESC);
CREATE INDEX idx_analyses_class      ON analyses(classification);
CREATE INDEX idx_analyses_model      ON analyses(model_version_id);
CREATE INDEX idx_analyses_body_hash  ON analyses(body_sha256);
CREATE INDEX idx_analyses_subj_hash  ON analyses(subject_hash);
```

> Não existe coluna de conteúdo. O `sender_domain_hash` permite agrupar campanhas e medir
> reincidência sem identificar o remetente.

### 5.6 `analysis_module_scores`

Decomposição do score nos 4 módulos + renormalização de peso (`planejamento_tg.md` §6.5).

```sql
CREATE TABLE analysis_module_scores (
    analysis_id  uuid        NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    module       score_module NOT NULL,
    raw_score    int         CHECK (raw_score BETWEEN 0 AND 100),   -- NULL = módulo não aplicável
    weight_used  numeric(4,3) NOT NULL,                             -- peso após renormalização
    applicable   boolean     NOT NULL DEFAULT true,
    evidence     jsonb       NOT NULL DEFAULT '[]',                 -- evidências já sanitizadas/hasheadas
    PRIMARY KEY (analysis_id, module)
);
```

### 5.7 `signal_catalog`

Catálogo de tipos de sinal de risco. Tabela de referência (não `ENUM`) porque cresce a cada
iteração do modelo.

```sql
CREATE TABLE signal_catalog (
    code           text PRIMARY KEY,             -- 'anchor_href_mismatch', 'spf_fail', 'cousin_domain'
    module         score_module NOT NULL,
    description    text NOT NULL,
    default_weight int  NOT NULL DEFAULT 0,
    active         boolean NOT NULL DEFAULT true
);
```

### 5.8 `analysis_signals`

Sinais concretos disparados por uma análise. Alimenta `top_techniques` do `/api/v1/stats`.

```sql
CREATE TABLE analysis_signals (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    analysis_id  uuid NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    signal_code  text NOT NULL REFERENCES signal_catalog(code),
    weight       int  NOT NULL DEFAULT 0,
    detail       jsonb NOT NULL DEFAULT '{}',    -- especificidades sanitizadas (sem conteúdo)
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_signals_analysis ON analysis_signals(analysis_id);
CREATE INDEX idx_signals_code     ON analysis_signals(signal_code);
```

### 5.9 `feedback`

Veredito do usuário (`planejamento_tg.md` §9 — `POST /api/v1/feedback`).

```sql
CREATE TABLE feedback (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id  uuid REFERENCES analyses(id) ON DELETE SET NULL,   -- sobrevive à purga de 90 dias
    user_id      uuid REFERENCES users(id)    ON DELETE SET NULL,
    verdict      feedback_verdict NOT NULL,
    comment      text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (analysis_id, user_id)
);
```

### 5.10 `curation_items`

Fila de curadoria humana antes do retreino (`planejamento_tg.md` §8.1 AMEAÇA 5 — anti-poisoning).

```sql
CREATE TABLE curation_items (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    feedback_id            uuid UNIQUE REFERENCES feedback(id) ON DELETE SET NULL,
    analysis_id            uuid REFERENCES analyses(id) ON DELETE SET NULL,
    status                 curation_status NOT NULL DEFAULT 'pending',
    label_final            classification,                 -- rótulo verdade-terreno do curador
    features_snapshot      jsonb NOT NULL DEFAULT '{}',    -- features anonimizadas p/ retreino (§8)
    curator_id             uuid REFERENCES users(id) ON DELETE SET NULL,
    notes                  text,
    curated_at             timestamptz,
    included_in_model_id   uuid REFERENCES model_versions(id) ON DELETE SET NULL,
    created_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_curation_status ON curation_items(status);
```

### 5.11 `brands` e `brand_domains`

Base curada de marcas e órgãos BR (`planejamento_tg.md` §6.4). Versionada como dado, não como
código.

```sql
CREATE TABLE brands (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL UNIQUE,           -- 'Banco do Brasil'
    category    brand_category NOT NULL,
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE brand_domains (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id   uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    domain     citext NOT NULL UNIQUE,          -- 'bb.com.br'
    is_primary boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_brand_domains_brand ON brand_domains(brand_id);
CREATE INDEX idx_brand_domains_trgm  ON brand_domains USING gin (domain gin_trgm_ops);
```

> O índice `gin_trgm_ops` sustenta a detecção de *cousin domain* por similaridade
> (`domain % 'bb-seguranca.com.br'`) e complementa `levenshtein()` da extensão `fuzzystrmatch`.

---

## 6. Extensões (entram após o núcleo)

### 6.1 `api_keys`

```sql
CREATE TABLE api_keys (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name         text NOT NULL,
    key_hash     text NOT NULL UNIQUE,          -- SHA-256 da chave; valor cru exibido uma única vez
    prefix       text NOT NULL,                 -- primeiros 8 caracteres, para identificação
    scopes       text[] NOT NULL DEFAULT '{analyze}',
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    revoked_at   timestamptz
);
```

### 6.2 LGPD — `consents`, `data_subject_requests`

```sql
CREATE TABLE consents (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose        consent_purpose NOT NULL,
    granted        boolean NOT NULL,
    policy_version text NOT NULL,               -- versão da política aceita
    granted_at     timestamptz NOT NULL DEFAULT now(),
    revoked_at     timestamptz
);
CREATE INDEX idx_consents_user ON consents(user_id, purpose);

CREATE TABLE data_subject_requests (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type          dsr_type   NOT NULL,
    status        dsr_status NOT NULL DEFAULT 'pending',
    requested_at  timestamptz NOT NULL DEFAULT now(),
    fulfilled_at  timestamptz,
    notes         text
);
```

### 6.3 `audit_log`

Registro das Operações de Tratamento (ROPA — `planejamento_tg.md` §8.2).

```sql
CREATE TABLE audit_log (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id uuid,                         -- sem FK: log preservado mesmo após exclusão do usuário
    action        text NOT NULL,                -- 'analysis.create', 'threshold.update', 'model.deploy'
    entity_type   text,
    entity_id     text,
    ip_hash       text,                         -- SHA-256 do IP
    metadata      jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_time   ON audit_log(created_at DESC);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
```

### 6.4 `email_donations`

Doações consentidas para o corpus (`planejamento_tg.md` §5.1). **O conteúdo vai para
*object storage* (bucket GCS); a tabela guarda só o ponteiro e o metadado.**

```sql
CREATE TABLE email_donations (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    donor_user_id         uuid REFERENCES users(id) ON DELETE SET NULL,
    consent_id            uuid NOT NULL REFERENCES consents(id) ON DELETE RESTRICT,
    channel               channel NOT NULL,
    label                 classification,
    storage_ref           text NOT NULL,        -- 'gs://phishguard-corpus/donations/<uuid>.eml'
    anonymized            boolean NOT NULL DEFAULT false,
    ingested_into_model_id uuid REFERENCES model_versions(id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now()
);
```

### 6.5 Campanhas — `detected_campaigns`, `campaign_analyses`

```sql
CREATE TABLE detected_campaigns (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 text NOT NULL,
    common_signal_code   text REFERENCES signal_catalog(code),
    impersonated_brand_id uuid REFERENCES brands(id) ON DELETE SET NULL,
    first_seen           timestamptz NOT NULL,
    last_seen            timestamptz NOT NULL,
    analyses_count       int NOT NULL DEFAULT 0,
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE campaign_analyses (
    campaign_id uuid NOT NULL REFERENCES detected_campaigns(id) ON DELETE CASCADE,
    analysis_id uuid NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, analysis_id)
);
```

---

## 7. Relacionamentos — resumo e integridade referencial

| # | Pai | Filho | Cardinalidade | FK | `ON DELETE` |
|---|---|---|---|---|---|
| 1 | `organizations` | `users` | 1 : N | `users.org_id` | `CASCADE` |
| 2 | `organizations` | `org_settings` | 1 : 1 | `org_settings.org_id` | `CASCADE` |
| 3 | `organizations` | `analyses` | 1 : N | `analyses.org_id` | `CASCADE` |
| 4 | `organizations` | `api_keys` | 1 : N | `api_keys.org_id` | `CASCADE` |
| 5 | `users` | `analyses` | 1 : N (opcional) | `analyses.user_id` | `SET NULL` |
| 6 | `model_versions` | `analyses` | 1 : N | `analyses.model_version_id` | `RESTRICT` (padrão) |
| 7 | `analyses` | `analysis_module_scores` | 1 : N (=4) | `analysis_id` | `CASCADE` |
| 8 | `analyses` | `analysis_signals` | 1 : N | `analysis_id` | `CASCADE` |
| 9 | `signal_catalog` | `analysis_signals` | 1 : N | `signal_code` | `RESTRICT` |
| 10 | `analyses` | `feedback` | 1 : N | `feedback.analysis_id` | `SET NULL` |
| 11 | `users` | `feedback` | 1 : N | `feedback.user_id` | `SET NULL` |
| 12 | `feedback` | `curation_items` | 1 : 0..1 | `curation_items.feedback_id` | `SET NULL` |
| 13 | `analyses` | `curation_items` | 1 : N | `curation_items.analysis_id` | `SET NULL` |
| 14 | `model_versions` | `curation_items` | 1 : N | `included_in_model_id` | `SET NULL` |
| 15 | `brands` | `brand_domains` | 1 : N | `brand_domains.brand_id` | `CASCADE` |
| 16 | `users` | `consents` | 1 : N | `consents.user_id` | `CASCADE` |
| 17 | `consents` | `email_donations` | 1 : N | `email_donations.consent_id` | `RESTRICT` |
| 18 | `users` | `data_subject_requests` | 1 : N | `dsr.user_id` | `CASCADE` |
| 19 | `detected_campaigns` | `campaign_analyses` | 1 : N | `campaign_id` | `CASCADE` |
| 20 | `analyses` | `campaign_analyses` | 1 : N | `analysis_id` | `CASCADE` |

**Regra de ouro da retenção (§8):** `feedback` e `curation_items` referenciam `analyses` com
`ON DELETE SET NULL`. Quando a análise é purgada aos 90 dias, o feedback permanece com
`analysis_id = NULL` e as features necessárias ao retreino já estão em
`curation_items.features_snapshot`.

---

## 8. Retenção e ciclo de vida dos dados

| Dado | Retenção | Mecanismo |
|---|---|---|
| `analyses` + `analysis_module_scores` + `analysis_signals` | **90 dias** | Job `pg_cron` diário: `DELETE FROM analyses WHERE created_at < now() - interval '90 days' AND id NOT IN (SELECT analysis_id FROM curation_items WHERE status = 'pending')`, em lotes de 5.000 + `VACUUM`. |
| `feedback` curado | Até ser consumido por um `model_versions` | Marcado por `curation_items.included_in_model_id`. |
| `curation_items.features_snapshot` | Permanente (dado de treino anonimizado) | — |
| `audit_log` | 5 anos (exigência ROPA) | Particionável por ano se o volume exigir. |
| `email_donations` conteúdo | Conforme termo de consentimento | *Object storage* com *lifecycle policy*; revogação de consentimento dispara exclusão. |
| Backups | 7 diários + 4 semanais | §9.8 |

> **Particionamento** de `analyses` por mês (`PARTITION BY RANGE (created_at)`) **não entra no
> MVP**. Só se justifica se o volume real (estimado em ~700 análises/dia no piloto, §12 do
> planejamento) crescer uma ordem de magnitude. Fica documentado como otimização, não como
> requisito.

---

## 9. Requisitos técnicos de desenvolvimento

### 9.1 Versões

| Componente | Versão | Observação |
|---|---|---|
| PostgreSQL | **16.x** | `gen_random_uuid()` nativo, FK para tabela particionada, `MERGE`. |
| Node.js | 20 LTS | Runtime do Next.js e do worker de análise. |
| Prisma | 5.x | ORM + migrações. |
| PgBouncer | 1.22+ | *Pooling* em modo `transaction`. |
| pgAdmin | 4 (8.x) | Administração e diagrama ER. |
| Python | 3.11 | Pipeline de ML (lê o Postgres via `psycopg[binary]` / SQLAlchemy). |
| Docker Engine | 24+ | Ambiente local. |

### 9.2 Extensões do PostgreSQL

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- gen_random_uuid(), digest() p/ SHA-256
CREATE EXTENSION IF NOT EXISTS citext;        -- domínios e e-mails case-insensitive
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- similaridade de domínio (cousin domain)
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch; -- levenshtein() p/ typosquat
CREATE EXTENSION IF NOT EXISTS pg_cron;       -- job de retenção e refresh de métricas
```

### 9.3 ORM e migrações (Prisma)

- Schema único em `prisma/schema.prisma`; enums do Postgres mapeados para `enum` Prisma.
- `prisma migrate dev` no desenvolvimento, `prisma migrate deploy` no CI/entrega.
- **Duas URLs de conexão:**
  - `DATABASE_URL` → PgBouncer (porta 6432), usada pela aplicação.
  - `DIRECT_URL` → Postgres direto (porta 5432), usada por `prisma migrate` e `prisma db seed`
    (migração não funciona através de *pooler* em modo transaction).
- `prisma generate` no *postinstall*.

### 9.4 Pooling de conexão

Aplicação **nunca** conecta direto no Postgres. PgBouncer em `pool_mode = transaction`,
`default_pool_size = 20`, `max_client_conn = 200`. Motivo: o *add-on* e a API podem gerar
picos de conexões curtas; sem *pooler* o Postgres esgota `max_connections`.

### 9.5 Ambiente local — `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: phishguard
      POSTGRES_USER: phishguard
      POSTGRES_PASSWORD: dev_only_change_me
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]

  pgbouncer:
    image: edoburu/pgbouncer:latest
    environment:
      DATABASE_URL: postgres://phishguard:dev_only_change_me@db:5432/phishguard
      POOL_MODE: transaction
    ports: ["6432:6432"]
    depends_on: [db]

  pgadmin:
    image: dpage/pgadmin4:latest
    environment:
      PGADMIN_DEFAULT_EMAIL: dev@phishguard.local
      PGADMIN_DEFAULT_PASSWORD: dev_only_change_me
    ports: ["5050:80"]
    depends_on: [db]

volumes:
  pgdata:
```

> Subida do zero: `docker compose up -d` → `npx prisma migrate deploy` → `npx prisma db seed`
> → pgAdmin em `http://localhost:5050`.

### 9.6 Integração Firebase Auth ↔ `users`

1. Cliente (add-on / painel) envia `Authorization: Bearer <Firebase ID token>`.
2. *Middleware* (Next.js) valida o token com o **Firebase Admin SDK** (`verifyIdToken`).
3. *Upsert* em `users` por `firebase_uid` (provisionamento *just-in-time*); na primeira vez
   cria também a `organizations` (tipo `pessoa_fisica`) e o `org_settings` padrão.
4. O `id` interno (uuid) — nunca o `firebase_uid` — é usado como FK no resto do banco.
5. Exclusão de conta: `data_subject_requests` tipo `exclusao` → apaga `users`
   (cascata em `consents`, `dsr`) + revoga no Firebase + anonimiza `feedback`/`audit_log`
   (já usam `SET NULL` / sem FK).

### 9.7 Autorização e isolamento multi-tenant

- **Padrão:** filtro por `org_id` na camada de repositório (todo `where` carrega `org_id` do
  contexto autenticado). Simples, testável, suficiente para o TCC.
- **Opcional (defesa):** Row-Level Security. `ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;`
  + policy `USING (org_id = current_setting('app.current_org')::uuid)`, com a aplicação
  fazendo `SET LOCAL app.current_org` no início da transação. Demonstra defesa em profundidade.

### 9.8 Backups

- `pg_dump --format=custom` diário via `pg_cron` / cron do host → retenção 7 diários + 4 semanais.
- WAL archiving (`archive_mode = on`) para *point-in-time recovery* — descrever RPO alvo de
  **15 min** e RTO de **1 h** no capítulo de infraestrutura.
- Teste de restauração documentado ao menos uma vez antes da defesa.

### 9.9 Seeds

| Seed | Origem | Conteúdo |
|---|---|---|
| `signal_catalog` | `prisma/seed/signals.ts` | Todos os `signal_code` de `planejamento_tg.md` §6.1–§6.4 com módulo e peso padrão. |
| `brands` + `brand_domains` | `data/brands_br.json` | Bancos, órgãos públicos, logística, varejo, provedores de e-mail. |
| `model_versions` | `prisma/seed/model.ts` | Linha inicial `version = '0.1.0'`, `status = 'training'`. |

### 9.10 Variáveis de ambiente

```bash
# Banco
DATABASE_URL="postgresql://phishguard:***@localhost:6432/phishguard?schema=public&pgbouncer=true"
DIRECT_URL="postgresql://phishguard:***@localhost:5432/phishguard?schema=public"

# Firebase Auth (Admin SDK — validação de token)
FIREBASE_PROJECT_ID="..."
FIREBASE_CLIENT_EMAIL="..."
FIREBASE_PRIVATE_KEY="..."

# LLM e APIs externas (ver planejamento_tg.md §10 Fase 1)
ANTHROPIC_API_KEY="..."
VIRUSTOTAL_API_KEY="..."
GOOGLE_SAFE_BROWSING_KEY="..."
```

### 9.11 CI (GitHub Actions)

```
jobs:
  db-check:
    - services: postgres:16
    - npx prisma migrate deploy        # aplica todas as migrações do zero
    - npx prisma migrate diff --exit-code   # falha se o schema divergir das migrações
    - npm run test:db                  # testes de integração do repositório
```

### 9.9-alt Alternativa gerenciada

Se a hospedagem auto-gerenciada via pgAdmin não se sustentar até a entrega: **Supabase** ou
**Neon** expõem uma `DATABASE_URL` compatível e já trazem *pooler*. Nesse caso, PgBouncer e o
serviço `db` do compose saem; o resto do documento (schema, migrações, seeds) não muda.

---

## 10. Checklist de implementação (alinhado ao `planejamento_tg.md` §10)

| Fase | Entrega de banco de dados | Verificação |
|---|---|---|
| **Fase 1 — Fundação** | `docker-compose.yml`, `schema.prisma` com o núcleo (§5), 1ª migração, `pg_cron` instalado | `prisma migrate deploy` sobe limpo; pgAdmin conecta |
| **Fase 2 — Corpus** | Seeds de `signal_catalog` e `brands`; tabela `email_donations` + bucket | `SELECT count(*) FROM brand_domains > 0` |
| **Fase 3 — Baselines** | Pipeline Python lê `analyses`/`analysis_signals` para *feature store* | *Notebook* `03` consulta o banco sem credencial de escrita |
| **Fase 4 — PhishRisk Engine** | `analysis_module_scores` gravado com pesos renormalizados; `model_versions` populado | Score reconstruído a partir do banco = score da API |
| **Fase 5 — API** | `feedback`, `api_keys`, `audit_log` ativos; RLS opcional | Testes de integração cobrindo isolamento por `org_id` |
| **Fase 6 — Add-on e Painel** | `curation_items`, `org_settings`, `detected_campaigns`; consultas de `/stats` | Painel RiskOps lê métricas agregadas em < 300 ms |
| **Fase 7 — Retreino e Defesa** | Job de retenção 90 dias validado; `curation_items.included_in_model_id` fechando o loop | Restauração de backup testada; purga não apaga item pendente |

---

*PhishGuard BR — Arquitetura Técnica e Modelo de Dados | Fatec Indaiatuba — ADS 2026*
*Complementa `planejamento_tg.md` v2.0 — Leonardo & Pedro Trindade | Prof. Michel Moron Munhoz*
