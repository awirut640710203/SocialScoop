"""แยกข้อมูลออกจากข้อความแคปชั่นและ URL

ทุกฟังก์ชันในไฟล์นี้เป็น pure function ไม่แตะเน็ตเวิร์กและไม่แตะดิสก์
จึงทดสอบได้ทั้งหมดโดยไม่ต้องต่ออินเทอร์เน็ต
"""

import re
from urllib.parse import urlparse

# ช่วง Unicode ของภาษาไทยทั้งบล็อก U+0E00–U+0E7F (รวมสระและวรรณยุกต์)
# ระบุเป็น escape แทนตัวอักษรจริง เพื่อไม่ให้ตัวไฟล์ถูกแก้ encoding แล้วพัง
_THAI = r"฀-๿"

HASHTAG_RE = re.compile(rf"#([\w{_THAI}]+)", re.UNICODE)

# โดเมน Shopee ที่พบในแคปชั่น รวมลิงก์ย่อ shp.ee และ subdomain อย่าง s.shopee.co.th
_SHOPEE_HOST = r"(?:[\w-]+\.)*shopee\.(?:co\.th|com|com\.my|ph|sg|vn|tw|co\.id|com\.br)|shp\.ee"
SHOPEE_RE = re.compile(
    rf"(?:https?://)?(?:{_SHOPEE_HOST})/[^\s<>\"']+",
    re.IGNORECASE,
)

# เครื่องหมายวรรคตอนที่มักติดท้ายลิงก์เวลาเขียนในประโยค เช่น "...ที่ shp.ee/abc123)"
_TRAILING_PUNCT = ".,;:!?)]}>’”"

PLATFORM_LABELS = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "threads": "Threads",
    "x": "X",
}


def detect_platform(url: str) -> str | None:
    """คืนชื่อแพลตฟอร์มจาก URL หรือ None ถ้าไม่รู้จัก

    รองรับ URL ที่ไม่มี scheme (เช่น "tiktok.com/@user/video/123") ด้วย
    """
    if not url or not url.strip():
        return None

    raw = url.strip()
    if "//" not in raw:
        raw = "https://" + raw

    try:
        host = (urlparse(raw).hostname or "").lower()
    except ValueError:
        return None

    if not host:
        return None

    host = host.removeprefix("www.")

    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "tiktok"
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "instagram"
    if host in ("threads.net", "threads.com") or host.endswith((".threads.net", ".threads.com")):
        return "threads"
    # ชื่อเดิม twitter.com ยังใช้ได้อยู่และคนยังคัดลอกลิงก์แบบนั้นมาเยอะ ต้องรับทั้งสองชื่อ
    if host in ("x.com", "twitter.com") or host.endswith((".x.com", ".twitter.com")):
        return "x"
    return None


# yt-dlp ยังใช้ชื่อ extractor เดิมว่า "Twitter" อยู่ แต่แพลตฟอร์มเปลี่ยนชื่อเป็น X แล้ว
# ถ้าโชว์ตามที่ yt-dlp บอก การ์ดผลลัพธ์จะเขียน "Twitter" ขณะที่ chip ด้านบนเขียน "X"
_EXTRACTOR_DISPLAY_NAMES = {"twitter": "X"}


def display_platform(extractor_key: str | None) -> str | None:
    """แปลงชื่อ extractor ของ yt-dlp เป็นชื่อที่ผู้ใช้คุ้นเคย"""
    if not extractor_key:
        return None
    return _EXTRACTOR_DISPLAY_NAMES.get(extractor_key.lower(), extractor_key)


def parse_hashtags(caption: str) -> list[str]:
    """ดึงแฮชแท็กจากแคปชั่น คืนรายการที่ไม่ซ้ำและเรียงตามลำดับที่พบ

    รองรับแฮชแท็กภาษาไทย เช่น #รีวิวของจริง
    """
    if not caption:
        return []

    seen: list[str] = []
    for tag in HASHTAG_RE.findall(caption):
        formatted = "#" + tag
        if formatted not in seen:
            seen.append(formatted)
    return seen


def _clean_link(link: str) -> str:
    """ตัดเครื่องหมายวรรคตอนท้ายลิงก์ และเติม https:// ถ้าไม่มี scheme"""
    link = link.rstrip(_TRAILING_PUNCT)
    if not link.lower().startswith(("http://", "https://")):
        link = "https://" + link
    return link


def find_shopee_links(text: str) -> list[str]:
    """หาลิงก์ Shopee ทั้งหมดในข้อความ คืนรายการที่ไม่ซ้ำและเรียงตามลำดับที่พบ

    ใช้สำหรับ affiliate sourcing: ผู้ใช้จะคัดลอกลิงก์นี้ไปหาสินค้าตัวจริงบน Shopee
    แล้วสร้างลิงก์ affiliate ของตัวเองต่อเอง — เครื่องมือนี้ไม่ได้สร้างลิงก์ aff ให้
    """
    if not text:
        return []

    found: list[str] = []
    for match in SHOPEE_RE.findall(text):
        link = _clean_link(match)
        if link not in found:
            found.append(link)
    return found


def format_count(value: int | None) -> str | None:
    """แปลงตัวเลขยอดเป็นข้อความสั้น เช่น 84200 -> "84.2K"

    คืน None ถ้าไม่มีค่า เพื่อให้ UI ซ่อนแถวนั้นไปเลย ไม่ใช่โชว์ 0 หลอกผู้ใช้
    """
    if value is None:
        return None
    if value < 1_000:
        return str(value)
    if value < 1_000_000:
        return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
    return f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


def media_type(info: dict) -> str | None:
    """"video" ถ้ามีวิดีโอให้โหลด, "image" ถ้ามีแต่รูป (เช่น Instagram โพสต์รูปภาพล้วน),
    None ถ้าไม่มีสื่อให้โหลดเลย — frontend ใช้ค่านี้ตัดสินใจว่าจะโชว์ปุ่ม
    "ดาวน์โหลดวิดีโอ" หรือ "ดาวน์โหลดรูปภาพ" (เหมือนที่ threads_extractor.media_type ทำ)
    """
    if info.get("formats"):
        return "video"
    if info.get("thumbnail"):
        return "image"
    return None


def build_details(info: dict) -> dict:
    """ประกอบข้อมูลดิบจาก yt-dlp ให้เป็นโครงสร้างที่หน้าเว็บใช้ได้ตรง ๆ

    field ที่ไม่มีค่าจะเป็น None เสมอ เพื่อให้ frontend ซ่อนแถวนั้นแทนการโชว์ค่าปลอม
    """
    caption = info.get("description") or ""
    # TikTok บางคลิปใส่แคปชั่นไว้ใน title แทน description
    if not caption:
        caption = info.get("title") or ""

    # ผู้โพสต์มักแปะลิงก์สินค้าไว้ที่คอมเมนต์ (มักเป็นคอมเมนต์ตัวเอง) แทนแคปชั่นตรงๆ
    # เพราะแพลตฟอร์มมักลดการมองเห็นโพสต์ที่มีลิงก์นอกอยู่ในแคปชั่น — ต้องสแกนคอมเมนต์
    # ด้วย ไม่ใช่แค่แคปชั่น (มีก็ต่อเมื่อเรียกด้วย getcomments: True เท่านั้น
    # TikTok extractor ไม่รองรับคอมเมนต์เลยตอนนี้ ค่านี้จะไม่มีสำหรับ TikTok)
    comment_texts = "\n".join(c.get("text") or "" for c in (info.get("comments") or []))
    link_search_text = caption + "\n" + comment_texts

    return {
        "title": info.get("title") or None,
        "caption": caption or None,
        "uploader": info.get("uploader") or info.get("uploader_id") or None,
        "platform": display_platform(info.get("extractor_key") or info.get("extractor")),
        "webpage_url": info.get("webpage_url") or None,
        "thumbnail": info.get("thumbnail") or None,
        "duration": info.get("duration"),
        "upload_date": info.get("upload_date") or None,
        "hashtags": parse_hashtags(caption),
        "shopee_links": find_shopee_links(link_search_text),
        "stats": {
            "like": format_count(info.get("like_count")),
            "comment": format_count(info.get("comment_count")),
            "view": format_count(info.get("view_count")),
        },
        "resolution": _describe_resolution(info),
        "media_type": media_type(info),
    }


def _short_side(width: int | None, height: int | None) -> int | None:
    """คืนด้านที่สั้นกว่า ซึ่งคือตัวเลขที่คนใช้เรียกคุณภาพ

    คลิปแนวตั้ง 1080x1920 คนเรียกว่า "1080p" ไม่ใช่ "1920p"
    จึงต้องดูด้านสั้น ไม่ใช่ความสูงอย่างเดียว
    """
    if width and height:
        return min(width, height)
    return height or width or None


def _describe_resolution(info: dict) -> str | None:
    """อธิบายความละเอียดที่จะได้ เช่น "1080p" — เป็นแค่ label ไม่ใช่ตัวเลือก"""
    short = _short_side(info.get("width"), info.get("height"))

    if not short:
        # ถ้ายังไม่ได้เลือก format ให้ดูตัวที่ดีที่สุดในรายการ
        candidates = [
            _short_side(f.get("width"), f.get("height"))
            for f in (info.get("formats") or [])
        ]
        candidates = [c for c in candidates if c]
        short = max(candidates) if candidates else None

    return f"{short}p" if short else None
