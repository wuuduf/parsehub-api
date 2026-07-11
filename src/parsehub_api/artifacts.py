from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


class S3ArtifactStore:
    def __init__(self, *, bucket: str, endpoint: str | None, region: str) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("S3 configured but object-storage extra is not installed") from exc
        self.bucket = bucket
        self.client: Any = boto3.client("s3", endpoint_url=endpoint, region_name=region)

    async def upload(self, job_id: str, path: Path) -> str:
        key = f"parsehub-jobs/{job_id}.zip"
        await asyncio.to_thread(
            self.client.upload_file,
            str(path),
            self.bucket,
            key,
            ExtraArgs={"ContentType": "application/zip"},
        )
        return key

    async def download_url(self, key: str, expires: int = 600) -> str:
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires,
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)
