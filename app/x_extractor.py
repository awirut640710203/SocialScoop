"""เติมส่วนที่ yt-dlp ขาดไปสำหรับ X (Twitter): URL ของรูปภาพ

yt-dlp ดึงข้อมูลโพสต์ X ได้ดีอยู่แล้ว (แคปชั่น ยอดไลก์ วิดีโอ) แต่ถ้าโพสต์นั้นมีแต่
รูปภาพ มันจะคืน formats ว่างและ thumbnail เป็น None — คือไม่มีอะไรให้ดาวน์โหลดเลย
(ยืนยันแล้วกับ x.com/NASAHubble/status/2032819034232619122)

โมดูลนี้จึงไปถาม syndication API ที่ X เปิดไว้ให้เว็บอื่นฝังโพสต์ (embed) แทน
เป็น endpoint สาธารณะ ไม่ต้องล็อกอิน ไม่ต้องใช้คุกกี้ ตอบกลับเป็น JSON ก้อนเดียว
ใช้เวลาไม่ถึงครึ่งวินาที — ถูกกว่าเปิดเบราว์เซอร์อย่างที่ทำกับ Threads มาก

ทุกฟังก์ชันในนี้ออกแบบให้ "ล้มแล้วเงียบ" (คืน None/ลิสต์ว่าง) เพราะเป็นส่วนเสริม
ถ้า API นี้ล่มหรือถูกบล็อก ผู้ใช้ยังต้องได้ข้อมูลโพสต์จาก yt-dlp ตามปกติ
แค่ปุ่มดาวน์โหลดรูปจะไม่ขึ้นเท่านั้น
"""

import re

import requests

# รองรับทั้ง x.com และ twitter.com รวม subdomain www/mobile/m ให้ตรงกับที่ yt-dlp รับ
_TWEET_URL_RE = re.compile(
    r"^https?://(?:(?:www|m|mobile)\.)?(?:x|twitter)\.com/"
    r"(?:i/web/status|statuses|[^/]+/status)/(?P<id>\d+)",
    re.IGNORECASE,
)

_SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result"

# X ตรวจ User-Agent: ถ้าไม่ส่งหรือส่งเป็น python-requests จะโดนปฏิเสธ
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_TIMEOUT_SECONDS = 10


def tweet_id(url: str) -> str | None:
    """ดึงเลข id ของโพสต์จาก URL คืน None ถ้าไม่ใช่ลิงก์โพสต์ X

    ลิงก์โปรไฟล์ (x.com/NASA) หรือหน้าอื่นจะคืน None เพราะไม่มีโพสต์ให้ดึง
    """
    if not url:
        return None
    match = _TWEET_URL_RE.match(url.strip())
    return match.group("id") if match else None


def _upgrade_quality(image_url: str) -> str:
    """ขอไฟล์ต้นฉบับแทนรูปย่อที่ API คืนมา

    URL ที่ได้จาก API เป็นรูปขนาดกลาง (~450KB) แต่เติม name=orig แล้วได้ไฟล์เต็ม
    (~2.5MB จากการวัดจริง) ซึ่งตรงกับหลักการของทั้งแอปคือเอาคุณภาพสูงสุดที่โพสต์นั้นมี
    """
    return image_url + ("&" if "?" in image_url else "?") + "format=jpg&name=orig"


def photo_urls(url: str) -> list[str]:
    """คืน URL รูปภาพทั้งหมดของโพสต์ (คุณภาพต้นฉบับ) เรียงตามลำดับในโพสต์

    คืนลิสต์ว่างถ้าโพสต์ไม่มีรูป ดึงไม่สำเร็จ หรือไม่ใช่ลิงก์ X
    """
    post_id = tweet_id(url)
    if not post_id:
        return []

    try:
        response = requests.get(
            _SYNDICATION_URL,
            params={"id": post_id, "token": "a", "lang": "en"},
            headers=_HEADERS,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return []

    if not isinstance(data, dict):
        return []

    # mediaDetails รวมทั้งรูปและวิดีโอไว้ด้วยกัน กรองเอาเฉพาะ type == "photo"
    # (โพสต์ที่มีทั้งวิดีโอและรูปปนกันก็เจอได้จริง — วิดีโอปล่อยให้ yt-dlp จัดการไป)
    found: list[str] = []
    for media in data.get("mediaDetails") or []:
        if not isinstance(media, dict) or media.get("type") != "photo":
            continue
        image_url = media.get("media_url_https")
        if not image_url:
            continue
        # ต้องแปลงคุณภาพก่อนแล้วค่อยเช็กซ้ำ ไม่งั้นเทียบ URL ดิบกับ URL ที่แปลงแล้ว
        # ซึ่งไม่มีทางตรงกันเลย = กันซ้ำไม่ได้จริง
        upgraded = _upgrade_quality(image_url)
        if upgraded not in found:
            found.append(upgraded)
    return found


def best_photo_url(url: str) -> str | None:
    """รูปแรกของโพสต์ (คุณภาพต้นฉบับ) หรือ None ถ้าไม่มี

    โพสต์ที่มีหลายรูปจะได้แค่รูปแรก เพราะทั้งแอปออกแบบให้ดาวน์โหลดครั้งละ 1 ไฟล์
    """
    urls = photo_urls(url)
    return urls[0] if urls else None
