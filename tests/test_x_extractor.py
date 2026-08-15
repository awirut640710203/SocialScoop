"""เทสต์ตัวดึงรูปภาพของ X — ไม่ต่อเน็ตจริง ใช้ requests.get ปลอมแทน

โครงสร้าง JSON ที่ใช้ในเทสต์นี้คัดลอกมาจากคำตอบจริงของ syndication API
(x.com/NASAHubble/status/2032819034232619122 และโพสต์ที่มีทั้งวิดีโอและรูปปนกัน)
"""

import pytest
import requests

from app import x_extractor


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture
def fake_get(monkeypatch):
    """แทนที่ requests.get แล้วเก็บพารามิเตอร์ที่ถูกเรียกไว้ตรวจ"""
    calls = []

    def install(payload, status=200):
        def _get(url, params=None, headers=None, timeout=None):
            calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
            if isinstance(payload, requests.RequestException):
                raise payload
            return FakeResponse(payload, status)

        monkeypatch.setattr(x_extractor.requests, "get", _get)
        return calls

    return install


class TestTweetId:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://x.com/NASA/status/2016900969389289568", "2016900969389289568"),
            ("https://twitter.com/NASA/status/123", "123"),
            ("https://www.x.com/NASA/status/123", "123"),
            ("https://mobile.twitter.com/NASA/status/123", "123"),
            ("https://m.x.com/NASA/status/123", "123"),
            ("https://x.com/i/web/status/123", "123"),
            ("https://x.com/statuses/123", "123"),
            ("https://x.com/NASA/status/123/photo/1", "123"),  # ลิงก์ที่กดจากรูปโดยตรง
            ("https://x.com/NASA/status/123?s=20&t=abc", "123"),
            ("  https://x.com/NASA/status/123  ", "123"),  # มีช่องว่างติดมาจากการคัดลอก
        ],
    )
    def test_ดึงไอดีได้(self, url, expected):
        assert x_extractor.tweet_id(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://x.com/NASA",  # หน้าโปรไฟล์ ไม่ใช่โพสต์
            "https://x.com/NASA/status/abc",  # ไอดีไม่ใช่ตัวเลข
            "https://instagram.com/p/Cabc/",
            "https://x.com.evil.com/NASA/status/123",  # โดเมนปลอมที่ขึ้นต้นเหมือนกัน
            "",
            None,
        ],
    )
    def test_ไม่ใช่ลิงก์โพสต์คืน_None(self, url):
        assert x_extractor.tweet_id(url) is None


class TestPhotoUrls:
    def test_โพสต์รูปล้วนได้ลิงก์รูปคุณภาพต้นฉบับ(self, fake_get):
        calls = fake_get({
            "mediaDetails": [
                {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/AAA.jpg"},
            ]
        })

        urls = x_extractor.photo_urls("https://x.com/NASAHubble/status/2032819034232619122")

        assert urls == ["https://pbs.twimg.com/media/AAA.jpg?format=jpg&name=orig"]
        assert calls[0]["params"]["id"] == "2032819034232619122"

    def test_เรียงตามลำดับในโพสต์และไม่ซ้ำ(self, fake_get):
        fake_get({
            "mediaDetails": [
                {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/A.jpg"},
                {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/B.jpg"},
                {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/A.jpg"},
            ]
        })

        urls = x_extractor.photo_urls("https://x.com/u/status/1")

        assert [u.split("?")[0].rsplit("/", 1)[-1] for u in urls] == ["A.jpg", "B.jpg"]

    def test_ข้ามวิดีโอเอาเฉพาะรูป(self, fake_get):
        # โพสต์ที่มีทั้งวิดีโอและรูปปนกันมีจริง — วิดีโอปล่อยให้ yt-dlp จัดการ
        fake_get({
            "mediaDetails": [
                {"type": "video", "media_url_https": "https://pbs.twimg.com/ext_tw_video_thumb/V.jpg"},
                {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/P.jpg"},
            ]
        })

        urls = x_extractor.photo_urls("https://x.com/u/status/1")

        assert len(urls) == 1
        assert "media/P.jpg" in urls[0]

    def test_โพสต์ข้อความล้วนคืนลิสต์ว่าง(self, fake_get):
        fake_get({"text": "แค่ข้อความ ไม่มีสื่อ"})
        assert x_extractor.photo_urls("https://x.com/u/status/1") == []

    def test_ไม่ยิงเน็ตเลยถ้าไม่ใช่ลิงก์_X(self, fake_get):
        calls = fake_get({"mediaDetails": []})
        assert x_extractor.photo_urls("https://instagram.com/p/Cabc/") == []
        assert calls == []

    @pytest.mark.parametrize(
        "payload,status",
        [
            ({}, 404),
            ({}, 500),
            (requests.ConnectionError("network down"), 200),
            (requests.Timeout("too slow"), 200),
            (ValueError("not json"), 200),  # ตอบกลับมาไม่ใช่ JSON
            ("ไม่ใช่ dict", 200),
            (None, 200),
        ],
    )
    def test_ล้มแล้วเงียบไม่โยน_error(self, fake_get, payload, status):
        # เป็นแค่ส่วนเสริม ถ้าล้มต้องไม่ทำให้ทั้งคำขอพัง ผู้ใช้ยังต้องได้ข้อมูลจาก yt-dlp
        fake_get(payload, status)
        assert x_extractor.photo_urls("https://x.com/u/status/1") == []

    def test_ส่ง_user_agent_ไปด้วย(self, fake_get):
        # ไม่ส่ง UA ของเบราว์เซอร์ = X ปฏิเสธคำขอ
        calls = fake_get({"mediaDetails": []})
        x_extractor.photo_urls("https://x.com/u/status/1")
        assert "Mozilla" in calls[0]["headers"]["User-Agent"]
        assert calls[0]["timeout"] == x_extractor._TIMEOUT_SECONDS


class TestBestPhotoUrl:
    def test_เอารูปแรก(self, fake_get):
        fake_get({
            "mediaDetails": [
                {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/first.jpg"},
                {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/second.jpg"},
            ]
        })
        assert "media/first.jpg" in x_extractor.best_photo_url("https://x.com/u/status/1")

    def test_ไม่มีรูปคืน_None(self, fake_get):
        fake_get({"mediaDetails": []})
        assert x_extractor.best_photo_url("https://x.com/u/status/1") is None


class TestUpgradeQuality:
    def test_เติมพารามิเตอร์ขอไฟล์ต้นฉบับ(self):
        assert x_extractor._upgrade_quality("https://pbs.twimg.com/media/A.jpg") == (
            "https://pbs.twimg.com/media/A.jpg?format=jpg&name=orig"
        )

    def test_url_ที่มี_query_อยู่แล้วต่อด้วย_and(self):
        assert x_extractor._upgrade_quality("https://pbs.twimg.com/media/A?x=1") == (
            "https://pbs.twimg.com/media/A?x=1&format=jpg&name=orig"
        )
