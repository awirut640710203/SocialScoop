"""เทสต์ระบบล็อกอิน — ชื่อผู้ใช้+รหัสผ่าน, คุกกี้จำอุปกรณ์, และการจำกัดการเดารหัส"""

import base64

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app

PASSWORD = "s3cret-ไทย"
USERNAME = "AUM"


def basic_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def fresh_client() -> TestClient:
    """คลายเอนต์ที่ยังไม่มีคุกกี้ติดมา — กันเทสต์หนึ่งไปใช้เซสชันของอีกเทสต์"""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_throttle():
    auth.reset_throttle()
    yield
    auth.reset_throttle()


class TestNoPasswordConfigured:
    def test_ไม่ตั้งรหัสผ่านเข้าได้ปกติ(self, monkeypatch):
        monkeypatch.delenv("SOCIALSCOOP_PASSWORD", raising=False)
        assert fresh_client().get("/api/health").status_code == 200


class TestPasswordConfigured:
    @pytest.fixture(autouse=True)
    def _set_password(self, monkeypatch):
        monkeypatch.setenv("SOCIALSCOOP_PASSWORD", PASSWORD)
        monkeypatch.delenv("SOCIALSCOOP_USERNAME", raising=False)

    def test_ไม่ใส่รหัสผ่านโดนบล็อก(self):
        res = fresh_client().get("/api/health")
        assert res.status_code == 401
        assert res.headers["www-authenticate"].startswith("Basic")

    def test_ชื่อผู้ใช้และรหัสผ่านถูกเข้าได้(self):
        res = fresh_client().get("/api/health", headers=basic_header(USERNAME, PASSWORD))
        assert res.status_code == 200

    def test_รหัสผ่านผิดโดนบล็อก(self):
        res = fresh_client().get("/api/health", headers=basic_header(USERNAME, "ผิด"))
        assert res.status_code == 401

    def test_ชื่อผู้ใช้ผิดโดนบล็อกแม้รหัสผ่านถูก(self):
        # เปลี่ยนจากพฤติกรรมเดิมที่ยอมรับ username อะไรก็ได้ — ตอนนี้ต้องเป็น AUM เท่านั้น
        for user in ("admin", "somchai", "aum", "AUM ", ""):
            res = fresh_client().get("/api/health", headers=basic_header(user, PASSWORD))
            assert res.status_code == 401, f"username={user!r} ไม่ควรผ่าน"

    def test_ตั้งชื่อผู้ใช้เองผ่าน_env_ได้(self, monkeypatch):
        monkeypatch.setenv("SOCIALSCOOP_USERNAME", "someoneelse")
        assert fresh_client().get("/api/health", headers=basic_header("someoneelse", PASSWORD)).status_code == 200
        assert fresh_client().get("/api/health", headers=basic_header(USERNAME, PASSWORD)).status_code == 401

    def test_ไฟล์สแตติกยังโดนป้องกัน(self):
        res = fresh_client().get("/static/style.css", follow_redirects=False)
        assert res.status_code != 200, "ห้ามเสิร์ฟไฟล์ให้คนที่ยังไม่ล็อกอิน"
        ok = fresh_client().get("/static/style.css", headers=basic_header(USERNAME, PASSWORD))
        assert ok.status_code == 200

    def test_header_รูปแบบผิดไม่พัง(self):
        c = fresh_client()
        assert c.get("/api/health", headers={"Authorization": "Bearer abc"}).status_code == 401
        assert c.get("/api/health", headers={"Authorization": "Basic !!!not-base64"}).status_code == 401
        assert c.get("/api/health", headers={"Authorization": "Basic"}).status_code == 401

    def test_หน้าเว็บที่ยังไม่ล็อกอินถูกพาไปหน้าล็อกอิน(self):
        res = fresh_client().get("/", follow_redirects=False)
        assert res.status_code == 303
        assert res.headers["location"] == "/login"

    def test_api_ที่ยังไม่ล็อกอินคืน_401_ไม่ใช่_redirect(self):
        # frontend เรียกด้วย fetch() ถ้าโดน redirect เป็น HTML จะ parse ไม่ได้
        res = fresh_client().get("/api/health", follow_redirects=False)
        assert res.status_code == 401

    def test_healthz_ยกเว้นไม่ต้องผ่านรหัส(self):
        # จำเป็นสำหรับ Render ตรวจสุขภาพเซิร์ฟเวอร์ — ถ้าโดนบล็อกจะคิดว่าแอปพัง
        res = fresh_client().get("/healthz")
        assert res.status_code == 200
        assert res.json() == {"ok": True}

    def test_api_health_ยังโดนป้องกันอยู่(self):
        # ต่างจาก /healthz ตรงนี้มีข้อมูล ai_enabled จึงยังป้องกันไว้เหมือนเดิม
        assert fresh_client().get("/api/health").status_code == 401

    def test_หน้าล็อกอินเข้าได้โดยไม่ต้องล็อกอิน(self):
        res = fresh_client().get("/login")
        assert res.status_code == 200
        assert "เข้าสู่ระบบ" in res.text


class TestLoginSession:
    """ล็อกอินครั้งเดียวแล้วเครื่องนั้นจำไว้ ไม่ต้องกรอกซ้ำ"""

    @pytest.fixture(autouse=True)
    def _set_password(self, monkeypatch):
        monkeypatch.setenv("SOCIALSCOOP_PASSWORD", PASSWORD)
        monkeypatch.delenv("SOCIALSCOOP_USERNAME", raising=False)

    def test_ล็อกอินสำเร็จได้คุกกี้แล้วใช้งานต่อได้เลย(self):
        client = fresh_client()
        res = client.post(
            "/login",
            data={"username": USERNAME, "password": PASSWORD},
            follow_redirects=False,
        )
        assert res.status_code == 303
        assert res.headers["location"] == "/"
        assert auth.SESSION_COOKIE in res.cookies

        # คำขอถัดไปไม่ต้องแนบรหัสผ่านอีก เพราะคุกกี้ติดไปกับคลายเอนต์แล้ว
        assert client.get("/api/health").status_code == 200
        assert client.get("/static/style.css").status_code == 200

    def test_คุกกี้อายุยาวพอให้ไม่ต้องล็อกอินซ้ำ(self):
        client = fresh_client()
        res = client.post(
            "/login",
            data={"username": USERNAME, "password": PASSWORD},
            follow_redirects=False,
        )
        cookie_header = res.headers["set-cookie"]
        assert "HttpOnly" in cookie_header, "ต้องกัน JS อ่านคุกกี้"
        assert "Max-Age=" in cookie_header
        max_age = int(cookie_header.split("Max-Age=")[1].split(";")[0])
        assert max_age >= 300 * 24 * 60 * 60, "ต้องจำได้อย่างน้อยหลายเดือน"

    def test_ล็อกอินผิดไม่ได้คุกกี้(self):
        client = fresh_client()
        res = client.post(
            "/login",
            data={"username": USERNAME, "password": "ผิด"},
            follow_redirects=False,
        )
        assert res.status_code == 401
        assert auth.SESSION_COOKIE not in res.cookies
        assert client.get("/api/health").status_code == 401

    def test_ชื่อผู้ใช้ผิดล็อกอินไม่ผ่าน(self):
        res = fresh_client().post(
            "/login",
            data={"username": "ไม่ใช่เจ้าของ", "password": PASSWORD},
            follow_redirects=False,
        )
        assert res.status_code == 401

    def test_คุกกี้ปลอมใช้ไม่ได้(self):
        client = fresh_client()
        client.cookies.set(auth.SESSION_COOKIE, "a" * 64)
        assert client.get("/api/health").status_code == 401

    def test_เปลี่ยนรหัสผ่านแล้วคุกกี้เดิมใช้ไม่ได้(self, monkeypatch):
        client = fresh_client()
        client.post("/login", data={"username": USERNAME, "password": PASSWORD}, follow_redirects=False)
        assert client.get("/api/health").status_code == 200

        # เปลี่ยนรหัสผ่าน = เตะทุกอุปกรณ์ออก เพราะโทเคนคุกกี้ผูกกับรหัสผ่านโดยตรง
        monkeypatch.setenv("SOCIALSCOOP_PASSWORD", "รหัสใหม่")
        assert client.get("/api/health").status_code == 401

    def test_ออกจากระบบแล้วต้องล็อกอินใหม่(self):
        client = fresh_client()
        client.post("/login", data={"username": USERNAME, "password": PASSWORD}, follow_redirects=False)
        assert client.get("/api/health").status_code == 200

        client.post("/logout", follow_redirects=False)
        assert client.get("/api/health").status_code == 401

    def test_ล็อกอินอยู่แล้วเปิดหน้า_login_เด้งกลับหน้าหลัก(self):
        client = fresh_client()
        client.post("/login", data={"username": USERNAME, "password": PASSWORD}, follow_redirects=False)
        res = client.get("/login", follow_redirects=False)
        assert res.status_code == 303
        assert res.headers["location"] == "/"


class TestLoginThrottle:
    """กันเดารหัสผ่านรัวๆ — สำคัญเพราะเว็บเปิดสาธารณะและรหัสผ่านอาจเป็นตัวเลขล้วน"""

    @pytest.fixture(autouse=True)
    def _set_password(self, monkeypatch):
        monkeypatch.setenv("SOCIALSCOOP_PASSWORD", PASSWORD)
        monkeypatch.delenv("SOCIALSCOOP_USERNAME", raising=False)

    def test_เดาผิดหลายครั้งโดนล็อกชั่วคราว(self):
        client = fresh_client()
        for _ in range(auth._MAX_ATTEMPTS):
            res = client.post(
                "/login",
                data={"username": USERNAME, "password": "เดามั่ว"},
                follow_redirects=False,
            )
            assert res.status_code == 401

        res = client.post(
            "/login",
            data={"username": USERNAME, "password": "เดามั่ว"},
            follow_redirects=False,
        )
        assert res.status_code == 429
        assert "รอ" in res.text

    def test_โดนล็อกแล้วรหัสถูกก็ยังเข้าไม่ได้จนกว่าจะหมดเวลา(self):
        client = fresh_client()
        for _ in range(auth._MAX_ATTEMPTS):
            client.post("/login", data={"username": USERNAME, "password": "เดามั่ว"}, follow_redirects=False)

        res = client.post(
            "/login",
            data={"username": USERNAME, "password": PASSWORD},
            follow_redirects=False,
        )
        assert res.status_code == 429, "ระหว่างโดนล็อกต้องไม่ยอมให้ลองต่อ แม้รหัสจะถูก"

    def test_ล็อกอินสำเร็จล้างตัวนับ(self):
        client = fresh_client()
        for _ in range(auth._MAX_ATTEMPTS - 1):
            client.post("/login", data={"username": USERNAME, "password": "เดามั่ว"}, follow_redirects=False)

        ok = client.post(
            "/login",
            data={"username": USERNAME, "password": PASSWORD},
            follow_redirects=False,
        )
        assert ok.status_code == 303

        # เดาผิดใหม่ต้องเริ่มนับจากศูนย์ ไม่ใช่โดนล็อกทันทีเพราะยอดเก่าค้าง
        auth_client = fresh_client()
        res = auth_client.post(
            "/login",
            data={"username": USERNAME, "password": "เดามั่ว"},
            follow_redirects=False,
        )
        assert res.status_code == 401
