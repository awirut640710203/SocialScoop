"""เทสต์ HTTP endpoints — mock yt-dlp และ OpenRouter ทั้งหมด ไม่แตะเน็ตจริง"""

import pytest
from fastapi.testclient import TestClient

from app import ai_chat, downloader
from app.main import DOWNLOAD_DIR, app

client = TestClient(app)

SAMPLE_INFO = {
    "title": "รีวิวหูฟัง",
    "description": "เบสแน่นมาก สั่งที่ shp.ee/6xj9kq #หูฟัง",
    "uploader": "somchai",
    "like_count": 84_200,
    "webpage_url": "https://www.tiktok.com/@somchai/video/1",
    "extractor_key": "TikTok",
    "height": 1080,
}


@pytest.fixture(autouse=True)
def _clear_ai_cache():
    ai_chat.clear_cache()
    yield
    ai_chat.clear_cache()


class TestPages:
    def test_หน้าแรกโหลดได้(self):
        res = client.get("/")
        assert res.status_code == 200
        assert "SocialScoop" in res.text
        # ต้อง render template จริง ไม่ใช่ปล่อย Jinja tag ค้าง
        assert "{{" not in res.text

    def test_health(self):
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["ok"] is True

    def test_ไฟล์_static_เสิร์ฟได้(self):
        assert client.get("/static/style.css").status_code == 200
        assert client.get("/static/app.js").status_code == 200


class TestDetect:
    def test_รู้จักแพลตฟอร์ม(self):
        res = client.get("/api/detect", params={"url": "https://www.tiktok.com/@a/video/1"})
        assert res.json() == {"platform": "tiktok", "label": "TikTok"}

    def test_รู้จัก_x(self):
        res = client.get("/api/detect", params={"url": "https://x.com/NASA/status/123"})
        assert res.json() == {"platform": "x", "label": "X"}

    def test_รู้จักลิงก์ชื่อเดิม_twitter(self):
        res = client.get("/api/detect", params={"url": "https://twitter.com/NASA/status/123"})
        assert res.json() == {"platform": "x", "label": "X"}

    def test_ไม่รู้จักแพลตฟอร์ม(self):
        res = client.get("/api/detect", params={"url": "https://example.com/x"})
        assert res.json() == {"platform": None, "label": None}


class TestFetch:
    def test_ดึงรายละเอียดสำเร็จ(self, monkeypatch):
        monkeypatch.setattr(
            downloader, "fetch_metadata", lambda url: downloader.build_details(SAMPLE_INFO)
        )
        res = client.post("/api/fetch", json={"url": "https://www.tiktok.com/@a/video/1"})

        assert res.status_code == 200
        details = res.json()["details"]
        assert details["caption"] == SAMPLE_INFO["description"]
        assert details["shopee_links"] == ["https://shp.ee/6xj9kq"]
        assert details["hashtags"] == ["#หูฟัง"]
        assert details["stats"]["like"] == "84.2K"

    def test_ดึงไม่สำเร็จคืน_422_พร้อมข้อความไทย(self, monkeypatch):
        def boom(url):
            raise downloader.DownloadError("โพสต์นี้เป็นส่วนตัวหรือต้องล็อกอิน")

        monkeypatch.setattr(downloader, "fetch_metadata", boom)
        res = client.post("/api/fetch", json={"url": "https://www.instagram.com/p/x/"})

        assert res.status_code == 422
        assert "ส่วนตัว" in res.json()["detail"]

    def test_url_ว่างถูกปฏิเสธ(self):
        assert client.post("/api/fetch", json={"url": ""}).status_code == 422

    def test_ไม่มี_field_url(self):
        assert client.post("/api/fetch", json={}).status_code == 422


class TestDownload:
    def test_ดาวน์โหลดสำเร็จคืนชื่อไฟล์(self, monkeypatch):
        monkeypatch.setattr(
            downloader,
            "download_video",
            lambda url, out: {
                "video_path": str(out / "abc.mp4"),
                "filename": "abc.mp4",
                "details": downloader.build_details(SAMPLE_INFO),
            },
        )
        res = client.post("/api/download", json={"url": "https://www.tiktok.com/@a/video/1"})

        assert res.status_code == 200
        assert res.json()["filename"] == "abc.mp4"

    def test_ดาวน์โหลดพลาดคืน_422(self, monkeypatch):
        def boom(url, out):
            raise downloader.DownloadError("ไม่พบโพสต์นี้")

        monkeypatch.setattr(downloader, "download_video", boom)
        res = client.post("/api/download", json={"url": "https://www.tiktok.com/@a/video/1"})

        assert res.status_code == 422
        assert res.json()["detail"] == "ไม่พบโพสต์นี้"


class TestFileServing:
    def test_ดาวน์โหลดไฟล์ที่มีอยู่จริง(self):
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        target = DOWNLOAD_DIR / "pytest_sample.txt"
        target.write_text("hello", encoding="utf-8")
        try:
            res = client.get("/api/file/pytest_sample.txt")
            assert res.status_code == 200
            assert res.content == b"hello"
        finally:
            target.unlink(missing_ok=True)

    def test_ไฟล์ไม่มีคืน_404(self):
        assert client.get("/api/file/ไม่มีไฟล์นี้.mp4").status_code == 404

    @pytest.mark.parametrize(
        "attack",
        [
            "..%2F..%2Fsecrets.txt",
            "..%5C..%5Csecrets.txt",
            "%2Fetc%2Fpasswd",
            ".env",
        ],
    )
    def test_กัน_path_traversal(self, attack):
        # ต้องไม่มีทางหลุดออกนอกโฟลเดอร์ downloads ได้
        res = client.get(f"/api/file/{attack}")
        assert res.status_code in (400, 404)
        assert res.status_code != 200


class TestAsk:
    def test_ถามสำเร็จ(self, monkeypatch):
        monkeypatch.setattr(ai_chat, "ask_ai", lambda caption, question: "คำตอบจำลอง")
        res = client.post("/api/ask", json={"caption": "แคปชั่น", "question": "สรุปหน่อย"})

        assert res.status_code == 200
        assert res.json()["answer"] == "คำตอบจำลอง"

    def test_ไม่มี_api_key_คืนข้อความบอกวิธีแก้(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        res = client.post("/api/ask", json={"caption": "แคปชั่น", "question": "สรุปหน่อย"})

        assert res.status_code == 422
        assert "OPENROUTER_API_KEY" in res.json()["detail"]

    def test_คำถามว่างถูกปฏิเสธ(self):
        res = client.post("/api/ask", json={"caption": "แคปชั่น", "question": ""})
        assert res.status_code == 422


class TestAiChatUnit:
    def test_แคชไม่ยิงซ้ำ(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        calls = []

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "คำตอบ"}}]}

        def fake_post(*args, **kwargs):
            calls.append(1)
            return FakeResponse()

        monkeypatch.setattr(ai_chat.requests, "post", fake_post)

        assert ai_chat.ask_ai("แคปชั่นเดิม", "คำถามเดิม") == "คำตอบ"
        assert ai_chat.ask_ai("แคปชั่นเดิม", "คำถามเดิม") == "คำตอบ"
        assert len(calls) == 1, "คำถามซ้ำต้องใช้แคช ไม่ยิง API ใหม่"

    def test_api_key_ผิดแจ้งชัดเจน(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "bad-key")

        class Unauthorized:
            status_code = 401

            def raise_for_status(self):
                raise AssertionError("ไม่ควรถูกเรียกเมื่อเจอ 401")

            def json(self):
                return {}

        monkeypatch.setattr(ai_chat.requests, "post", lambda *a, **k: Unauthorized())

        with pytest.raises(ai_chat.AIError, match="API key"):
            ai_chat.ask_ai("แคปชั่น", "คำถาม")

    def test_ทุกรุ่นในลิสต์ต้องเป็นรุ่นฟรี(self):
        # กันเผลอเพิ่มรุ่นเสียเงินเข้ามาแล้วเกิดค่าใช้จ่ายโดยไม่รู้ตัว
        for model in ai_chat.FREE_MODELS:
            assert model.endswith(":free"), f"{model} ไม่ใช่รุ่นฟรี"

    def test_ไม่มีรุ่นที่ขึ้นบัญชีห้ามใช้(self):
        banned = {
            "nvidia/nemotron-3.5-lightning:free",   # พ่น chain-of-thought แม้ปิด reasoning
            "nvidia/nemotron-3-nano-30b-a3b:free",  # AA 14.5 อ่อนกว่าตัวอื่นในลิสต์
            "nvidia/nemotron-nano-9b-v2:free",      # AA 8.7 อ่อนสุด
            "liquid/lfm-2.5-2.6b:free",             # ไม่มีคะแนนใน AA และช้า
            "openrouter/free",                      # auto-router คุมรุ่นไม่ได้
        }
        assert not (set(ai_chat.FREE_MODELS) & banned)

    def test_เรียงตามความเร็วที่วัดจริง(self):
        """ลำดับต้องตรงกับเวลาตอบที่วัดจริงเมื่อ 2026-08-15 (เร็วไปช้า)

        เปลี่ยนจากเรียงตามคะแนนความฉลาด (Intelligence Index) มาเป็นความเร็ว เพราะ
        งานนี้คือสรุป/ตอบคำถามสั้นจากแคปชั่น ไม่ต้องการโมเดลฉลาดที่สุด แต่ต้องการ
        คำตอบไวที่สุด — ถ้าจะสลับลำดับ ต้องวัดเวลาจริงใหม่แล้วอัปเดตตัวเลขตรงนี้ด้วย
        ไม่ใช่เรียงตามความรู้สึก
        """
        measured_seconds = {
            "nvidia/nemotron-3-super-120b-a12b:free": 2.3,
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": 3.7,
            "cohere/north-mini-code:free": 4.8,
            "dots-studio/dots-3-note-preview:free": 3.5,  # เร็วกว่า cohere แต่เคยปนคำอังกฤษ
            "google/gemma-4-26b-a4b-it:free": 7.6,
        }
        assert set(ai_chat.FREE_MODELS) == set(measured_seconds), "ลิสต์ไม่ตรงกับตารางเวลาอ้างอิง"
        assert ai_chat.FREE_MODELS.index("cohere/north-mini-code:free") < ai_chat.FREE_MODELS.index(
            "dots-studio/dots-3-note-preview:free"
        ), "dots-studio เคยตอบปนภาษาอังกฤษ ต้องเรียงไว้หลัง cohere แม้จะเร็วกว่า"

    def test_ส่ง_reasoning_exclude_ไปด้วย(self, monkeypatch):
        # กันรุ่น reasoning ส่งความคิดปนมาในคำตอบ และลดโทเคนที่เสียเปล่า
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        captured = {}

        class Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "ตอบแล้ว"}}]}

        def fake_post(*args, **kwargs):
            captured.update(kwargs["json"])
            return Resp()

        monkeypatch.setattr(ai_chat.requests, "post", fake_post)
        ai_chat.ask_ai("แคปชั่น", "คำถาม")

        assert captured["reasoning"] == {"exclude": True}
        assert captured["max_tokens"] == ai_chat.MAX_TOKENS

    def test_timeout_ต้องไม่เกิน_20_วิ(self, monkeypatch):
        # ลดจาก 60s เดิม — รุ่นแรกค้างไม่ควรทำให้ผู้ใช้รอนานเกินไปก่อนข้ามไปรุ่นถัดไป
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        captured = {}

        class Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "ตอบแล้ว"}}]}

        def fake_post(*args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return Resp()

        monkeypatch.setattr(ai_chat.requests, "post", fake_post)
        ai_chat.ask_ai("แคปชั่น", "คำถาม")

        assert captured["timeout"] == ai_chat.REQUEST_TIMEOUT_SECONDS
        assert ai_chat.REQUEST_TIMEOUT_SECONDS <= 20

    def test_ถ้ามีค่าใช้จ่ายต้องหยุดทันที(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        class Charged:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "choices": [{"message": {"content": "คำตอบ"}}],
                    "usage": {"cost": 0.0012},
                }

        monkeypatch.setattr(ai_chat.requests, "post", lambda *a, **k: Charged())

        with pytest.raises(ai_chat.CostError, match="ค่าใช้จ่าย"):
            ai_chat.ask_ai("แคปชั่น", "คำถาม")

    def test_cost_ศูนย์ผ่านปกติ(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        class Free:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "choices": [{"message": {"content": "คำตอบฟรี"}}],
                    "usage": {"cost": 0},
                }

        monkeypatch.setattr(ai_chat.requests, "post", lambda *a, **k: Free())
        assert ai_chat.ask_ai("แคปชั่น", "คำถาม") == "คำตอบฟรี"

    def test_เจอ_429_ข้ามไปรุ่นถัดไป(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        seen = []

        class Resp:
            def __init__(self, code):
                self.status_code = code

            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "ตอบจากรุ่นสำรอง"}}]}

        def fake_post(*args, **kwargs):
            model = kwargs["json"]["model"]
            seen.append(model)
            return Resp(429 if len(seen) == 1 else 200)

        monkeypatch.setattr(ai_chat.requests, "post", fake_post)

        assert ai_chat.ask_ai("แคปชั่น", "คำถาม") == "ตอบจากรุ่นสำรอง"
        assert len(seen) == 2, "รุ่นแรกโดน 429 ต้องข้ามไปรุ่นที่สองทันที"

    def test_แคปชั่นว่างไม่ยิง_api(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setattr(
            ai_chat.requests,
            "post",
            lambda *a, **k: pytest.fail("ไม่ควรเรียก API เมื่อแคปชั่นว่าง"),
        )
        with pytest.raises(ai_chat.AIError):
            ai_chat.ask_ai("", "คำถาม")
