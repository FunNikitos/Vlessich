"""MTProto issuance (TZ §9A)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.schemas import MtprotoIn, MtprotoOut
from app.security import verify_internal_signature

router = APIRouter(
    prefix="/internal/mtproto",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature)],
)


@router.post("/issue", response_model=MtprotoOut)
async def issue(payload: MtprotoIn) -> MtprotoOut:
    # TODO: generate/lookup per-user Fake-TLS secret via mtg admin API.
    host = "mtp.example.com"
    port = 443
    secret = "ee" + "00" * 16 + "676f6f676c652e636f6d"
    deeplink = f"tg://proxy?server={host}&port={port}&secret={secret}"
    return MtprotoOut(tg_deeplink=deeplink, host=host, port=port)
