"""เทสต์ฟังก์ชันแปล error ของ yt-dlp เป็นข้อความไทย — ไม่ต้องต่ออินเทอร์เน็ต"""

from app import downloader
from app.downloader import _friendly_error
from app.extract import media_type


class TestFriendlyErrorTikTok:
    def test_universal_data_error(self):
        msg = _friendly_error(RuntimeError("Unable to extract universal data for rehydration"))
        assert "คุกกี้" in msg

    def test_rehydration_error(self):
        msg = _friendly_error(RuntimeError("rehydration failed"))
        assert "คุกกี้" in msg

    def test_unexpected_response_error(self):
        # เจอจริงตอน deploy บน Render — TikTok ปฏิเสธ challenge cookie จาก IP คลาวด์
        msg = _friendly_error(RuntimeError("Unexpected response from webpage request"))
        assert "คุกกี้" in msg


class TestFriendlyErrorGeneric:
    def test_private_post(self):
        msg = _friendly_error(RuntimeError("This account is private"))
        assert "ส่วนตัว" in msg

    def test_not_found(self):
        msg = _friendly_error(RuntimeError("Video does not exist"))
        assert "ไม่พบโพสต์" in msg

    def test_unsupported_url(self):
        msg = _friendly_error(RuntimeError("Unsupported URL: https://example.com"))
        assert "ยังไม่รองรับ" in msg

    def test_unknown_error_falls_back_to_raw_message(self):
        msg = _friendly_error(RuntimeError("some totally new yt-dlp error"))
        assert "some totally new yt-dlp error" in msg


class TestEnrichXPhoto:
    """เติม thumbnail ให้โพสต์ X ที่มีแต่รูป — ไม่งั้นหน้าเว็บไม่ขึ้นปุ่มดาวน์โหลดเลย"""

    def _patch_photo(self, monkeypatch, value):
        calls = []

        def fake(url):
            calls.append(url)
            return value

        monkeypatch.setattr(downloader.x_extractor, "best_photo_url", fake)
        return calls

    def test_โพสต์รูปล้วนได้_thumbnail_และกลายเป็น_image(self, monkeypatch):
        self._patch_photo(monkeypatch, "https://pbs.twimg.com/media/A.jpg?name=orig")
        info = {"formats": [], "thumbnail": None}

        downloader._enrich_x_photo("https://x.com/u/status/1", info)

        assert info["thumbnail"] == "https://pbs.twimg.com/media/A.jpg?name=orig"
        assert media_type(info) == "image"

    def test_โพสต์วิดีโอไม่ถูกแตะและไม่ยิงเน็ต(self, monkeypatch):
        calls = self._patch_photo(monkeypatch, "https://pbs.twimg.com/media/A.jpg")
        info = {"formats": [{"url": "https://video.twimg.com/x.mp4"}]}

        downloader._enrich_x_photo("https://x.com/u/status/1", info)

        assert "thumbnail" not in info
        assert calls == []

    def test_มี_thumbnail_อยู่แล้วไม่ยิงซ้ำ(self, monkeypatch):
        calls = self._patch_photo(monkeypatch, "https://pbs.twimg.com/media/NEW.jpg")
        info = {"formats": [], "thumbnail": "https://pbs.twimg.com/media/OLD.jpg"}

        downloader._enrich_x_photo("https://x.com/u/status/1", info)

        assert info["thumbnail"] == "https://pbs.twimg.com/media/OLD.jpg"
        assert calls == []

    def test_แพลตฟอร์มอื่นไม่ยิงเน็ตเลย(self, monkeypatch):
        # Instagram โพสต์รูปล้วนมี thumbnail จาก yt-dlp อยู่แล้ว ไม่ต้องพึ่ง X API
        calls = self._patch_photo(monkeypatch, "https://pbs.twimg.com/media/A.jpg")
        info = {"formats": [], "thumbnail": None}

        downloader._enrich_x_photo("https://www.instagram.com/p/Cabc/", info)

        assert calls == []

    def test_ดึงรูปไม่ได้ก็ไม่พังและไม่ใส่ค่าปลอม(self, monkeypatch):
        self._patch_photo(monkeypatch, None)
        info = {"formats": [], "thumbnail": None}

        downloader._enrich_x_photo("https://x.com/u/status/1", info)

        assert info["thumbnail"] is None
        assert media_type(info) is None
