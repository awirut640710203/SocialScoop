"""เทสต์แคช fetch->download — ยืนยันว่า download_video ไม่ยิงซ้ำถ้าเพิ่ง fetch_metadata
ไปหมาดๆ (ไม่แตะเน็ต/เบราว์เซอร์จริง ใช้ stub ทั้งหมด)
"""

import pytest

from app import downloader, threads_extractor

TIKTOK_URL = "https://www.tiktok.com/@a/video/123"
THREADS_URL = "https://www.threads.com/@a/post/DJDNCztRGb1"

THREADS_NODE = {
    "code": "DJDNCztRGb1",
    "user": {"username": "a"},
    "caption": None,
    "like_count": 0,
    "video_versions": [{"type": 101, "url": "https://cdn.example.com/video.mp4"}],
    "image_versions2": {"candidates": []},
}


@pytest.fixture(autouse=True)
def _clear_cache():
    downloader._cache.clear()
    yield
    downloader._cache.clear()


class _StubYoutubeDL:
    """แทน yt_dlp.YoutubeDL — นับจำนวนครั้งที่ extract_info/process_ie_result ถูกเรียก"""

    calls: list[str] = []
    extract_result: dict = {}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download):
        _StubYoutubeDL.calls.append("extract_info")
        return dict(_StubYoutubeDL.extract_result)

    def process_ie_result(self, info, download):
        _StubYoutubeDL.calls.append("process_ie_result")
        return dict(info)

    def prepare_filename(self, info):
        return self.opts["outtmpl"].replace("%(id)s.%(ext)s", f"{info['id']}.mp4")


class TestYtdlpCacheReuse:
    def test_download_หลัง_fetch_ใช้แคชไม่ยิงซ้ำ(self, monkeypatch, tmp_path):
        _StubYoutubeDL.calls = []
        _StubYoutubeDL.extract_result = {"id": "123", "title": "t", "webpage_url": TIKTOK_URL}
        monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _StubYoutubeDL)
        (tmp_path / "123.mp4").write_bytes(b"x")

        downloader.fetch_metadata(TIKTOK_URL)
        downloader.download_video(TIKTOK_URL, tmp_path)

        assert _StubYoutubeDL.calls == ["extract_info", "process_ie_result"], (
            "ครั้งที่สองต้องใช้ process_ie_result (แคช) ไม่ใช่ extract_info (ยิงซ้ำ)"
        )

    def test_download_ตรงๆไม่ผ่าน_fetch_ก่อนต้องยิงจริง(self, monkeypatch, tmp_path):
        _StubYoutubeDL.calls = []
        _StubYoutubeDL.extract_result = {"id": "123", "title": "t", "webpage_url": TIKTOK_URL}
        monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _StubYoutubeDL)
        (tmp_path / "123.mp4").write_bytes(b"x")

        downloader.download_video(TIKTOK_URL, tmp_path)

        assert _StubYoutubeDL.calls == ["extract_info"], "ไม่มีแคช ต้องยิง extract_info จริง"

    def test_แคชหมดอายุกลับไปยิงจริง(self, monkeypatch, tmp_path):
        _StubYoutubeDL.calls = []
        _StubYoutubeDL.extract_result = {"id": "123", "title": "t", "webpage_url": TIKTOK_URL}
        monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _StubYoutubeDL)
        (tmp_path / "123.mp4").write_bytes(b"x")

        downloader.fetch_metadata(TIKTOK_URL)
        # บังคับให้แคชหมดอายุโดยไม่ต้องรอจริง
        expires_at, value = downloader._cache[TIKTOK_URL]
        downloader._cache[TIKTOK_URL] = (expires_at - downloader._CACHE_TTL_SECONDS - 1, value)

        downloader.download_video(TIKTOK_URL, tmp_path)

        assert _StubYoutubeDL.calls == ["extract_info", "extract_info"], (
            "แคชหมดอายุแล้วต้องยิงใหม่ ไม่ใช้ของเก่า"
        )

    def test_url_คนละอันไม่ใช้แคชร่วมกัน(self, monkeypatch, tmp_path):
        _StubYoutubeDL.calls = []
        _StubYoutubeDL.extract_result = {"id": "123", "title": "t", "webpage_url": TIKTOK_URL}
        monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _StubYoutubeDL)
        (tmp_path / "123.mp4").write_bytes(b"x")

        downloader.fetch_metadata(TIKTOK_URL)
        downloader.download_video("https://www.tiktok.com/@other/video/999", tmp_path)

        assert _StubYoutubeDL.calls == ["extract_info", "extract_info"]


class TestThreadsCacheReuse:
    def test_download_หลัง_fetch_ไม่เปิด_chromium_ซ้ำ(self, monkeypatch, tmp_path):
        calls = []

        def fake_fetch_node(url):
            calls.append(url)
            return THREADS_NODE

        monkeypatch.setattr(threads_extractor, "fetch_node", fake_fetch_node)

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size):
                return [b"video-bytes"]

        monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResp())

        downloader.fetch_metadata(THREADS_URL)
        result = downloader.download_video(THREADS_URL, tmp_path)

        assert calls == [THREADS_URL], "ต้องเปิด Chromium (fetch_node) แค่ครั้งเดียว ไม่ใช่สองครั้ง"
        assert result["filename"] == "DJDNCztRGb1.mp4"

    def test_download_ตรงๆไม่ผ่าน_fetch_ก่อนต้องเปิด_chromium_จริง(self, monkeypatch, tmp_path):
        calls = []

        def fake_fetch_node(url):
            calls.append(url)
            return THREADS_NODE

        monkeypatch.setattr(threads_extractor, "fetch_node", fake_fetch_node)

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size):
                return [b"video-bytes"]

        monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResp())

        downloader.download_video(THREADS_URL, tmp_path)

        assert calls == [THREADS_URL]

    def test_ลิงก์แชร์ไม่มี_post_ในตัวเองก็ดาวน์โหลดได้(self, monkeypatch, tmp_path):
        # threads.com/share/xxxxx/ ไม่มี "/post/" ในตัวเอง — ชื่อไฟล์ต้องมาจาก
        # node['code'] ที่ resolve หลัง redirect แล้ว ไม่ใช่แกะจาก url ตรงๆ (เคยพังมาแล้ว)
        share_url = "https://www.threads.com/share/_gPhmX3c8/"
        monkeypatch.setattr(threads_extractor, "fetch_node", lambda url: THREADS_NODE)

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size):
                return [b"video-bytes"]

        monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: FakeResp())

        result = downloader.download_video(share_url, tmp_path)

        assert result["filename"] == "DJDNCztRGb1.mp4"
