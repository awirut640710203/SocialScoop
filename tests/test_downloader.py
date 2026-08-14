"""เทสต์ฟังก์ชันแปล error ของ yt-dlp เป็นข้อความไทย — ไม่ต้องต่ออินเทอร์เน็ต"""

from app.downloader import _friendly_error


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
