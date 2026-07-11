from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "ParseHub API"
    api_keys: tuple[str, ...] = field(default_factory=tuple)
    parse_timeout: int = 35
    cache_ttl: int = 300
    max_input_length: int = 8192
    max_concurrent_parse: int = 8
    rate_limit_requests: int = 60
    rate_limit_window: int = 60
    docs_enabled: bool = True
    token_secret: str = "development-only-change-me"
    media_token_ttl: int = 600
    media_timeout: int = 60
    media_max_bytes: int = 1024 * 1024 * 1024
    allow_private_media: bool = False
    job_ttl: int = 3600
    job_max_files: int = 50
    job_max_bytes: int = 2 * 1024 * 1024 * 1024
    job_max_concurrent: int = 2
    daily_quota: int = 1000
    circuit_failures: int = 5
    circuit_cooldown: int = 60
    redis_url: str | None = None
    s3_bucket: str | None = None
    s3_endpoint: str | None = None
    s3_region: str = "us-east-1"
    admin_token: str = ""
    admin_db_path: str = "./data/parsehub-admin.db"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            app_name=os.getenv("PARSEHUB_APP_NAME", "ParseHub API"),
            api_keys=_csv(os.getenv("PARSEHUB_API_KEYS", "")),
            parse_timeout=_positive_int("PARSEHUB_PARSE_TIMEOUT", 35),
            cache_ttl=_positive_int("PARSEHUB_CACHE_TTL", 300),
            max_input_length=_positive_int("PARSEHUB_MAX_INPUT_LENGTH", 8192),
            max_concurrent_parse=_positive_int("PARSEHUB_MAX_CONCURRENT_PARSE", 8),
            rate_limit_requests=_positive_int("PARSEHUB_RATE_LIMIT_REQUESTS", 60),
            rate_limit_window=_positive_int("PARSEHUB_RATE_LIMIT_WINDOW", 60),
            docs_enabled=os.getenv("PARSEHUB_DOCS_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
            token_secret=os.getenv("PARSEHUB_TOKEN_SECRET", "development-only-change-me"),
            media_token_ttl=_positive_int("PARSEHUB_MEDIA_TOKEN_TTL", 600),
            media_timeout=_positive_int("PARSEHUB_MEDIA_TIMEOUT", 60),
            media_max_bytes=_positive_int("PARSEHUB_MEDIA_MAX_BYTES", 1024 * 1024 * 1024),
            allow_private_media=os.getenv("PARSEHUB_ALLOW_PRIVATE_MEDIA", "false").lower()
            in {"1", "true", "yes", "on"},
            job_ttl=_positive_int("PARSEHUB_JOB_TTL", 3600),
            job_max_files=_positive_int("PARSEHUB_JOB_MAX_FILES", 50),
            job_max_bytes=_positive_int("PARSEHUB_JOB_MAX_BYTES", 2 * 1024 * 1024 * 1024),
            job_max_concurrent=_positive_int("PARSEHUB_JOB_MAX_CONCURRENT", 2),
            daily_quota=_positive_int("PARSEHUB_DAILY_QUOTA", 1000),
            circuit_failures=_positive_int("PARSEHUB_CIRCUIT_FAILURES", 5),
            circuit_cooldown=_positive_int("PARSEHUB_CIRCUIT_COOLDOWN", 60),
            redis_url=os.getenv("PARSEHUB_REDIS_URL") or None,
            s3_bucket=os.getenv("PARSEHUB_S3_BUCKET") or None,
            s3_endpoint=os.getenv("PARSEHUB_S3_ENDPOINT") or None,
            s3_region=os.getenv("PARSEHUB_S3_REGION", "us-east-1"),
            admin_token=os.getenv("PARSEHUB_ADMIN_TOKEN", ""),
            admin_db_path=os.getenv("PARSEHUB_ADMIN_DB_PATH", "./data/parsehub-admin.db"),
        )
