from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from parsehub import ParseHub

from .admin import router as admin_router
from .admin_store import AdminStore
from .artifacts import S3ArtifactStore
from .cache import TTLCache
from .circuit import CircuitBreaker
from .distributed import RedisDailyQuota, RedisMediaTokenStore, RedisRateLimiter, RedisTTLCache
from .errors import APIError
from .jobs import JobManager
from .media import MediaGateway, MediaTokenStore
from .metrics import DailyQuota, Metrics
from .rate_limit import InMemoryRateLimiter
from .routers import router
from .services import ResolverService
from .settings import Settings
from .web import router as web_router

logger = logging.getLogger("parsehub_api")


def create_app(*, settings: Settings | None = None, parser: ParseHub | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    redis = Redis.from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None
    admin_store = AdminStore(settings.admin_db_path, settings.token_secret)
    artifact_store = (
        S3ArtifactStore(bucket=settings.s3_bucket, endpoint=settings.s3_endpoint, region=settings.s3_region)
        if settings.s3_bucket
        else None
    )
    jobs = JobManager(
        ttl=settings.job_ttl,
        max_files=settings.job_max_files,
        max_bytes=settings.job_max_bytes,
        max_concurrent=settings.job_max_concurrent,
        allow_private=settings.allow_private_media,
        artifact_store=artifact_store,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if redis is not None:
            await redis.ping()
        yield
        await jobs.close()
        admin_store.close()
        if redis is not None:
            await redis.aclose()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    parsehub = parser or ParseHub()
    cache = RedisTTLCache(redis, settings.cache_ttl) if redis is not None else TTLCache(settings.cache_ttl)
    app.state.settings = settings
    app.state.admin_store = admin_store
    app.state.parsehub = parsehub
    app.state.rate_limiter = (
        RedisRateLimiter(redis, settings.rate_limit_requests, settings.rate_limit_window)
        if redis is not None
        else InMemoryRateLimiter(settings.rate_limit_requests, settings.rate_limit_window)
    )
    app.state.daily_quota = (
        RedisDailyQuota(redis, settings.daily_quota) if redis is not None else DailyQuota(settings.daily_quota)
    )
    app.state.metrics = Metrics()
    app.state.circuit = CircuitBreaker(settings.circuit_failures, settings.circuit_cooldown)
    app.state.media_tokens = (
        RedisMediaTokenStore(redis, settings.token_secret, settings.media_token_ttl)
        if redis is not None
        else MediaTokenStore(settings.token_secret, settings.media_token_ttl)
    )
    app.state.redis = redis
    app.state.media_gateway = MediaGateway(
        timeout=settings.media_timeout,
        max_bytes=settings.media_max_bytes,
        allow_private=settings.allow_private_media,
    )
    app.state.jobs = jobs
    app.state.resolver = ResolverService(
        parsehub,
        cache=cache,
        timeout=settings.parse_timeout,
        max_concurrent=settings.max_concurrent_parse,
        circuit=app.state.circuit,
        metrics=app.state.metrics,
        admin_store=admin_store,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        request.state.request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return _error_response(request, exc.status_code, exc.code, exc.message, exc.retryable, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"location": list(item["loc"]), "message": item["msg"]} for item in exc.errors()]
        return _error_response(request, 422, "INVALID_INPUT", "请求参数格式错误", False, details)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error request_id=%s", request.state.request_id)
        return _error_response(request, 500, "INTERNAL_ERROR", "服务端内部错误", True, None)

    app.include_router(router)
    app.include_router(admin_router)
    app.include_router(web_router)
    return app


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
    details: Any,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "request_id": getattr(request.state, "request_id", "unknown"),
            "error": {"code": code, "message": message, "retryable": retryable, "details": details},
        },
    )


app = create_app()
