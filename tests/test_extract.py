"""เทสต์ฟังก์ชัน parse — ไม่ต้องต่ออินเทอร์เน็ต"""

import pytest

from app.extract import (
    build_details,
    detect_platform,
    find_shopee_links,
    format_count,
    parse_hashtags,
)


class TestDetectPlatform:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.tiktok.com/@user/video/7123456789", "tiktok"),
            ("https://vt.tiktok.com/ZSabc123/", "tiktok"),
            ("tiktok.com/@user/video/1", "tiktok"),  # ไม่มี scheme
            ("https://www.instagram.com/reel/Cabc123/", "instagram"),
            ("https://instagram.com/p/Cxyz/", "instagram"),
            ("https://www.threads.com/@zuck/post/abc", "threads"),
            ("https://www.threads.net/@zuck/post/abc", "threads"),
            ("https://youtube.com/watch?v=abc", None),
            ("", None),
            ("   ", None),
            ("ไม่ใช่ลิงก์", None),
        ],
    )
    def test_detect(self, url, expected):
        assert detect_platform(url) == expected

    def test_ไม่หลงโดเมนปลอมที่ลงท้ายคล้ายกัน(self):
        # tiktok.com.evil.com ต้องไม่ถูกมองว่าเป็น TikTok
        assert detect_platform("https://tiktok.com.evil.com/x") is None
        assert detect_platform("https://faketiktok.com/x") is None


class TestParseHashtags:
    def test_แฮชแท็กภาษาไทย(self):
        caption = "รีวิวจริง #หูฟังไร้สาย #รีวิวของจริง"
        assert parse_hashtags(caption) == ["#หูฟังไร้สาย", "#รีวิวของจริง"]

    def test_ผสมไทยอังกฤษตัวเลข(self):
        assert parse_hashtags("#test123 #ของดี #a_b") == ["#test123", "#ของดี", "#a_b"]

    def test_ไม่ซ้ำและเรียงตามที่พบ(self):
        assert parse_hashtags("#a #b #a #c") == ["#a", "#b", "#c"]

    def test_ไม่มีแฮชแท็ก(self):
        assert parse_hashtags("ข้อความเปล่า ๆ") == []
        assert parse_hashtags("") == []
        assert parse_hashtags(None) == []


class TestFindShopeeLinks:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("สั่งที่ shp.ee/6xj9kq", ["https://shp.ee/6xj9kq"]),
            ("https://shopee.co.th/product/123/456", ["https://shopee.co.th/product/123/456"]),
            ("https://s.shopee.co.th/9zAbCd", ["https://s.shopee.co.th/9zAbCd"]),
        ],
    )
    def test_รูปแบบลิงก์ต่าง_ๆ(self, text, expected):
        assert find_shopee_links(text) == expected

    def test_ตัดเครื่องหมายวรรคตอนท้ายลิงก์(self):
        assert find_shopee_links("ซื้อที่ shp.ee/abc123.") == ["https://shp.ee/abc123"]
        assert find_shopee_links("ดูที่ (shp.ee/abc123)") == ["https://shp.ee/abc123"]

    def test_หลายลิงก์ในแคปชั่นเดียว(self):
        text = "ตัวแรก shp.ee/aaa111 ตัวสอง https://shopee.co.th/product/9/9"
        assert find_shopee_links(text) == [
            "https://shp.ee/aaa111",
            "https://shopee.co.th/product/9/9",
        ]

    def test_ไม่ซ้ำ(self):
        assert find_shopee_links("shp.ee/x1 และ shp.ee/x1") == ["https://shp.ee/x1"]

    def test_ไม่จับลิงก์ที่ไม่ใช่_shopee(self):
        assert find_shopee_links("https://lazada.co.th/p/1 https://example.com") == []

    def test_ข้อความว่าง(self):
        assert find_shopee_links("") == []
        assert find_shopee_links(None) == []


class TestFormatCount:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            (0, "0"),
            (999, "999"),
            (1_000, "1K"),
            (84_200, "84.2K"),
            (920_000, "920K"),
            (1_500_000, "1.5M"),
        ],
    )
    def test_format(self, value, expected):
        assert format_count(value) == expected

    def test_ศูนย์ต่างจากไม่มีข้อมูล(self):
        # 0 คือ "มีข้อมูล แต่ยอดเป็นศูนย์" ส่วน None คือ "ไม่มีข้อมูล" — ต้องแยกกันชัดเจน
        assert format_count(0) == "0"
        assert format_count(None) is None


class TestBuildDetails:
    def test_ประกอบข้อมูลครบ(self):
        info = {
            "title": "รีวิวหูฟัง",
            "description": "เบสแน่นมาก สั่งที่ shp.ee/6xj9kq #หูฟัง #รีวิว",
            "uploader": "somchai",
            "like_count": 84_200,
            "comment_count": 1_200,
            "view_count": 920_000,
            "webpage_url": "https://www.tiktok.com/@somchai/video/1",
            "thumbnail": "https://cdn.example/t.jpg",
            "extractor_key": "TikTok",
            "height": 1080,
        }
        details = build_details(info)

        assert details["caption"] == info["description"]
        assert details["hashtags"] == ["#หูฟัง", "#รีวิว"]
        assert details["shopee_links"] == ["https://shp.ee/6xj9kq"]
        assert details["stats"] == {"like": "84.2K", "comment": "1.2K", "view": "920K"}
        assert details["resolution"] == "1080p"
        assert details["platform"] == "TikTok"

    def test_field_ที่ขาดหายเป็น_None_ไม่ใช่ศูนย์(self):
        # เคสของ Threads ที่ yt-dlp ใช้ generic extractor แล้วไม่มียอดกลับมา
        details = build_details({"title": "โพสต์", "description": "ข้อความ"})

        assert details["stats"] == {"like": None, "comment": None, "view": None}
        assert details["thumbnail"] is None
        assert details["resolution"] is None
        assert details["shopee_links"] == []

    def test_ใช้_title_เป็นแคปชั่นถ้าไม่มี_description(self):
        details = build_details({"title": "แคปชั่นอยู่ใน title #แท็ก"})
        assert details["caption"] == "แคปชั่นอยู่ใน title #แท็ก"
        assert details["hashtags"] == ["#แท็ก"]

    def test_คลิปแนวตั้ง_1080x1920_ต้องอ่านว่า_1080p(self):
        # กันบั๊กเดิม: เคยรายงานเป็น "1920p" เพราะดูแต่ความสูง
        info = {"title": "x", "width": 1080, "height": 1920}
        assert build_details(info)["resolution"] == "1080p"

    def test_คลิปแนวนอน_1920x1080_ต้องอ่านว่า_1080p(self):
        info = {"title": "x", "width": 1920, "height": 1080}
        assert build_details(info)["resolution"] == "1080p"

    def test_เดาความละเอียดจากรายการ_formats_เลือกดีที่สุด(self):
        # เลียนแบบ format จริงของ TikTok ที่เป็นแนวตั้งทั้งหมด
        info = {
            "title": "x",
            "formats": [
                {"width": 576, "height": 1024},
                {"width": 720, "height": 1280},
                {"width": 1080, "height": 1920},
            ],
        }
        assert build_details(info)["resolution"] == "1080p"

    def test_แคปชั่นว่างคืน_None(self):
        details = build_details({})
        assert details["caption"] is None
