"""เทสต์ระบบรหัสผ่าน (HTTP Basic Auth)"""

import base64

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def basic_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


class TestNoPasswordConfigured:
    def test_ไม่ตั้งรหัสผ่านเข้าได้ปกติ(self, monkeypatch):
        monkeypatch.delenv("SOCIALSCOOP_PASSWORD", raising=False)
        assert client.get("/api/health").status_code == 200


class TestPasswordConfigured:
    @pytest.fixture(autouse=True)
    def _set_password(self, monkeypatch):
        monkeypatch.setenv("SOCIALSCOOP_PASSWORD", "s3cret-ไทย")

    def test_ไม่ใส่รหัสผ่านโดนบล็อก(self):
        res = client.get("/api/health")
        assert res.status_code == 401
        assert res.headers["www-authenticate"].startswith("Basic")

    def test_รหัสผ่านถูกเข้าได้(self):
        res = client.get("/api/health", headers=basic_header("anyuser", "s3cret-ไทย"))
        assert res.status_code == 200

    def test_รหัสผ่านผิดโดนบล็อก(self):
        res = client.get("/api/health", headers=basic_header("admin", "ผิด"))
        assert res.status_code == 401

    def test_username_ใส่อะไรก็ได้(self):
        for user in ("admin", "somchai", ""):
            res = client.get("/api/health", headers=basic_header(user, "s3cret-ไทย"))
            assert res.status_code == 200, f"username={user!r} ควรผ่านเพราะเช็กแค่รหัสผ่าน"

    def test_ครอบไฟล์สแตติกด้วย_ไม่ใช่แค่หน้าแรก(self):
        assert client.get("/static/style.css").status_code == 401
        res = client.get("/static/style.css", headers=basic_header("x", "s3cret-ไทย"))
        assert res.status_code == 200

    def test_header_รูปแบบผิดไม่พัง(self):
        assert client.get("/api/health", headers={"Authorization": "Bearer abc"}).status_code == 401
        assert client.get("/api/health", headers={"Authorization": "Basic !!!not-base64"}).status_code == 401
        assert client.get("/api/health", headers={"Authorization": "Basic"}).status_code == 401

    def test_หน้าแรกก็โดนป้องกัน(self):
        assert client.get("/").status_code == 401
