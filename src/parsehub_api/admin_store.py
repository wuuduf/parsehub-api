from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .cookie_policies import get_cookie_policy


@dataclass(frozen=True, slots=True)
class APIKeyPrincipal:
    identity: str
    name: str
    daily_quota: int | None


@dataclass(frozen=True, slots=True)
class PlatformCredential:
    platform: str
    cookie: str | None
    proxy: str | None
    version: int = 0


class AdminStore:
    def __init__(self, path: str, secret: str) -> None:
        self.path = path
        self._hmac_secret = secret.encode()
        fernet_key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(fernet_key)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        self._connection.close()

    def create_api_key(self, name: str, daily_quota: int | None = None) -> tuple[dict, str]:
        raw_key = f"ph_{secrets.token_urlsafe(32)}"
        key_id = f"key_{uuid.uuid4().hex}"
        now = int(time.time())
        self._connection.execute(
            """INSERT INTO api_keys(id, name, key_digest, prefix, enabled, daily_quota, created_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (key_id, name.strip(), self._digest(raw_key), raw_key[:10], daily_quota, now),
        )
        self._connection.commit()
        return self.get_api_key(key_id), raw_key

    def list_api_keys(self) -> list[dict]:
        rows = self._connection.execute(
            """SELECT id, name, prefix, enabled, daily_quota, created_at, last_used_at
            FROM api_keys ORDER BY created_at DESC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def get_api_key(self, key_id: str) -> dict:
        row = self._connection.execute(
            "SELECT id, name, prefix, enabled, daily_quota, created_at, last_used_at FROM api_keys WHERE id = ?",
            (key_id,),
        ).fetchone()
        if row is None:
            raise KeyError(key_id)
        return dict(row)

    def update_api_key(
        self,
        key_id: str,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        daily_quota: int | None = None,
        set_quota: bool = False,
    ) -> dict:
        current = self.get_api_key(key_id)
        self._connection.execute(
            "UPDATE api_keys SET name = ?, enabled = ?, daily_quota = ? WHERE id = ?",
            (
                name.strip() if name is not None else current["name"],
                int(enabled) if enabled is not None else current["enabled"],
                daily_quota if set_quota else current["daily_quota"],
                key_id,
            ),
        )
        self._connection.commit()
        return self.get_api_key(key_id)

    def delete_api_key(self, key_id: str) -> bool:
        cursor = self._connection.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        self._connection.commit()
        return cursor.rowcount > 0

    def authenticate_api_key(self, raw_key: str) -> APIKeyPrincipal | None:
        row = self._connection.execute(
            "SELECT id, name, daily_quota FROM api_keys WHERE key_digest = ? AND enabled = 1",
            (self._digest(raw_key),),
        ).fetchone()
        if row is None:
            return None
        self._connection.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (int(time.time()), row["id"]))
        self._connection.commit()
        return APIKeyPrincipal(identity=row["id"], name=row["name"], daily_quota=row["daily_quota"])

    def list_credentials(self, platforms: list[dict]) -> list[dict]:
        rows = {
            row["platform"]: row
            for row in self._connection.execute(
                "SELECT platform, cookie_ciphertext, proxy, updated_at FROM platform_credentials"
            ).fetchall()
        }
        return [
            {
                "platform": item["id"],
                "name": item["name"],
                "cookie_configured": bool(rows.get(item["id"]) and rows[item["id"]]["cookie_ciphertext"]),
                "proxy": rows[item["id"]]["proxy"] if rows.get(item["id"]) else None,
                "updated_at": rows[item["id"]]["updated_at"] if rows.get(item["id"]) else None,
                "cookie_policy": get_cookie_policy(item["id"]).public(),
            }
            for item in platforms
        ]

    def set_credential(self, platform: str, cookie: str | None, proxy: str | None) -> None:
        current = self._connection.execute(
            "SELECT cookie_ciphertext FROM platform_credentials WHERE platform = ?", (platform,)
        ).fetchone()
        encrypted = (
            self._fernet.encrypt(cookie.encode()).decode()
            if cookie
            else (current["cookie_ciphertext"] if current is not None else None)
        )
        self._connection.execute(
            """INSERT INTO platform_credentials(platform, cookie_ciphertext, proxy, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(platform) DO UPDATE SET cookie_ciphertext=excluded.cookie_ciphertext,
            proxy=excluded.proxy, updated_at=excluded.updated_at""",
            (platform, encrypted, proxy.strip() if proxy else None, int(time.time())),
        )
        self._connection.commit()

    def clear_credential(self, platform: str) -> None:
        self._connection.execute("DELETE FROM platform_credentials WHERE platform = ?", (platform,))
        self._connection.commit()

    def get_credential(self, platform: str) -> PlatformCredential:
        row = self._connection.execute(
            "SELECT cookie_ciphertext, proxy, updated_at FROM platform_credentials WHERE platform = ?", (platform,)
        ).fetchone()
        if row is None:
            return PlatformCredential(platform, None, None)
        cookie = None
        if row["cookie_ciphertext"]:
            try:
                cookie = self._fernet.decrypt(row["cookie_ciphertext"].encode()).decode()
            except InvalidToken:
                cookie = None
        return PlatformCredential(platform, cookie, row["proxy"], row["updated_at"])

    def _digest(self, value: str) -> str:
        return hmac.new(self._hmac_secret, value.encode(), hashlib.sha256).hexdigest()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                key_digest TEXT NOT NULL UNIQUE,
                prefix TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                daily_quota INTEGER,
                created_at INTEGER NOT NULL,
                last_used_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS platform_credentials (
                platform TEXT PRIMARY KEY,
                cookie_ciphertext TEXT,
                proxy TEXT,
                updated_at INTEGER NOT NULL
            );
            """
        )
        self._connection.commit()
