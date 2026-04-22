# Stage 9 — Per-User MTProto Secrets

Status: in_progress (branched off Stage 8 HEAD `6280fac`).

## Goal

Flip the `scope='user'` branch in `/internal/mtproto/issue` from 501 to
a real allocation: each user gets a dedicated MTProto secret bound to
a dedicated mtg instance listening on a distinct port. Resilient
enough for dev (N replicas via docker compose profile) and prod
(Ansible systemd template unit spawning N containers on a single
host, 8443+i).

## Locked decisions

- **Orchestration**: **N containers** on ports `8443..8443+MAX-1`.
  Not `[replicas]` (mtg pro), not custom fork. Each container gets
  its own `config.toml` generated from a template; systemd templated
  unit (`mtg@.service`) manages them in prod. In dev we expose a
  `per-user-mtg` compose **profile** with N services so default
  `docker compose up` stays lean.
- **Port allocation strategy**: first-fit into the free pool, not
  hash-based. Hash-based collides and wastes replicas; first-fit is
  O(log n) via a partial unique index and matches how we already
  allocate devices.
- **Pool sizing**: `API_MTG_PER_USER_POOL_SIZE` (default 16 in dev,
  configurable in prod via env). Ceiling is hard: 65535-8443 but
  practically ≤ 256 per host. Exceeded → `ApiCode.POOL_FULL` →
  503 user-facing message "MTProto перегружен, повтори позже".
- **Feature gate**: `API_MTG_PER_USER_ENABLED: bool = False`. When
  off, scope='user' keeps returning 501 `per_user_disabled` (not
  `not_implemented`; we reuse a dedicated code so bot can tell "not
  implemented at all" from "deliberately disabled on this install"
  apart). When on, the full allocator runs.
- **Secret binding**: `MtprotoSecret(scope='user', user_id=...,
  port=...)`. Add `port: int | null` column; `NOT NULL` only for
  scope='user' via CHECK constraint. Unique `(user_id)` across
  ACTIVE user-scope rows (1 secret per user at a time). Unique
  `(port)` across ACTIVE user-scope rows (1 port per container).
  Both enforced by **partial** unique indexes on `WHERE
  status='ACTIVE' AND scope='user'`.
- **Rotation (per-user)**: `POST /admin/mtproto/users/{user_id}/rotate`
  (superadmin). Flips old ACTIVE user-secret → REVOKED, allocates a
  new (secret_hex, port) pair. Port MAY be reused (allocator picks
  free slot). Audit: `mtproto_user_rotated`.
- **Revoke**: `POST /admin/mtproto/users/{user_id}/revoke` → marks
  ACTIVE user-secret REVOKED, frees port. Audit:
  `mtproto_user_revoked`.
- **List**: `GET /admin/mtproto/users` (readonly+) → paginated list
  `{user_id, secret_id, port, cloak_domain, status, created_at}`.
- **Cloak selection**: round-robin over `API_MTG_CLOAK_DOMAINS` when
  allocating. Existing setting, just start using it for scope='user'.
- **Audit hygiene**: `secret_hex` / `full_secret` NEVER land in
  `AuditLog.payload`. Payload carries `{port, cloak_domain,
  revoked_secret_id?}` only. Enforced by tests (same pattern as
  Stage 8).

## Out of scope (defer to Stage 10+)

- Auto-rebroadcast deeplinks to active users after rotation (bot-side
  mass-DM worker). Stage 9 delivers backend only; operator manually
  nudges via existing bot flow until then.
- Cron auto-rotation on a schedule. Manual admin trigger only.
- Multi-host sharding (all N containers on one host in Stage 9).
- Admin UI page for mtg. Backend endpoints ship; frontend later.

## Migration

`api/alembic/versions/0005_stage9.py`:

- `ALTER TABLE mtproto_secrets ADD COLUMN port INTEGER`.
- `ALTER TABLE mtproto_secrets ADD CONSTRAINT mtproto_port_range CHECK
  (port IS NULL OR (port BETWEEN 1 AND 65535))`.
- `ALTER TABLE mtproto_secrets ADD CONSTRAINT
  mtproto_user_port_consistency CHECK ((scope='shared' AND port IS
  NULL) OR (scope='user' AND port IS NOT NULL))` — only on upgrade,
  but since existing scope='user' rows never existed (Stage 8
  returned 501 for that branch), the column defaults to NULL
  everywhere and the CHECK is safe.
- Two partial unique indexes:
  - `ux_mtproto_user_active ON mtproto_secrets (user_id) WHERE
    status='ACTIVE' AND scope='user'`.
  - `ux_mtproto_user_port_active ON mtproto_secrets (port) WHERE
    status='ACTIVE' AND scope='user'`.

## Config surface

| Setting | Env | Default | Purpose |
|---|---|---|---|
| `mtg_per_user_enabled` | `API_MTG_PER_USER_ENABLED` | `false` | Feature flag for the whole stage. `false` → scope='user' returns 501 `per_user_disabled`. |
| `mtg_per_user_pool_size` | `API_MTG_PER_USER_POOL_SIZE` | `16` | Size of port pool (containers 8443..8443+N-1). |
| `mtg_per_user_port_base` | `API_MTG_PER_USER_PORT_BASE` | `8443` | First port. Shared secret stays on `mtg_port`; per-user starts here. |

## API surface (delta)

```
POST /internal/mtproto/issue      # scope='user' now allocates (or reuses)
POST /admin/mtproto/users/{uid}/rotate
POST /admin/mtproto/users/{uid}/revoke
GET  /admin/mtproto/users?limit=&offset=&status=
```

All admin endpoints require superadmin for mutating ops; list is
`readonly+`.

## Error codes

- `ApiCode.POOL_FULL = "pool_full"` — per-user pool exhausted (503).
- `ApiCode.PER_USER_DISABLED = "per_user_disabled"` — feature flag off
  (501). `NOT_IMPLEMENTED` is repurposed as generic, this is specific.

## Task breakdown

| # | Task | Files |
|---|---|---|
| T1 | Plan | `docs/plan-stage-9.md` |
| T2 | Settings + error codes | `api/app/config.py`, `api/app/errors.py`, `api/.env.example` |
| T3 | Alembic migration | `api/alembic/versions/0005_stage9.py` |
| T4 | Model + allocator service | `api/app/models.py`, new `api/app/services/mtproto_allocator.py` |
| T5 | Wire `/internal/mtproto/issue` scope='user' | `api/app/routers/mtproto.py` |
| T6 | Admin per-user endpoints | `api/app/routers/admin/mtproto.py`, register in `api/app/main.py` |
| T7 | Infra: compose `per-user-mtg` profile + ansible role stub | `docker-compose.dev.yml`, `mtg/config.template.toml` (new), `ansible/roles/mtg/` |
| T8 | Tests | `api/tests/test_mtproto_allocator.py`, `api/tests/test_mtproto_issue.py` (extend), `api/tests/test_admin_mtproto.py` (extend) |
| T9 | Docs | `CHANGELOG.md` `[0.9.0]`, `docs/ARCHITECTURE.md` §20, `README.md`, `api/README.md`, `mtg/README.md` |

## Allocator algorithm (T4)

```python
async def allocate_user_secret(session, settings, user_id) -> MtprotoSecret:
    async with session.begin_nested():  # caller holds the outer tx
        # 1. Existing ACTIVE user-secret? Return it (idempotent issue).
        existing = await session.scalar(
            select(MtprotoSecret)
            .where(
                MtprotoSecret.scope == "user",
                MtprotoSecret.user_id == user_id,
                MtprotoSecret.status == "ACTIVE",
            )
            .with_for_update()
        )
        if existing is not None:
            return existing

        # 2. Find free port: set(range(base, base+size)) - active_ports.
        taken = set(
            (await session.execute(
                select(MtprotoSecret.port)
                .where(
                    MtprotoSecret.scope == "user",
                    MtprotoSecret.status == "ACTIVE",
                    MtprotoSecret.port.is_not(None),
                )
                .with_for_update()
            )).scalars()
        )
        pool = range(settings.mtg_per_user_port_base,
                     settings.mtg_per_user_port_base + settings.mtg_per_user_pool_size)
        free = next((p for p in pool if p not in taken), None)
        if free is None:
            raise ApiError(503, POOL_FULL, "MTProto перегружен, повтори позже.")

        # 3. Insert new ACTIVE user-secret.
        cloak = _pick_cloak(settings.mtg_cloak_domains, user_id)
        fresh = MtprotoSecret(
            secret_hex=secrets.token_hex(16),
            cloak_domain=cloak,
            scope="user",
            user_id=user_id,
            port=free,
            status="ACTIVE",
        )
        session.add(fresh)
        await session.flush()
        return fresh
```

## Verification gates

- AST parse all `api/**/*.py`.
- `python -c "import yaml; yaml.safe_load(open('docker-compose.dev.yml'))"`.
- `alembic upgrade head` **dry-check via AST only** (no DB in sandbox).
- Type-escape audit clean.
- Tests written, not run (same rule as Stage 8).
