from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response

from .dependencies import authorize
from .errors import APIError
from .media import MediaTarget
from .schemas import JobCreateRequest, ResolveRequest

router = APIRouter()


def _success(request: Request, data: object) -> dict:
    return {"ok": True, "request_id": request.state.request_id, "data": data}


@router.get("/health/live", tags=["health"])
async def liveness(request: Request) -> dict:
    return _success(request, {"status": "ok"})


@router.get("/health/ready", tags=["health"])
async def readiness(request: Request) -> dict:
    platforms = request.app.state.parsehub.get_platforms()
    circuits = await request.app.state.circuit.snapshot()
    return _success(
        request,
        {
            "status": "ready",
            "platform_count": len(platforms),
            "token_secret_configured": request.app.state.settings.token_secret != "development-only-change-me",
            "circuits": circuits,
        },
    )


@router.get("/api/v1/platforms", tags=["parse"], dependencies=[Depends(authorize)])
async def platforms(request: Request) -> dict:
    return _success(request, request.app.state.parsehub.get_platforms())


@router.post("/api/v1/resolve", tags=["parse"], dependencies=[Depends(authorize)])
async def resolve(payload: ResolveRequest, request: Request) -> dict:
    if len(payload.input) > request.app.state.settings.max_input_length:
        raise APIError(422, "INVALID_INPUT", "输入内容过长")
    data, cache_hit = await request.app.state.resolver.resolve(
        payload.input,
        include_content=payload.include_content,
    )
    if payload.delivery in {"proxy", "auto"}:
        data = await _proxy_media(request, data)
    else:
        data = _public_media(data)
    data = {**data, **_shortcut_payload(data)}
    data = {**data, "cache": {"hit": cache_hit, "ttl": request.app.state.settings.cache_ttl}}
    return _success(request, data)


@router.post("/api/v1/shortcut/resolve", tags=["parse"], dependencies=[Depends(authorize)])
async def shortcut_resolve(payload: ResolveRequest, request: Request) -> dict:
    """Return a deliberately simple shape that Apple Shortcuts handles reliably."""
    if len(payload.input) > request.app.state.settings.max_input_length:
        raise APIError(422, "INVALID_INPUT", "输入内容过长")
    data, _ = await request.app.state.resolver.resolve(payload.input, include_content=True)
    data = await _proxy_media(request, data)
    return _success(request, _shortcut_payload(data))


@router.api_route("/api/v1/media/{token}", methods=["GET", "HEAD"], tags=["media"])
async def media(token: str, request: Request) -> Response:
    target = await request.app.state.media_tokens.resolve(token)
    await request.app.state.metrics.increment("media_total", method=request.method, result="requested")
    return cast(Response, await request.app.state.media_gateway.proxy(request, target))


@router.post("/api/v1/jobs", tags=["jobs"], dependencies=[Depends(authorize)], status_code=202)
async def create_job(payload: JobCreateRequest, request: Request) -> dict:
    if len(payload.input) > request.app.state.settings.max_input_length:
        raise APIError(422, "INVALID_INPUT", "输入内容过长")
    data, _ = await request.app.state.resolver.resolve(payload.input, include_content=False)
    targets = [
        MediaTarget(
            url=item["url"],
            filename=f'{item["id"]}.{item.get("extension") or "bin"}',
            headers=item.get("_headers", {}),
        )
        for item in data["media"]
    ]
    job = await request.app.state.jobs.create(request.state.identity, targets)
    return _success(request, job.public())


@router.get("/api/v1/jobs/{job_id}", tags=["jobs"], dependencies=[Depends(authorize)])
async def get_job(job_id: str, request: Request) -> dict:
    job = await request.app.state.jobs.get(job_id, request.state.identity)
    return _success(request, job.public())


@router.delete("/api/v1/jobs/{job_id}", tags=["jobs"], dependencies=[Depends(authorize)])
async def cancel_job(job_id: str, request: Request) -> dict:
    job = await request.app.state.jobs.cancel(job_id, request.state.identity)
    return _success(request, job.public())


@router.get("/api/v1/jobs/{job_id}/download", tags=["jobs"], dependencies=[Depends(authorize)])
async def download_job(job_id: str, request: Request) -> Response:
    job = await request.app.state.jobs.get(job_id, request.state.identity)
    if job.status != "succeeded":
        raise APIError(409, "JOB_NOT_READY", "任务尚未完成")
    if url := await request.app.state.jobs.download_url(job):
        return RedirectResponse(url, status_code=307)
    if job.output_path is None:
        raise APIError(410, "JOB_ARTIFACT_EXPIRED", "任务产物已失效")
    return FileResponse(job.output_path, media_type="application/zip", filename=f"{job.id}.zip")


@router.get("/metrics", tags=["operations"], dependencies=[Depends(authorize)])
async def metrics(request: Request) -> PlainTextResponse:
    return PlainTextResponse(await request.app.state.metrics.render(), media_type="text/plain; version=0.0.4")


async def _proxy_media(request: Request, data: dict) -> dict:
    media_items = []
    for item in data["media"]:
        filename = f'{item["id"]}.{item["extension"] or "bin"}'
        token, expires = await request.app.state.media_tokens.issue(
            MediaTarget(url=item["url"], filename=filename, headers=item.get("_headers", {}))
        )
        item = {
            **item,
            "url": str(request.url_for("media", token=token)),
            "expires_at": expires,
        }
        proxied_qualities = []
        for quality in item.get("qualities", []):
            quality_token, quality_expires = await request.app.state.media_tokens.issue(
                MediaTarget(
                    url=quality["url"],
                    filename=f'{item["id"]}_{quality["id"]}.{quality.get("extension") or "mp4"}',
                    headers=quality.get("_headers", item.get("_headers", {})),
                )
            )
            proxied_qualities.append(
                {
                    **{key: value for key, value in quality.items() if not key.startswith("_")},
                    "url": str(request.url_for("media", token=quality_token)),
                    "expires_at": quality_expires,
                }
            )
        item["qualities"] = proxied_qualities
        if item.get("paired_video_url"):
            paired_token, _ = await request.app.state.media_tokens.issue(
                MediaTarget(
                    url=item["paired_video_url"],
                    filename=f'{item["id"]}_live.mp4',
                    headers=item.get("_headers", {}),
                )
            )
            item["paired_video_url"] = str(request.url_for("media", token=paired_token))
        media_items.append(item)
    return _public_media({**data, "media": media_items})


def _public_media(data: dict) -> dict:
    return {
        **data,
        "media": [
            {
                **{key: value for key, value in item.items() if not key.startswith("_")},
                "qualities": [
                    {key: value for key, value in quality.items() if not key.startswith("_")}
                    for quality in item.get("qualities", [])
                ],
            }
            for item in data["media"]
        ],
    }


def _shortcut_payload(data: dict) -> dict:
    images: list[str] = []
    videos: list[str] = []
    for item in data["media"]:
        if item["kind"] in {"image", "animation", "live_photo"}:
            images.append(item["url"])
        if item["kind"] == "video":
            videos.append(item["url"])
        if item["kind"] == "live_photo" and item.get("paired_video_url"):
            videos.append(item["paired_video_url"])
    return {
        "caption": data["post"]["content"] or data["post"]["title"],
        "images": images,
        "videos": videos,
        "image_count": len(images),
        "video_count": len(videos),
    }
