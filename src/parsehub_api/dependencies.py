from __future__ import annotations

import hashlib
import secrets

from fastapi import Request

from .errors import APIError


async def authorize(request: Request) -> str:
    settings = request.app.state.settings
    if not settings.api_keys and not request.app.state.admin_store.list_api_keys():
        raise APIError(503, "AUTH_NOT_CONFIGURED", "服务端尚未配置 API Key")

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise APIError(401, "UNAUTHORIZED", "缺少有效的 Bearer API Key")
    principal = request.app.state.admin_store.authenticate_api_key(token)
    static_key = any(secrets.compare_digest(token, key) for key in settings.api_keys)
    if principal is None and not static_key:
        raise APIError(401, "UNAUTHORIZED", "缺少有效的 Bearer API Key")

    allowed, retry_after = await request.app.state.rate_limiter.allow(token)
    if not allowed:
        raise APIError(
            429,
            "RATE_LIMITED",
            "请求过于频繁，请稍后重试",
            retryable=True,
            details={"retry_after": retry_after},
        )
    identity = principal.identity if principal else hashlib.sha256(token.encode()).hexdigest()[:16]
    quota_limit = principal.daily_quota if principal else None
    quota_allowed, remaining = await request.app.state.daily_quota.consume(identity, quota_limit)
    if not quota_allowed:
        raise APIError(429, "DAILY_QUOTA_EXCEEDED", "今日请求额度已用完", details={"remaining": 0})
    request.state.identity = identity
    request.state.quota_remaining = remaining
    return identity


async def authorize_admin(request: Request) -> None:
    configured = request.app.state.settings.admin_token
    supplied = request.headers.get("X-Admin-Token", "")
    if not configured:
        raise APIError(503, "ADMIN_NOT_CONFIGURED", "服务端尚未配置管理员密钥")
    if not supplied or not secrets.compare_digest(supplied, configured):
        raise APIError(401, "ADMIN_UNAUTHORIZED", "管理员认证失败")
