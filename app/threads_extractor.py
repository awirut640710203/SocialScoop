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
import queue
import re
import threading
from concurrent.futures import Future
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


def _find_thread_item_lists(obj: Any, results: list) -> None:
    """เดินหาทุก list ที่อยู่ใต้คีย์ "thread_items" — ใช้ทั้งกับ reply จริงของโพสต์นี้
    และโพสต์แนะนำที่ไม่เกี่ยวข้องเลย ("relatedPosts" ในหน้าใช้คีย์ชื่อเดียวกัน) ต้องกรอง
    เอา list ที่ใช่จริงทีหลังด้วยการเทียบ shortcode (ดู find_reply_captions)
    """
    if isinstance(obj, dict):
        items = obj.get("thread_items")
        if isinstance(items, list):
            results.append(items)
        for value in obj.values():
            _find_thread_item_lists(value, results)
    elif isinstance(obj, list):
        for item in obj:
            _find_thread_item_lists(item, results)


def find_reply_captions(html: str, shortcode: str) -> list[str]:
    """ดึงข้อความคอมเมนต์ (reply) ใต้โพสต์นี้ จาก HTML เดิมที่โหลดมาแล้ว — ไม่ต้องขอเพิ่ม

    ผู้โพสต์มักแปะลิงก์สินค้าไว้ที่คอมเมนต์แทนแคปชั่นตรงๆ (หลีกเลี่ยงการที่แพลตฟอร์ม
    ลดการมองเห็นโพสต์ที่มีลิงก์นอกในแคปชั่น) จึงต้องสแกนคอมเมนต์หา Shopee link ด้วย
    """
    all_lists: list = []
    for raw in _JSON_SCRIPT_RE.findall(html):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        _find_thread_item_lists(data, all_lists)

    for items in all_lists:
        codes = {(item or {}).get("post", {}).get("code") for item in items if isinstance(item, dict)}
        if shortcode in codes:
            # เจอ list ที่มีโพสต์นี้อยู่จริง = thread ของโพสต์นี้เอง ไม่ใช่ relatedPosts ที่ไม่เกี่ยว
            captions = []
            for item in items:
                text = _caption_text((item or {}).get("post") or {})
                if text:
                    captions.append(text)
            return captions

    return []


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

    # เก็บไว้ตอน fetch_node() (ดูที่นั่น) — ลิงก์สินค้ามักถูกแปะไว้ที่คอมเมนต์แทนแคปชั่น
    reply_captions = node.get("_reply_captions") or []
    link_search_text = caption + "\n" + "\n".join(reply_captions)

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
        "shopee_links": find_shopee_links(link_search_text),
        "stats": {
            "like": format_count(node.get("like_count")),
            "comment": format_count(reply_info.get("direct_reply_count")),
            "view": None,
        },
        "resolution": None,
        "media_type": media_type(node),
    }


def _load_page(browser, url: str) -> tuple[str, str]:
    """เปิดหน้าใน browser ที่ให้มา แล้วคืน (html, final_url)"""
    page = browser.new_page(user_agent=USER_AGENT)
    try:
        # เราอ่านแค่ HTML/JSON ที่ฝังมากับหน้า ไม่เคยต้องเห็นภาพจริงเลย —
        # บล็อกรูป/ฟอนต์/CSS/วิดีโอทิ้งไปตั้งแต่ระดับ network request ประหยัดทั้ง
        # เวลาโหลดและ CPU ตอน decode/render ซึ่งมีผลมากเป็นพิเศษบน container ที่
        # จำกัด CPU อย่าง Render free tier
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
        page.close()


class _BrowserWorker:
    """เธรดเดียวที่เป็นเจ้าของ Chromium และเปิดค้างไว้ใช้ซ้ำข้ามคำขอ

    ทำไมต้องมีเธรดเฉพาะ: Playwright แบบ sync ผูกอ็อบเจกต์ไว้กับเธรดที่สร้างมันเท่านั้น
    แต่ FastAPI รัน endpoint แบบ sync ใน threadpool ซึ่งสลับเธรดไปเรื่อยทุกคำขอ
    จึงเอา browser ไปแชร์ตรงๆ ข้ามเธรดไม่ได้ ต้องให้เธรดนี้เธรดเดียวเป็นเจ้าของ
    แล้วเธรดอื่นส่งงานเข้าคิวมาแทน

    ทำไมต้องเปิดค้าง: วัดจริงแล้วการเปิด-ปิด Chromium ใหม่ทุกครั้งกินเวลาเปล่า ~1.8s
    บนเครื่อง dev และ ~6s บน Render (CPU ถูกจำกัด) ต่อหนึ่งคำขอ ทั้งที่ไม่เกี่ยวกับ
    การโหลดหน้าเว็บจริงเลย

    ผลข้างเคียงที่ยอมรับ: คำขอ Threads จะถูกทำทีละอันตามคิว ไม่ขนานกัน — ซึ่งไม่เสียหาย
    เพราะ Render free tier มี CPU เดียวอยู่แล้ว รันขนานก็ไม่ได้เร็วขึ้นจริง
    """

    # ปิด browser ทิ้งถ้าไม่มีงานเข้ามานานเท่านี้ เพื่อคืน RAM ให้ระบบ — สำคัญมากบน
    # Render free tier ที่มี RAM แค่ 512MB และ Chromium ที่เปิดค้างกินไปร่วม 100-150MB
    IDLE_CLOSE_SECONDS = 120

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="threads-browser", daemon=True
                )
                self._thread.start()

    def _run(self) -> None:
        with sync_playwright() as p:
            browser = None
            try:
                while True:
                    try:
                        job = self._queue.get(timeout=self.IDLE_CLOSE_SECONDS)
                    except queue.Empty:
                        browser = _close_quietly(browser)
                        continue

                    if job is None:  # สัญญาณให้ปิดเธรด (ใช้ในเทสต์)
                        break

                    url, future = job
                    if not future.set_running_or_notify_cancel():
                        continue
                    try:
                        # --no-sandbox จำเป็นตอนรันเป็น non-root ใน container (Render ฯลฯ)
                        # เพราะ sandbox ปกติของ Chromium ต้องการสิทธิ์ user-namespace ที่
                        # container ส่วนใหญ่ปิดไว้ — ไม่มี flag นี้ Chromium จะ crash ทันที
                        if browser is None or not browser.is_connected():
                            browser = p.chromium.launch(
                                headless=True,
                                args=["--no-sandbox", "--disable-setuid-sandbox"],
                            )
                        future.set_result(_load_page(browser, url))
                    except BaseException as exc:  # noqa: BLE001
                        # browser อาจพังไปแล้ว (ถูก OOM killer เก็บ ฯลฯ) ทิ้งไปเลยให้
                        # คำขอถัดไปเปิดใหม่ ดีกว่าใช้ตัวที่พังแล้วค้างไปเรื่อยๆ
                        browser = _close_quietly(browser)
                        future.set_exception(exc)
            finally:
                _close_quietly(browser)

    def fetch(self, url: str) -> tuple[str, str]:
        self._ensure_thread()
        future: Future = Future()
        self._queue.put((url, future))
        return future.result()

    def shutdown(self) -> None:
        """ปิดเธรดและ browser — ใช้ในเทสต์ให้แน่ใจว่าไม่มีของค้างข้ามเทสต์"""
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread and thread.is_alive():
            self._queue.put(None)
            thread.join(timeout=10)


def _close_quietly(browser):
    """ปิด browser โดยไม่ให้ error ตอนปิดทำให้ทั้งเธรดล้ม — คืน None เสมอ"""
    if browser is not None:
        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass
    return None


_worker = _BrowserWorker()


def shutdown_browser() -> None:
    """ปิด Chromium ที่เปิดค้างไว้ (ใช้ในเทสต์/ตอนปิดแอป)"""
    _worker.shutdown()


def fetch_page_html(url: str) -> tuple[str, str]:
    """คืน (html, final_url) — final_url คือ URL หลัง redirect ถ้ามี

    ลิงก์แชร์แบบ threads.com/share/xxxxx/ ไม่มี /post/ ในตัวเอง แต่พาไปที่โพสต์จริง
    (.../@user/post/รหัส) ผ่าน redirect ของเบราว์เซอร์ — ต้องอ่าน shortcode จาก URL
    หลัง redirect เท่านั้น อ่านจาก url ที่ผู้ใช้วางมาตรงๆ ไม่ได้เสมอไป
    """
    try:
        return _worker.fetch(url)
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
    node = parse_post_node(html, shortcode)
    # แนบคอมเมนต์ไว้ในตัว node เลย (คีย์ขึ้นต้น _ = ใช้ภายในเท่านั้น ไม่ใช่ข้อมูลของโพสต์
    # จริง) เพื่อให้ build_details() เอาไปสแกนหา Shopee link ต่อได้โดยไม่ต้อง parse
    # หน้าเว็บซ้ำอีกรอบ — ข้อมูลนี้อยู่ใน html เดิมที่โหลดมาแล้วอยู่แล้ว ไม่มีต้นทุนเพิ่ม
    node["_reply_captions"] = find_reply_captions(html, shortcode)
    return node
