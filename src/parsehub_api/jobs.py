from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from .errors import APIError
from .media import MediaTarget, validate_public_url

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "expired"]


class ArtifactStore(Protocol):
    async def upload(self, job_id: str, path: Path) -> str: ...

    async def download_url(self, key: str, expires: int = 600) -> str: ...

    async def delete(self, key: str) -> None: ...


@dataclass(slots=True)
class DownloadJob:
    id: str
    owner: str
    targets: list[MediaTarget]
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_files: int = 0
    total_files: int = 0
    downloaded_bytes: int = 0
    output_path: Path | None = None
    artifact_key: str | None = None
    error: str | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def public(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_files": self.completed_files,
            "total_files": self.total_files,
            "downloaded_bytes": self.downloaded_bytes,
            "download_ready": self.status == "succeeded"
            and (self.output_path is not None or self.artifact_key is not None),
            "error": self.error,
        }


class JobManager:
    def __init__(
        self,
        *,
        ttl: int,
        max_files: int,
        max_bytes: int,
        max_concurrent: int,
        allow_private: bool,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.ttl = ttl
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.allow_private = allow_private
        self.artifact_store = artifact_store
        self.root = Path(tempfile.mkdtemp(prefix="parsehub-jobs-"))
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def create(self, owner: str, targets: list[MediaTarget]) -> DownloadJob:
        if not targets or len(targets) > self.max_files:
            raise APIError(422, "JOB_FILE_LIMIT", f"任务媒体数量必须在 1 到 {self.max_files} 之间")
        await self.cleanup()
        job = DownloadJob(
            id=f"job_{uuid.uuid4().hex}", owner=owner, targets=targets, total_files=len(targets)
        )
        async with self._lock:
            self._jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job))
        return job

    async def get(self, job_id: str, owner: str) -> DownloadJob:
        await self.cleanup()
        async with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.owner != owner:
            raise APIError(404, "JOB_NOT_FOUND", "任务不存在")
        return job

    async def cancel(self, job_id: str, owner: str) -> DownloadJob:
        job = await self.get(job_id, owner)
        if job.task and not job.task.done():
            job.task.cancel()
        if job.status in {"queued", "running"}:
            job.status = "cancelled"
            job.updated_at = time.time()
        await self._remove_output(job)
        return job

    async def cleanup(self) -> None:
        now = time.time()
        async with self._lock:
            expired = [job for job in self._jobs.values() if now - job.updated_at > self.ttl]
            for job in expired:
                if job.task and not job.task.done():
                    job.task.cancel()
                job.status = "expired"
                await self._remove_output(job)
                self._jobs.pop(job.id, None)

    async def close(self) -> None:
        async with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job.task and not job.task.done():
                job.task.cancel()
        await asyncio.gather(*(job.task for job in jobs if job.task), return_exceptions=True)
        for job in jobs:
            await self._remove_output(job)
        shutil.rmtree(self.root, ignore_errors=True)

    async def download_url(self, job: DownloadJob) -> str | None:
        if job.artifact_key and self.artifact_store:
            return await self.artifact_store.download_url(job.artifact_key)
        return None

    async def _run(self, job: DownloadJob) -> None:
        job_dir = self.root / job.id
        files_dir = job_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        try:
            async with self._semaphore:
                job.status = "running"
                for index, target in enumerate(job.targets, 1):
                    await validate_public_url(target.url, allow_private=self.allow_private)
                    filename = target.filename or _filename(target.url, index)
                    await self._download(target.url, files_dir / filename, job, target.headers, target.proxy)
                    job.completed_files = index
                    job.updated_at = time.time()
                output = job_dir / "media.zip"
                await asyncio.to_thread(_zip_directory, files_dir, output)
                if self.artifact_store:
                    job.artifact_key = await self.artifact_store.upload(job.id, output)
                    shutil.rmtree(job_dir, ignore_errors=True)
                else:
                    job.output_path = output
                job.status = "succeeded"
                job.updated_at = time.time()
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.updated_at = time.time()
            await self._remove_output(job)
            raise
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)[:300]
            job.updated_at = time.time()
            await self._remove_output(job)

    async def _download(
        self, url: str, path: Path, job: DownloadJob, headers: dict[str, str], proxy: str | None
    ) -> None:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False, proxy=proxy) as client:
            current_url = url
            for _ in range(6):
                await validate_public_url(current_url, allow_private=self.allow_private)
                request = client.build_request("GET", current_url, headers=headers)
                response = await client.send(request, stream=True)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise APIError(502, "MEDIA_UPSTREAM_FAILED", "媒体重定向缺少目标地址")
                current_url = urljoin(current_url, location)
            else:
                raise APIError(502, "MEDIA_REDIRECT_LIMIT", "媒体重定向次数过多")
            try:
                response.raise_for_status()
                length = _int(response.headers.get("content-length"))
                if length and job.downloaded_bytes + length > self.max_bytes:
                    raise APIError(413, "JOB_SIZE_LIMIT", "任务下载大小超过限制")
                with path.open("wb") as handle:
                    async for chunk in response.aiter_bytes(64 * 1024):
                        job.downloaded_bytes += len(chunk)
                        if job.downloaded_bytes > self.max_bytes:
                            raise APIError(413, "JOB_SIZE_LIMIT", "任务下载大小超过限制")
                        await asyncio.to_thread(handle.write, chunk)
            finally:
                await response.aclose()

    async def _remove_output(self, job: DownloadJob) -> None:
        if job.output_path:
            shutil.rmtree(job.output_path.parent, ignore_errors=True)
            job.output_path = None
        if job.artifact_key and self.artifact_store:
            try:
                await self.artifact_store.delete(job.artifact_key)
            finally:
                job.artifact_key = None


def _filename(url: str, index: int) -> str:
    name = Path(urlsplit(url).path).name
    safe = "".join(character for character in name if character.isalnum() or character in ".-_")
    return f"{index:03d}_{safe or 'media.bin'}"


def _zip_directory(source: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.iterdir()):
            archive.write(path, path.name)


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None
