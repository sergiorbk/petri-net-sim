"""Stateless portable review endpoints. Archives remain under the caller's control."""
import base64
import binascii
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.api.shared.exceptions import BadRequestException
from src.core.dependencies import get_current_user
from src.infrastructure.postgres.models.user import User
from src.services.auth.contributor import contributor_profile
from src.services.training_export import attachment, build_training_bundle
from src.services.training_history import read_bundle, revision_files
from src.services.training_inspection import inspect_bundle, compare_revisions
from src.api.shared.rate_limit import rate_limit
from src.core.security_config import security_settings

router = APIRouter(prefix="/training", tags=["training"], dependencies=[Depends(rate_limit(
    scope="simulate", max_requests=security_settings.RATE_LIMIT_SIMULATE_MAX,
    window_seconds=security_settings.RATE_LIMIT_SIMULATE_WINDOW, by="token"))])


def decode_archive(value):
    if len(value) > 358_000_000:
        raise ValueError("Training ZIP exceeds the size limit")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid archive encoding") from exc


class ArchiveBody(BaseModel):
    archive_base64: str = Field(max_length=358_000_000)
    revision_id: str | None = None


class CompareBody(ArchiveBody):
    left: str
    right: str
    include_layout: bool = False


class ImageBody(ArchiveBody):
    view_id: str = "main"


class RunBody(ArchiveBody):
    horizon: float = Field(default=100, gt=0, le=1_000_000, allow_inf_nan=False)
    sampling_interval: float = Field(default=1, gt=0, allow_inf_nan=False)


class ExportBody(BaseModel):
    net_data: dict[str, Any]
    title: str = ""
    archive_base64: str | None = Field(default=None, max_length=358_000_000)
    context: dict[str, Any] = Field(default_factory=dict)
    conversation: list[dict[str, Any]] | None = None
    review: dict[str, Any] | None = None


async def execute(fn, *args, **kwargs):
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise BadRequestException(str(exc)[:500]) from exc


@router.post("/inspect")
async def inspect(body: ArchiveBody, user: User = Depends(get_current_user)):
    return await execute(lambda: inspect_bundle(read_bundle(decode_archive(body.archive_base64)), body.revision_id))


@router.post("/compare")
async def compare(body: CompareBody, user: User = Depends(get_current_user)):
    return await execute(lambda: compare_revisions(read_bundle(decode_archive(body.archive_base64)), body.left, body.right, body.include_layout))


@router.post("/image")
async def image(body: ImageBody, user: User = Depends(get_current_user)):
    def capture():
        import json
        files = revision_files(read_bundle(decode_archive(body.archive_base64)), body.revision_id)
        views = json.loads(files.get("network-views.json", b'{"views":[]}'))["views"]
        view = next((v for v in views if v["id"] == body.view_id), {"image": "network.png"} if body.view_id == "main" else None)
        if view is None or view["image"] not in files:
            raise ValueError("Unknown stored image view")
        return files[view["image"]]
    return attachment(await execute(capture), "network.png", "image/png")


@router.post("/export")
async def export(body: ExportBody, user: User = Depends(get_current_user)):
    def capture():
        profile = contributor_profile(user)
        review = None if body.review is None else {**body.review, "reviewer": profile["nickname"], "reviewer_kind": "human"}
        return build_training_bundle(body.net_data, body.title or body.net_data.get("name", "Petri network"),
                                     archive=decode_archive(body.archive_base64) if body.archive_base64 else None,
                                     context=body.context, conversation=body.conversation, review=review, contributor=profile,
                                     conversation_origin="client-provided" if body.conversation else "unavailable")
    data, name = await execute(capture)
    return attachment(data, name, "application/zip")


@router.post("/run")
async def run(body: RunBody, user: User = Depends(get_current_user)):
    def capture():
        from src.services.training_simulation import run_evidence
        files = revision_files(read_bundle(decode_archive(body.archive_base64)), body.revision_id)
        return run_evidence(files["model.pnml"], body.horizon, body.sampling_interval, "interactive-run")
    return await execute(capture)
