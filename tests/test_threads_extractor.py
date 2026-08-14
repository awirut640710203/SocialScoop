"""เทสต์การแกะ JSON ที่ฝังอยู่ในหน้า Threads — ไม่ต้องต่ออินเทอร์เน็ตหรือเปิดเบราว์เซอร์จริง

โครงสร้าง node จำลองตามของจริงที่ตรวจสอบมาจากหน้าโพสต์ Threads จริง (เทียบ commit message)
"""

import json

import pytest

from app.threads_extractor import (
    ThreadsExtractError,
    best_thumbnail_url,
    best_video_url,
    build_details,
    find_reply_captions,
    media_type,
    parse_post_node,
    shortcode_from_url,
)

SAMPLE_NODE = {
    "code": "DJDNCztRGb1",
    "user": {"username": "guilfoilpr", "full_name": "John Guilfoil Public Relations"},
    "caption": {"text": "รีวิวของจริง #หูฟัง สั่งที่ shp.ee/6xj9kq"},
    "like_count": 1,
    "taken_at": 1745971738,
    "text_post_app_info": {"direct_reply_count": 3},
    "video_versions": [
        {"type": 101, "url": "https://cdn.example.com/best.mp4"},
        {"type": 102, "url": "https://cdn.example.com/worse.mp4"},
    ],
    "image_versions2": {
        "candidates": [
            {"height": 1136, "url": "https://cdn.example.com/thumb.jpg"},
        ]
    },
}


def _wrap_in_page(node: dict) -> str:
    payload = json.dumps({"data": {"post": node}})
    return f'<html><body><script type="application/json">{payload}</script></body></html>'


class TestShortcodeFromUrl:
    def test_ดึง_shortcode_ได้(self):
        assert shortcode_from_url("https://www.threads.com/@zuck/post/DJDNCztRGb1") == "DJDNCztRGb1"

    def test_ดึง_shortcode_ได้แม้มี_query_string(self):
        assert shortcode_from_url("https://www.threads.net/@zuck/post/abc123?x=1") == "abc123"

    def test_ไม่ใช่ลิงก์โพสต์ต้องพัง(self):
        with pytest.raises(ThreadsExtractError):
            shortcode_from_url("https://www.threads.com/@zuck")


class TestParsePostNode:
    def test_หา_node_ที่ตรง_shortcode_เจอ(self):
        html = _wrap_in_page(SAMPLE_NODE)
        node = parse_post_node(html, "DJDNCztRGb1")
        assert node["code"] == "DJDNCztRGb1"

    def test_ไม่เจอ_node_เลยต้องพังพร้อมข้อความไทย(self):
        html = "<html><body><script type=\"application/json\">{}</script></body></html>"
        with pytest.raises(ThreadsExtractError, match="ไม่พบข้อมูลโพสต์"):
            parse_post_node(html, "abc")

    def test_json_พังไม่ทำให้ทั้งหมดพัง(self):
        html = (
            '<script type="application/json">not valid json</script>'
            + _wrap_in_page(SAMPLE_NODE)
        )
        node = parse_post_node(html, "DJDNCztRGb1")
        assert node["code"] == "DJDNCztRGb1"


class TestFindReplyCaptions:
    def _wrap_thread_items(self, own_code, items, decoy_code=None, decoy_items=None):
        payload = {
            "data": {
                "data": {"edges": [{"node": {"thread_items": items}}]},
            }
        }
        if decoy_items is not None:
            # จำลอง relatedPosts ที่ใช้คีย์ "thread_items" ชื่อเดียวกันแต่เป็นโพสต์คนละเรื่อง
            payload["data"]["relatedPosts"] = {"threads": [{"thread_items": decoy_items}]}
        return f'<html><body><script type="application/json">{json.dumps(payload)}</script></body></html>'

    def test_ดึงแคปชั่นคอมเมนต์ของโพสต์เจอ(self):
        items = [
            {"post": {"code": "DJDNCztRGb1", "caption": {"text": "แคปชั่นหลัก"}}},
            {"post": {"code": "reply1", "caption": {"text": "สนใจสั่งที่ shp.ee/xyz123 นะ"}}},
        ]
        html = self._wrap_thread_items("DJDNCztRGb1", items)
        captions = find_reply_captions(html, "DJDNCztRGb1")
        assert "สนใจสั่งที่ shp.ee/xyz123 นะ" in captions

    def test_ไม่ดึงจาก_relatedPosts_ที่ไม่เกี่ยวข้อง(self):
        items = [{"post": {"code": "DJDNCztRGb1", "caption": {"text": "แคปชั่นหลัก"}}}]
        decoy = [{"post": {"code": "other999", "caption": {"text": "อย่าดึงอันนี้ shp.ee/should-not-appear"}}}]
        html = self._wrap_thread_items("DJDNCztRGb1", items, decoy_items=decoy)
        captions = find_reply_captions(html, "DJDNCztRGb1")
        assert not any("should-not-appear" in c for c in captions)

    def test_ไม่เจอ_thread_ของโพสต์นี้เลยคืนลิสต์ว่าง(self):
        html = "<html><body><script type=\"application/json\">{}</script></body></html>"
        assert find_reply_captions(html, "DJDNCztRGb1") == []


class TestBestMedia:
    def test_เลือกวิดีโอตัวแรกเป็นคุณภาพดีที่สุด(self):
        assert best_video_url(SAMPLE_NODE) == "https://cdn.example.com/best.mp4"

    def test_ไม่มีวิดีโอคืน_none(self):
        node = {**SAMPLE_NODE, "video_versions": []}
        assert best_video_url(node) is None

    def test_ดึง_thumbnail_ได้(self):
        assert best_thumbnail_url(SAMPLE_NODE) == "https://cdn.example.com/thumb.jpg"

    def test_carousel_ดึงจาก_item_แรกที่มีวิดีโอ(self):
        node = {
            "code": "x",
            "user": {},
            "caption": None,
            "carousel_media": [
                {"image_versions2": {"candidates": [{"url": "https://cdn.example.com/photo.jpg"}]}},
                {"video_versions": [{"type": 101, "url": "https://cdn.example.com/vid.mp4"}]},
            ],
        }
        assert best_video_url(node) == "https://cdn.example.com/vid.mp4"


class TestMediaType:
    def test_มีวิดีโอคืน_video(self):
        assert media_type(SAMPLE_NODE) == "video"

    def test_มีแต่รูปคืน_image(self):
        node = {**SAMPLE_NODE, "video_versions": []}
        assert media_type(node) == "image"

    def test_ไม่มีสื่อเลยคืน_none(self):
        node = {**SAMPLE_NODE, "video_versions": [], "image_versions2": {"candidates": []}}
        assert media_type(node) is None


class TestBuildDetails:
    def test_แปลงข้อมูลครบ(self):
        details = build_details(SAMPLE_NODE, "https://www.threads.com/@guilfoilpr/post/DJDNCztRGb1")

        assert details["uploader"] == "guilfoilpr"
        assert details["platform"] == "Threads"
        assert details["caption"] == "รีวิวของจริง #หูฟัง สั่งที่ shp.ee/6xj9kq"
        assert details["hashtags"] == ["#หูฟัง"]
        assert details["shopee_links"] == ["https://shp.ee/6xj9kq"]
        assert details["stats"]["like"] == "1"
        assert details["stats"]["comment"] == "3"
        assert details["stats"]["view"] is None
        assert details["upload_date"] == "20250430"
        assert details["media_type"] == "video"

    def test_โพสต์รูปภาพล้วน_media_type_เป็น_image(self):
        node = {**SAMPLE_NODE, "video_versions": []}
        details = build_details(node, "https://www.threads.com/@guilfoilpr/post/DJDNCztRGb1")
        assert details["media_type"] == "image"

    def test_โพสต์ไม่มีแคปชั่นเป็น_none(self):
        node = {**SAMPLE_NODE, "caption": None}
        details = build_details(node, "https://www.threads.com/@guilfoilpr/post/DJDNCztRGb1")
        assert details["caption"] is None
        assert details["hashtags"] == []
        assert details["shopee_links"] == []

    def test_ดึงลิงก์_shopee_จากคอมเมนต์ได้ด้วยไม่ใช่แค่แคปชั่น(self):
        # จำลองว่า fetch_node() แนบ _reply_captions ไว้แล้ว (ดู threads_extractor.fetch_node)
        node = {**SAMPLE_NODE, "caption": None, "_reply_captions": ["ลิงก์สินค้า shp.ee/from-comment"]}
        details = build_details(node, "https://www.threads.com/@guilfoilpr/post/DJDNCztRGb1")
        assert details["caption"] is None, "คอมเมนต์ไม่ควรถูกเอาไปแสดงเป็นแคปชั่นของโพสต์"
        assert details["shopee_links"] == ["https://shp.ee/from-comment"]
