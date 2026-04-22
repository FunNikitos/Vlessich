# Stage 9 — Per-User MTProto Secrets (FREE-pool model)

Status: in_progress (branched off Stage 8 HEAD `6280fac`).

## Goal

Flip `scope='user'` in `/internal/mtproto/issue` from 501 to a real
allocation: each user gets a dedicated MTProto secret bound to a
dedicated port. **Secrets are pre-generated and known to mtg in
advance** — API cannot mint new ones at runtime (mtg only accepts
secrets configured statically in `config.toml`).

## Architecture pivot (vs. naive runtime-mint)

The naive design (allocator generates `secrets.token_hex(16)` on
demand) is broken: mtg only forwards traffic for secrets listed in
its config. A runtime-minted secret would never reach mtg.

**Source-of-truth = DB**. Operator bootstraps a pool of FREE
secrets via admin endpoint; API renders an mtg config bundle that
Ansible deploys to N containers (ports `8443..8443+N-1`). Allocator
just *claims* a FREE row for a user — no new secret material ever
appears.

```
                         ┌──── API ────┐
admin POST bootstrap ───▶│             │── INSERT N rows status=FREE
                         │  DB pool    │
                         │ (FREE/ACTIVE)│
                         └──────────────┘
                                │
                                ▼ (operator pulls)
                       GET pool/config
                                │
                                ▼ (Ansible templates per-port mtg config)
                          mtg_8443  mtg_8444 ... mtg_8443+N-1
                                ▲
internal POST issue scope=user ─┤  allocator SELECT FREE FOR UPDATE
                                │  SKIP LOCKED LIMIT 1 → SET status=ACTIVE
                                ▼
                          tg://proxy?server=mtp&port=8444&secret=ee…
```

## Locked decisions

- **Pool seeding**: `POST /admin/mtproto/pool/bootstrap` (superadmin)
  with `{count: int, port_base?: int, cloak_domain?: str}`. API:
  1. Iterates `port_base..port_base+count-1`, skips ports already
     present in DB with status in `('ACTIVE','FREE')`.
  2. INSERTs FREE rows for the rest with fresh
     `secrets.token_hex(16)`.
  3. Returns one-time `{items: [{port, secret_hex, cloak_domain,
     full_secret}], inserted_ports, skipped_ports}` so operator can
     pipe it into Ansible.
- **Allocator**: `SELECT … WHERE status='FREE' AND scope='user'
  ORDER BY port ASC FOR UPDATE SKIP LOCKED LIMIT 1`. Concurrent
  allocators get distinct rows, no port collision possible.
- **Statuses**:
  - `FREE`   — pre-seeded, bound to a port, no `user_id`.
  - `ACTIVE` — claimed by a user (`user_id` set).
  - `REVOKED` — manually revoked by admin; the secret is dead and
    its port stays *occupied* in DB (mtg still serves that secret
    until admin restarts mtg with a new bootstrap).
  - (legacy `ROTATED` kept in CHECK for back-compat with shared
    rotate from Stage 8.)
- **Per-user idempotency on issue**: if user has ACTIVE → return it.
  Else allocate one FREE → set ACTIVE + user_id.
- **Rotate** (`POST /admin/mtproto/users/{user_id}/rotate`,
  superadmin): mark current ACTIVE → REVOKED, allocate fresh FREE
  → ACTIVE. New port is whatever FREE was picked; old port is
  burned (status=REVOKED) and no longer usable until next
  bootstrap.
  - Caveat: rotate consumes a FREE slot. Admin must re-bootstrap to
    refill. Endpoint response includes `pool_free_remaining` so
    operator sees pressure.
- **Revoke** (`POST /admin/mtproto/users/{user_id}/revoke`,
  superadmin): ACTIVE → REVOKED. No re-allocation. Pool free count
  unchanged. Secret stays in mtg config until admin manually
  removes it (recommended on bootstrap refresh).
- **List** (`GET /admin/mtproto/users`, readonly+, paginated, status
  filter). Never returns `secret_hex` / `full_secret`.
- **Pool config dump** (`GET /admin/mtproto/pool/config`,
  superadmin): returns ALL non-REVOKED secrets (FREE + ACTIVE) with
  full material so operator can regenerate mtg `config.toml` for
  every port. Audit-logged. Use case: rebuilding mtg-VPS from
  scratch or after Ansible re-deploy.
- **Pool exhaustion**: allocator finds no FREE → `503 pool_full`.
  Bot surfaces RU message, admin gets the cue to bootstrap.
- **Feature gate**: `API_MTG_PER_USER_ENABLED` (Stage 9 T2).
  When off, scope=user → 501 `per_user_disabled`. Pool endpoints
  remain reachable for admins (so they can prep the pool **before**
  flipping the flag).
- **Cloak per user**: each FREE row carries its own
  `cloak_domain` set at bootstrap. Default = first item of
  `mtg_cloak_domains`. Override via bootstrap payload.
- **Audit**: actions `mtproto_pool_bootstrapped`,
  `mtproto_user_allocated` (NEW — also written from
  `/internal/mtproto/issue` because it's a mutating action),
  `mtproto_user_rotated`, `mtproto_user_revoked`. Payloads carry
  `port`, `cloak_domain`, `count`, `revoked_secret_id` only —
  **never** `secret_hex` / `full_secret`.

## Out of scope (Stage 10+)

- Auto-rebroadcast deeplinks after rotation (bot mass-DM worker).
- Cron auto-rotation.
- Admin UI page for mtg.
- Multi-host pool sharding (all N containers on one host).
- Auto-Ansible-trigger from API (operator runs `make` after pool
  changes).

## Migration `0005_stage9.py`

- `ALTER TABLE mtproto_secrets ADD COLUMN port INTEGER`.
- `ALTER TABLE mtproto_secrets DROP CONSTRAINT mtproto_status_chk`,
  re-create with `status IN ('ACTIVE','ROTATED','REVOKED','FREE')`.
- New CHECK `mtproto_port_range`: `port IS NULL OR port BETWEEN 1
  AND 65535`.
- New CHECK `mtproto_user_port_consistency`: `(scope='shared' AND
  port IS NULL) OR (scope='user' AND port IS NOT NULL)`.
- New CHECK `mtproto_user_status_consistency`: `scope='shared' OR
  status IN ('ACTIVE','REVOKED','FREE')` — keeps `ROTATED` away
  from per-user rows.
- New CHECK `mtproto_free_no_user`: `status<>'FREE' OR user_id IS
  NULL`.
- Drop existing CHECK `mtproto_scope_user_consistency` and re-create
  to allow FREE rows: `(scope='shared' AND user_id IS NULL) OR
  (scope='user' AND ((status='FREE' AND user_id IS NULL) OR
  (status<>'FREE' AND user_id IS NOT NULL)))`.
- Partial unique `ux_mtproto_user_active(user_id) WHERE
  status='ACTIVE' AND scope='user'`.
- Partial unique `ux_mtproto_port_live(port) WHERE status IN
  ('ACTIVE','FREE') AND scope='user'` (one live secret per port —
  REVOKED rows are tombstones, can coexist).

## Config surface (Stage 9 T2 already shipped)

| Setting | Env | Default | Purpose |
|---|---|---|---|
| `mtg_per_user_enabled` | `API_MTG_PER_USER_ENABLED` | `false` | Feature flag. |
| `mtg_per_user_pool_size` | `API_MTG_PER_USER_POOL_SIZE` | `16` | Default `count` for bootstrap; advisory for monitoring. |
| `mtg_per_user_port_base` | `API_MTG_PER_USER_PORT_BASE` | `8443` | Default `port_base` for bootstrap; first per-user port. |

## API surface (delta)

```
POST /internal/mtproto/issue                # scope='user' → allocator
POST /admin/mtproto/pool/bootstrap          # superadmin, idempotent
GET  /admin/mtproto/pool/config             # superadmin, full secrets dump
POST /admin/mtproto/users/{uid}/rotate      # superadmin
POST /admin/mtproto/users/{uid}/revoke      # superadmin
GET  /admin/mtproto/users                   # readonly+
```

## Error codes (Stage 9 T2 already shipped)

- `PER_USER_DISABLED` (501) — feature flag off.
- `POOL_FULL` (503) — allocator found no FREE.

## Task breakdown (revised)

| # | Task | Status |
|---|---|---|
| T1 | Plan v1 | superseded |
| T2 | Settings + error codes | done (`8f4aa55`) |
| T3 | **Plan v2 (FREE-pool)** | this commit |
| T4 | Alembic 0005 (port + FREE status + indexes + CHECKs) | next |
| T5 | Model + allocator (SKIP LOCKED on FREE) + issue wiring | next |
| T6 | Admin endpoints (list/rotate/revoke/bootstrap/pool-config) | next |
| T7 | Infra: compose `per-user-mtg` profile + ansible mtg pool task | next |
| T8 | Tests (allocator, issue, admin endpoints, migration semantics) | next |
| T9 | Docs (CHANGELOG, ARCHITECTURE §20, READMEs) | next |

## Allocator algorithm (final)

```python
async def allocate_user_secret(session, user_id) -> MtprotoSecret:
    # 1. Idempotent: existing ACTIVE for this user.
    existing = await session.scalar(
        select(MtprotoSecret).where(
            scope=='user', user_id==user_id, status=='ACTIVE'
        )
    )
    if existing:
        return existing

    # 2. Claim a FREE slot.
    free = await session.scalar(
        select(MtprotoSecret)
        .where(scope=='user', status=='FREE')
        .order_by(port.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not free:
        raise api_error(503, POOL_FULL, "MTProto перегружен …")

    free.status = 'ACTIVE'
    free.user_id = user_id
    await session.flush()
    return free
```

## Verification gates

- AST parse all `api/**/*.py`.
- `python -c "import yaml; yaml.safe_load(open('docker-compose.dev.yml'))"`.
- Type-escape audit clean.
- Tests written, not run.
