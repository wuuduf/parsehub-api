from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ResolveRequest(BaseModel):
    input: str = Field(min_length=1)
    delivery: Literal["direct", "proxy", "auto"] = "direct"
    include_content: bool = True


class PlatformInfo(BaseModel):
    id: str
    name: str


class PostInfo(BaseModel):
    type: str
    title: str
    content: str
    canonical_url: str


class MediaInfo(BaseModel):
    id: str
    kind: Literal["image", "video", "animation", "live_photo", "unknown"]
    url: str
    thumbnail_url: str | None = None
    extension: str | None = None
    width: int = 0
    height: int = 0
    duration: int = 0
    paired_video_url: str | None = None
    expires_at: int | None = None
    qualities: list[dict[str, Any]] = Field(default_factory=list)


class JobCreateRequest(BaseModel):
    input: str = Field(min_length=1)


class APIKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    daily_quota: int | None = Field(default=None, ge=1)


class APIKeyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None
    daily_quota: int | None = Field(default=None, ge=1)
    clear_daily_quota: bool = False


class CredentialUpdateRequest(BaseModel):
    cookie: str | None = Field(default=None, max_length=100_000)
    proxy: str | None = Field(default=None, max_length=2048)


class CacheInfo(BaseModel):
    hit: bool
    ttl: int


class ResolveData(BaseModel):
    platform: PlatformInfo
    post: PostInfo
    media: list[MediaInfo]
    cache: CacheInfo


class SuccessResponse(BaseModel):
    ok: Literal[True] = True
    request_id: str
    data: Any


class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: Any = None


class ErrorResponse(BaseModel):
    ok: Literal[False] = False
    request_id: str
    error: ErrorInfo
