import contextlib
import io
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from parsehub.errors import ParseError, UnknownPlatform
from parsehub.types import ImageRef, MultimediaParseResult, Platform, VideoRef
from parsehub_api.main import create_app
from parsehub_api.media import MediaTarget
from parsehub_api.settings import Settings


class FakeParseHub:
    def __init__(self):
        self.parse_calls = 0
        self.media_url = "https://cdn.example/image.jpg"
        self.last_parse_kwargs = {}

    def get_platforms(self):
        return [
            {"id": "xhs", "name": "小红书", "supported_types": ["图文", "视频"]},
            {"id": "twitter", "name": "Twitter", "supported_types": ["图文", "视频"]},
            {"id": "weibo", "name": "微博", "supported_types": ["图文", "视频"]},
        ]

    def get_platform(self, text):
        return None if "unsupported" in text else Platform.XHS

    async def parse(self, text, **kwargs):
        self.parse_calls += 1
        self.last_parse_kwargs = kwargs
        if "unsupported" in text:
            raise UnknownPlatform(text)
        if "broken" in text:
            raise ParseError("账号风控\n使用的Cookie: secret-cookie")
        result = MultimediaParseResult(
            title="示例标题",
            content="示例正文",
            media=[
                ImageRef(url=self.media_url, width=1080, height=1440),
                VideoRef(url=self.media_url, duration=8),
            ],
        )
        result.platform = Platform.XHS
        result.raw_url = "https://www.xiaohongshu.com/explore/example"
        if "qualities" in text:
            result.dl = SimpleNamespace(
                info_json={
                    "formats": [
                        {
                            "format_id": "360",
                            "url": "https://cdn.example/video-360.mp4",
                            "vcodec": "h264",
                            "acodec": "aac",
                            "height": 360,
                            "width": 640,
                            "tbr": 500,
                            "ext": "mp4",
                        },
                        {
                            "format_id": "720-low",
                            "url": "https://cdn.example/video-720-low.mp4",
                            "vcodec": "h264",
                            "acodec": "aac",
                            "height": 720,
                            "width": 1280,
                            "tbr": 1200,
                            "ext": "mp4",
                        },
                        {
                            "format_id": "720-best",
                            "url": "https://cdn.example/video-720.mp4",
                            "vcodec": "h264",
                            "acodec": "aac",
                            "height": 720,
                            "width": 1280,
                            "tbr": 1800,
                            "ext": "mp4",
                        },
                        {
                            "format_id": "1080-video-only",
                            "url": "https://cdn.example/video-only.mp4",
                            "vcodec": "h264",
                            "acodec": "none",
                            "height": 1080,
                        },
                    ]
                }
            )
        return result


def make_client(*, media_url="https://cdn.example/image.jpg", **overrides):
    values = {
        "api_keys": ("test-key",),
        "parse_timeout": 2,
        "cache_ttl": 60,
        "max_input_length": 100,
        "max_concurrent_parse": 2,
        "rate_limit_requests": 10,
        "rate_limit_window": 60,
        "admin_token": "admin-test-token",
        "admin_db_path": str(Path(tempfile.mkdtemp()) / "admin.db"),
    }
    values.update(overrides)
    parser = FakeParseHub()
    parser.media_url = media_url
    app = create_app(settings=Settings(**values), parser=parser)
    return TestClient(app, raise_server_exceptions=False), parser


class APITest(unittest.TestCase):
    def test_public_resolver_page_is_available(self):
        client, _ = make_client()
        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("万能链接解析", response.text)
        self.assertIn("下载所选", response.text)

    def test_video_qualities_are_real_playable_formats_and_deduplicated(self):
        client, _ = make_client()
        response = client.post(
            "/api/v1/resolve",
            headers={"Authorization": "Bearer test-key"},
            json={"input": "https://xhs.example/qualities", "delivery": "direct"},
        )

        self.assertEqual(response.status_code, 200)
        video = response.json()["data"]["media"][1]
        self.assertEqual([item["label"] for item in video["qualities"]], ["720p", "360p"])
        self.assertEqual(video["qualities"][0]["id"], "720-best")
        self.assertEqual(video["url"], "https://cdn.example/video-720.mp4")

    def test_admin_panel_is_available(self):
        client, _ = make_client()
        response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("ParseHub 管理台", response.text)

    def test_admin_can_create_use_disable_and_delete_api_key(self):
        client, _ = make_client()
        admin = {"X-Admin-Token": "admin-test-token"}
        created = client.post(
            "/api/admin/keys", headers=admin, json={"name": "iPhone", "daily_quota": 10}
        )

        self.assertEqual(created.status_code, 201)
        raw_key = created.json()["data"]["api_key"]
        key_id = created.json()["data"]["id"]
        self.assertTrue(raw_key.startswith("ph_"))
        listed = client.get("/api/admin/keys", headers=admin).json()["data"]
        self.assertNotIn(raw_key, str(listed))
        self.assertEqual(
            client.get("/api/v1/platforms", headers={"Authorization": f"Bearer {raw_key}"}).status_code,
            200,
        )

        client.patch(f"/api/admin/keys/{key_id}", headers=admin, json={"enabled": False})
        self.assertEqual(
            client.get("/api/v1/platforms", headers={"Authorization": f"Bearer {raw_key}"}).status_code,
            401,
        )
        self.assertEqual(client.delete(f"/api/admin/keys/{key_id}", headers=admin).status_code, 200)

    def test_platform_cookie_is_encrypted_not_returned_and_injected(self):
        client, parser = make_client()
        admin = {"X-Admin-Token": "admin-test-token"}
        saved = client.put(
            "/api/admin/credentials/xhs",
            headers=admin,
            json={"cookie": "session=top-secret", "proxy": "http://proxy.example:7890"},
        )
        self.assertEqual(saved.status_code, 200)
        credentials = client.get("/api/admin/credentials", headers=admin).json()["data"]
        self.assertNotIn("top-secret", str(credentials))
        xhs = next(item for item in credentials if item["platform"] == "xhs")
        self.assertTrue(xhs["cookie_policy"]["supported"])
        self.assertIn("web_session", xhs["cookie_policy"]["recommended"])

        response = client.post(
            "/api/v1/resolve",
            headers={"Authorization": "Bearer test-key"},
            json={"input": "https://xhs.example/admin-cookie-test"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(parser.last_parse_kwargs["cookie"], "session=top-secret")
        self.assertEqual(parser.last_parse_kwargs["proxy"], "http://proxy.example:7890")

    def test_platform_specific_cookie_validation(self):
        client, _ = make_client()
        admin = {"X-Admin-Token": "admin-test-token"}

        missing = client.put(
            "/api/admin/credentials/twitter",
            headers=admin,
            json={"cookie": "auth_token=only-one-field"},
        )
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["error"]["code"], "COOKIE_FIELDS_MISSING")
        self.assertEqual(missing.json()["error"]["details"]["missing"], ["ct0"])

        valid = client.put(
            "/api/admin/credentials/twitter",
            headers=admin,
            json={"cookie": "auth_token=value; ct0=csrf"},
        )
        self.assertEqual(valid.status_code, 200)
        self.assertTrue(valid.json()["data"]["warnings"])

        unsupported = client.put(
            "/api/admin/credentials/weibo",
            headers=admin,
            json={"cookie": "SUB=value"},
        )
        self.assertEqual(unsupported.status_code, 422)
        self.assertEqual(unsupported.json()["error"]["code"], "COOKIE_NOT_SUPPORTED")

    def test_admin_api_rejects_invalid_token(self):
        client, _ = make_client()
        response = client.get("/api/admin/keys", headers={"X-Admin-Token": "wrong"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "ADMIN_UNAUTHORIZED")

    def test_health_is_public_and_has_request_id(self):
        client, _ = make_client()
        response = client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.headers["X-Request-ID"], response.json()["request_id"])

    def test_platforms_requires_bearer_key(self):
        client, _ = make_client()
        response = client.get("/api/v1/platforms")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHORIZED")

    def test_resolve_returns_stable_media_array_and_uses_cache(self):
        client, parser = make_client()
        headers = {"Authorization": "Bearer test-key"}
        first = client.post("/api/v1/resolve", headers=headers, json={"input": "https://xhs.example/post/1"})
        second = client.post("/api/v1/resolve", headers=headers, json={"input": "https://xhs.example/post/1"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["data"]["platform"]["id"], "xhs")
        self.assertEqual([item["kind"] for item in first.json()["data"]["media"]], ["image", "video"])
        self.assertFalse(first.json()["data"]["cache"]["hit"])
        self.assertTrue(second.json()["data"]["cache"]["hit"])
        self.assertEqual(parser.parse_calls, 1)

    def test_parse_error_is_normalized_and_cookie_is_removed(self):
        client, _ = make_client()
        response = client.post(
            "/api/v1/resolve",
            headers={"Authorization": "Bearer test-key"},
            json={"input": "https://broken.example/post/1"},
        )

        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(body["error"]["code"], "UPSTREAM_PARSE_FAILED")
        self.assertNotIn("secret-cookie", str(body))

    def test_unsupported_platform_has_stable_error(self):
        client, _ = make_client()
        response = client.post(
            "/api/v1/resolve",
            headers={"Authorization": "Bearer test-key"},
            json={"input": "https://unsupported.example/post/1"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "PLATFORM_UNSUPPORTED")

    def test_rate_limit_is_enforced_per_key(self):
        client, _ = make_client(rate_limit_requests=1)
        headers = {"Authorization": "Bearer test-key"}

        self.assertEqual(client.get("/api/v1/platforms", headers=headers).status_code, 200)
        response = client.get("/api/v1/platforms", headers=headers)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "RATE_LIMITED")

    def test_delivery_proxy_returns_signed_media_urls(self):
        client, _ = make_client()
        response = client.post(
            "/api/v1/resolve",
            headers={"Authorization": "Bearer test-key"},
            json={"input": "https://xhs.example/post/1", "delivery": "proxy"},
        )

        self.assertEqual(response.status_code, 200)
        media = response.json()["data"]["media"]
        self.assertIn("/api/v1/media/", media[0]["url"])
        self.assertIsInstance(media[0]["expires_at"], int)

    def test_media_gateway_supports_head_and_range(self):
        with media_server(b"0123456789") as url:
            client, _ = make_client(allow_private_media=True)
            import asyncio

            signed, _ = asyncio.run(
                client.app.state.media_tokens.issue(MediaTarget(url=url, filename="demo.bin", headers={}))
            )
            head = client.head(f"/api/v1/media/{signed}")
            partial = client.get(f"/api/v1/media/{signed}", headers={"Range": "bytes=2-5"})

        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.headers["content-length"], "10")
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, b"2345")

    def test_download_job_builds_zip_and_enforces_owner(self):
        with media_server(b"job-content") as url:
            client, _ = make_client(media_url=url, allow_private_media=True, rate_limit_requests=200)
            with client:
                headers = {"Authorization": "Bearer test-key"}
                response = client.post("/api/v1/jobs", headers=headers, json={"input": "https://xhs.example/post/1"})
                self.assertEqual(response.status_code, 202)
                job_id = response.json()["data"]["id"]
                for _ in range(100):
                    status = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()["data"]
                    if status["status"] in {"succeeded", "failed"}:
                        break
                    time.sleep(0.02)
                self.assertEqual(status["status"], "succeeded", status)
                archive = client.get(f"/api/v1/jobs/{job_id}/download", headers=headers)

        self.assertEqual(archive.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
            self.assertGreaterEqual(len(zipped.namelist()), 1)


class MediaHandler(BaseHTTPRequestHandler):
    body = b""

    def log_message(self, format, *args):
        return

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        range_header = self.headers.get("Range")
        body = self.body
        if range_header:
            start, end = (int(value) for value in range_header.removeprefix("bytes=").split("-"))
            body = body[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(self.body)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def media_server(body):
    class Handler(MediaHandler):
        pass

    Handler.body = body
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/media.bin"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
