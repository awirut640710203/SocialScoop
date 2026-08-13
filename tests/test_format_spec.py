"""กันไม่ให้บั๊ก "เลือกคุณภาพต่ำสุดในคลิปแนวตั้ง" กลับมาอีก

บั๊กเดิม: FORMAT_SPEC เคยเป็น "bv*[height<=1080]+ba/b[height<=1080]/best"
คลิป TikTok/Reels/Threads เป็นแนวตั้ง ไฟล์ 1080p ตัวจริงคือ 1080x1920
ซึ่งความสูง 1920 > 1080 จึงถูกกรองทิ้ง เหลือแต่ 576x1024 (540p) ที่แย่ที่สุด
"""

import yt_dlp

from app.downloader import FORMAT_SPEC

# จำลอง format ที่ TikTok ส่งมาจริง (ดึงมาจากคลิปจริงตอนพัฒนา)
VERTICAL_FORMATS = [
    {
        "format_id": "540p",
        "url": "https://example.invalid/540.mp4",
        "ext": "mp4",
        "width": 576,
        "height": 1024,
        "vcodec": "h264",
        "acodec": "aac",
        "tbr": 622.8,
    },
    {
        "format_id": "720p",
        "url": "https://example.invalid/720.mp4",
        "ext": "mp4",
        "width": 720,
        "height": 1280,
        "vcodec": "h264",
        "acodec": "aac",
        "tbr": 1835.1,
    },
    {
        "format_id": "1080p",
        "url": "https://example.invalid/1080.mp4",
        "ext": "mp4",
        "width": 1080,
        "height": 1920,
        "vcodec": "h264",
        "acodec": "aac",
        "tbr": 1201.8,
    },
]


def _select(format_spec: str, formats: list[dict]) -> dict:
    """ให้ yt-dlp เลือก format ตาม spec โดยไม่ต่อเน็ต"""
    ydl = yt_dlp.YoutubeDL({"format": format_spec, "quiet": True, "simulate": True})
    selector = ydl.build_format_selector(format_spec)
    ctx = {
        "formats": formats,
        "incomplete_formats": {},
    }
    return list(selector(ctx))[0]


def test_เลือก_1080p_ในคลิปแนวตั้ง():
    chosen = _select(FORMAT_SPEC, VERTICAL_FORMATS)
    assert chosen["format_id"] == "1080p", (
        f"ต้องเลือกไฟล์คุณภาพสูงสุด แต่ได้ {chosen['format_id']} — "
        "ตรวจสอบว่ามีใครใส่ height<=1080 กลับเข้ามาใน FORMAT_SPEC หรือเปล่า"
    )


def test_spec_ต้องไม่มีเงื่อนไข_height():
    # เงื่อนไข height ใด ๆ จะพังกับคลิปแนวตั้งเสมอ
    assert "height" not in FORMAT_SPEC, (
        "FORMAT_SPEC ต้องไม่กรองด้วย height เพราะคลิปแนวตั้งมีความสูงมากกว่าความกว้าง"
    )


def test_spec_เดิมที่มีบั๊กเลือกตัวแย่สุดจริง():
    # ยืนยันว่าบั๊กที่เจอเป็นเรื่องจริง ไม่ใช่เข้าใจผิด
    buggy = "bv*[height<=1080]+ba/b[height<=1080]/best"
    chosen = _select(buggy, VERTICAL_FORMATS)
    assert chosen["format_id"] == "540p"
