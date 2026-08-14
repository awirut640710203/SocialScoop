"""ดึงข้อมูล/วิดีโอจากโพสต์ Threads (threads.net / threads.com)

yt-dlp ไม่มี extractor สำหรับ Threads (ยังเป็น feature request ที่ค้างมาหลายปี —
github.com/yt-dlp/yt-dlp/issues/7523, #10133) ตกไปใช้ generic extractor ซึ่งใช้ไม่ได้
เพราะ Threads เป็นหน้าที่ต้องรัน JS ถึงจะได้ข้อมูลโพสต์จริง (fetch ตรงด้วย requests
ได้แต่ app shell เปล่าๆ ไม่มีข้อมูลโพสต์ฝังมาด้วย)

วิธี reverse-engineer GraphQL API ตรงๆ (ตามที่โปรเจกต์อื่นเคยทำ เช่น
github.com/m1guelpf/threads-re) ก็ทดสอบแล้วใช้ไม่ได้แล้ว — Meta เปลี่ยน doc_id/route
เร็วกว่าที่จะ maintain เองไหว และ endpoint ปฏิเสธคำขอที่ไม่ได้มาจากเบราว์เซอร์จริง
(ลองแล้วทั้งใส่ header ครบและ TLS impersonate ก็ยังโดนเด้งกลับเป็นหน้าเปล่า)

ทางที่ใช้ได้จริงตอนนี้คือเปิด headless Chromium จริงด้วย Playwright ให้โหลดหน้าโพสต์
แล้วดึง JSON ของโพสต์ที่ฝังอยู่ใน <script type="application/json"> ออกมา (โครงสร้าง
เหมือน media node ของ Instagram เป๊ะ เพราะ Threads ใช้ backend เดียวกัน)
"""

import json
import re
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .extract import find_shopee_links, format_count, parse_hashtags

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_JSON_SCRIPT_RE = re.compile(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', re.S)
_POST_ID_RE = re.compile(r"/post/([^/?#]+)")


class ThreadsExtractError(RuntimeError):
    """ดึงข้อมูล/วิดีโอจากโพสต์ Threads ไม่สำเร็จ พร้อมข้อความที่แสดงให้ผู้ใช้อ่านได้"""


def shortcode_from_url(url: str) -> str:
    match = _POST_ID_RE.search(url)
    if not match:
        raise ThreadsExtractError("ลิงก์นี้ไม่ใช่ลิงก์โพสต์ Threads เดี่ยว (ต้องมี /post/ ในลิงก์)")
    return match.group(1)


def _find_post_nodes(obj: Any, results: list) -> None:
    """เดินหา dict ที่หน้าตาเหมือน media node ของโพสต์ ในทุก JSON blob ที่ฝังอยู่ในหน้า"""
    if isinstance(obj, dict):
        if "code" in obj and "user" in obj and ("video_versions" in obj or "image_versions2" in obj):
            results.append(obj)
        for value in obj.values():
            _find_post_nodes(value, results)
    elif isinstance(obj, list):
        for item in obj:
            _find_post_nodes(item, results)


def parse_post_node(html: str, shortcode: str) -> dict:
    """หา media node ของโพสต์ที่ตรงกับ shortcode จาก HTML ที่เรนเดอร์แล้ว"""
    candidates: list = []
    for raw in _JSON_SCRIPT_RE.findall(html):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        _find_post_nodes(data, candidates)

    for node in candidates:
        if node.get("code") == shortcode:
            return node
    if candidates:
        # เจอ node อื่นแต่ไม่ตรง shortcode เป๊ะ (เช่นโพสต์ที่ถูก quote/reply ด้วยกัน) — เอาตัวแรกดีกว่าไม่มีเลย
        return candidates[0]

    raise ThreadsExtractError(
        "ไม่พบข้อมูลโพสต์ในหน้าเว็บ — โพสต์อาจถูกลบ เป็นแบบส่วนตัว หรือ Threads เปลี่ยนโครงสร้างหน้าเว็บ"
    )


def _first_media_with(node: dict, key: str) -> dict:
    """โพสต์แบบ carousel (หลายรูป/วิดีโอ) เก็บ media จริงไว้ใน carousel_media แทน node บนสุด"""
    if node.get(key):
        return node
    for item in node.get("carousel_media") or []:
        if item.get(key):
            return item
    return node


def best_video_url(node: dict) -> str | None:
    media = _first_media_with(node, "video_versions")
    versions = media.get("video_versions") or []
    return versions[0]["url"] if versions else None


def best_thumbnail_url(node: dict) -> str | None:
    media = _first_media_with(node, "image_versions2")
    candidates = (media.get("image_versions2") or {}).get("candidates") or []
    return candidates[0]["url"] if candidates else None


def _caption_text(node: dict) -> str:
    caption = node.get("caption")
    if isinstance(caption, dict):
        return caption.get("text") or ""
    if isinstance(caption, str):
        return caption
    return ""


def _upload_date(node: dict) -> str | None:
    taken_at = node.get("taken_at")
    if not isinstance(taken_at, (int, float)):
        return None
    return datetime.fromtimestamp(taken_at, tz=timezone.utc).strftime("%Y%m%d")


def media_type(node: dict) -> str | None:
    """"video" ถ้ามีวิดีโอให้โหลด, "image" ถ้ามีแต่รูป, None ถ้าไม่มีสื่อเลย (โพสต์ข้อความล้วน)

    frontend ใช้ค่านี้ตัดสินใจว่าจะโชว์ปุ่ม "ดาวน์โหลดวิดีโอ" หรือ "ดาวน์โหลดรูปภาพ"
    """
    if best_video_url(node):
        return "video"
    if best_thumbnail_url(node):
        return "image"
    return None


def build_details(node: dict, url: str) -> dict:
    """แปลง media node ให้เป็นโครงสร้างเดียวกับ extract.build_details() ที่ frontend ใช้"""
    caption = _caption_text(node)
    user = node.get("user") or {}
    reply_info = node.get("text_post_app_info") or {}

    return {
        "title": caption or None,
        "caption": caption or None,
        "uploader": user.get("username") or user.get("full_name") or None,
        "platform": "Threads",
        "webpage_url": url,
        "thumbnail": best_thumbnail_url(node),
        "duration": None,
        "upload_date": _upload_date(node),
        "hashtags": parse_hashtags(caption),
        "shopee_links": find_shopee_links(caption),
        "stats": {
            "like": format_count(node.get("like_count")),
            "comment": format_count(reply_info.get("direct_reply_count")),
            "view": None,
        },
        "resolution": None,
        "media_type": media_type(node),
    }


def fetch_page_html(url: str) -> tuple[str, str]:
    """คืน (html, final_url) — final_url คือ URL หลัง redirect ถ้ามี

    ลิงก์แชร์แบบ threads.com/share/xxxxx/ ไม่มี /post/ ในตัวเอง แต่พาไปที่โพสต์จริง
    (.../@user/post/รหัส) ผ่าน redirect ของเบราว์เซอร์ — ต้องอ่าน shortcode จาก URL
    หลัง redirect เท่านั้น อ่านจาก url ที่ผู้ใช้วางมาตรงๆ ไม่ได้เสมอไป
    """
    try:
        with sync_playwright() as p:
            # --no-sandbox จำเป็นตอนรันเป็น non-root ใน container (Render ฯลฯ) เพราะ
            # sandbox ปกติของ Chromium ต้องการสิทธิ์ user-namespace ที่ container ส่วนใหญ่
            # ปิดไว้ — ไม่มี flag นี้ Chromium จะ crash ตั้งแต่ launch ทันทีตอนรันบน Render
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                # เราอ่านแค่ HTML/JSON ที่ฝังมากับหน้า ไม่เคยต้องเห็นภาพจริงเลย —
                # บล็อกรูป/ฟอนต์/CSS/วิดีโอทิ้งไปตั้งแต่ระดับ network request ประหยัดทั้ง
                # เวลาโหลดและ CPU ตอน decode/render ซึ่งมีผลมากเป็นพิเศษบน container ที่
                # จำกัด CPU อย่าง Render free tier (วัดจริง: ลด fetch จาก ~14s เหลือดีขึ้นมาก)
                page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ("image", "stylesheet", "font", "media")
                    else route.continue_(),
                )
                # ข้อมูลโพสต์ (video_versions/caption ฯลฯ) มาจาก server-side render ฝังอยู่ใน
                # HTML ตั้งแต่แรกอยู่แล้ว ไม่ได้โหลดทีหลังด้วย JS จึงไม่ต้องรอ networkidle
                # (ซึ่งรอ tracking/analytics beacon เบื้องหลังที่ไม่เกี่ยวด้วย เสียเวลาเปล่า
                # ~2 วินาทีต่อครั้ง — วัดจริงแล้วก่อนแก้) แค่ domcontentloaded ก็พอ
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(300)
                return page.content(), page.url
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise ThreadsExtractError("โหลดหน้า Threads ไม่ทัน (หมดเวลา) — ลองใหม่อีกครั้ง") from exc
    except PlaywrightError as exc:
        raise ThreadsExtractError(f"เปิดหน้า Threads ไม่สำเร็จ: {exc}") from exc


def fetch_node(url: str) -> dict:
    """ดึง media node ของโพสต์จริงจาก Threads (เปิด Chromium จริง)

    downloader.py เป็นคนเรียกฟังก์ชันนี้โดยตรงแล้วแคชผลลัพธ์ไว้ใช้ซ้ำตอนดาวน์โหลด
    (ดู downloader.py: _cache_*) เพื่อไม่ต้องเปิด Chromium ใหม่ทั้งที่เพิ่งดึงเมื่อกี้นี้เอง
    """
    html, final_url = fetch_page_html(url)
    shortcode = shortcode_from_url(final_url)
    return parse_post_node(html, shortcode)
