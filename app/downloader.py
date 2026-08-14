"""ดึงข้อมูลและดาวน์โหลดวิดีโอจาก TikTok / Instagram / Threads ด้วย yt-dlp

แยกเป็นสองจังหวะ:
  1. fetch_metadata()  — ไม่โหลดไฟล์ ใช้เวลาไม่กี่วินาที เอาไปโชว์การ์ดรายละเอียดก่อน
  2. download_video()  — โหลดไฟล์จริง เรียกเมื่อผู้ใช้กดปุ่มดาวน์โหลดเท่านั้น
"""

import os
import threading
import time
from pathlib import Path

import requests
import yt_dlp

from . import threads_extractor
from .extract import build_details, detect_platform

DOWNLOAD_DIR = Path("downloads")

# แคชผลลัพธ์การดึงข้อมูล (yt-dlp info dict หรือ Threads media node) ไว้ชั่วคราว
# คีย์ด้วย url ตรงๆ — ผู้ใช้งานจริงมักกด "ดึงข้อมูล" (แสดงการ์ดพรีวิว) แล้วค่อยกด
# "ดาวน์โหลด" ทีหลังไม่กี่วินาที ถ้าไม่แคชไว้ ทั้งสองขั้นตอนจะต้องยิงไปหา TikTok/
# Instagram/Threads แยกกันคนละรอบ ทำให้ช้าลงเท่าตัวและเพิ่มโอกาสโดน anti-bot บล็อก
# โดยไม่จำเป็น (ยิ่งยิงถี่ยิ่งเสี่ยง) TTL สั้นๆ พอ เพราะ URL ของไฟล์วิดีโอที่เซ็นชื่อไว้
# (CDN signed URL) มีอายุเป็นชั่วโมง ไม่ใช่นาที จึงไม่มีความเสี่ยงเรื่องลิงก์หมดอายุ
_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _cache_get(url: str) -> dict | None:
    with _cache_lock:
        entry = _cache.get(url)
        if not entry:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del _cache[url]
            return None
        return value


def _cache_set(url: str, value: dict) -> None:
    with _cache_lock:
        now = time.monotonic()
        # เก็บกวาดของหมดอายุทุกครั้งที่เขียน กันแคชโตไม่มีที่สิ้นสุดโดยไม่ต้องมี background thread
        expired = [k for k, (exp, _) in _cache.items() if exp < now]
        for k in expired:
            del _cache[k]
        _cache[url] = (now + _CACHE_TTL_SECONDS, value)


# เบราว์เซอร์ที่ yt-dlp ดึงคุกกี้ได้ — ตั้งผ่าน .env เช่น SOCIALSCOOP_COOKIES_BROWSER=chrome
SUPPORTED_COOKIE_BROWSERS = {
    "brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale",
}

# คุณภาพสูงสุดเท่าที่โพสต์นั้นมี — ตายตัว ไม่มีตัวเลือกให้ผู้ใช้เลือก
#
# หมายเหตุสำคัญ (อย่าเผลอใส่ height<=1080 กลับเข้ามา):
# คลิปจาก TikTok/Reels/Threads เป็นแนวตั้งเกือบทั้งหมด ไฟล์ 1080p ตัวจริงมีขนาด
# 1080x1920 ซึ่ง "ความสูง" คือ 1920 ไม่ใช่ 1080 การกรอง height<=1080 จึงตัด
# ไฟล์คุณภาพสูงสุดทิ้ง แล้วไปเลือก 576x1024 (540p) ซึ่งแย่ที่สุดแทน
FORMAT_SPEC = "bv*+ba/b"

_BASE_OPTS = {
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
}


def cookie_browser() -> str | None:
    """เบราว์เซอร์ที่จะดึงคุกกี้มาใช้ อ่านจาก SOCIALSCOOP_COOKIES_BROWSER

    TikTok และ Instagram ปฏิเสธคำขอที่ไม่มีคุกกี้บ่อยมาก การส่งคุกกี้จากเบราว์เซอร์
    ที่เข้าสู่ระบบไว้แล้วช่วยให้ดึงข้อมูลผ่านได้ในกรณีที่ถูกปฏิเสธ
    """
    name = os.environ.get("SOCIALSCOOP_COOKIES_BROWSER", "").strip().lower()
    return name if name in SUPPORTED_COOKIE_BROWSERS else None


def cookie_file() -> Path | None:
    """ไฟล์คุกกี้รูปแบบ Netscape อ่านจาก SOCIALSCOOP_COOKIES_FILE

    วิธีนี้เชื่อถือได้กว่าการดึงคุกกี้จากเบราว์เซอร์โดยตรงบน Windows
    เพราะ Chrome/Edge รุ่นใหม่เข้ารหัสคุกกี้ด้วย App-Bound Encryption
    ซึ่ง yt-dlp ถอดรหัสไม่ได้ (DPAPI error)
    """
    raw = os.environ.get("SOCIALSCOOP_COOKIES_FILE", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def _build_opts(extra: dict | None = None) -> dict:
    opts = {**_BASE_OPTS, **(extra or {})}

    # ไฟล์คุกกี้มาก่อนเสมอ เพราะเสถียรกว่าการอ่านจากเบราว์เซอร์
    path = cookie_file()
    if path:
        opts["cookiefile"] = str(path)
        return opts

    browser = cookie_browser()
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    return opts


class DownloadError(RuntimeError):
    """ดึงข้อมูล/ดาวน์โหลดไม่สำเร็จ พร้อมข้อความที่แสดงให้ผู้ใช้อ่านได้"""


def _friendly_error(exc: Exception) -> str:
    """แปลง error ของ yt-dlp เป็นข้อความไทยที่บอกวิธีแก้ต่อได้"""
    text = str(exc)
    lowered = text.lower()

    # TikTok ตอบหน้าเปล่า/ปฏิเสธ challenge ให้คำขอที่ดูเหมือนบอท — เกิดบ่อยเมื่อยิงถี่,
    # ไม่มีคุกกี้, หรือยิงจาก IP ของผู้ให้บริการคลาวด์ (เช่น Render) ที่ TikTok ขึ้นบัญชีดำไว้
    if (
        "universal data" in lowered
        or "rehydration" in lowered
        or "unexpected response" in lowered
    ):
        if cookie_browser():
            return (
                "TikTok ปฏิเสธคำขอนี้ชั่วคราว — รอสัก 1-2 นาทีแล้วลองอีกครั้ง "
                "หรือเปิดเบราว์เซอร์เข้า tiktok.com สักครั้งเพื่อรีเฟรชคุกกี้"
            )
        return (
            "TikTok ปฏิเสธคำขอที่ไม่มีคุกกี้ — ตั้งค่า SOCIALSCOOP_COOKIES_BROWSER=chrome "
            "ในไฟล์ .env (ต้องเปิดเบราว์เซอร์เข้า tiktok.com ไว้ก่อน) แล้วลองใหม่"
        )
    # Chrome/Edge รุ่นใหม่บน Windows เข้ารหัสคุกกี้แบบที่ yt-dlp ถอดไม่ได้
    if "dpapi" in lowered or ("decrypt" in lowered and "cookie" in lowered):
        return (
            "อ่านคุกกี้จาก Chrome/Edge บน Windows ไม่ได้ (App-Bound Encryption) — "
            "ให้ export ไฟล์ cookies.txt จากส่วนขยายเบราว์เซอร์ แล้วตั้ง "
            "SOCIALSCOOP_COOKIES_FILE=cookies.txt ใน .env แทน "
            "(หรือใช้ Firefox ซึ่งอ่านคุกกี้ได้ปกติ)"
        )
    if "could not copy" in lowered and "cookie" in lowered:
        return (
            "อ่านคุกกี้จากเบราว์เซอร์ไม่ได้ — ปิดเบราว์เซอร์ให้สนิทแล้วลองใหม่ "
            "หรือลบค่า SOCIALSCOOP_COOKIES_BROWSER ออกจาก .env"
        )
    if "unsupported url" in lowered:
        return "ลิงก์นี้ยังไม่รองรับ — ลองตรวจสอบว่าเป็นลิงก์โพสต์โดยตรงหรือไม่"
    if "private" in lowered or "login" in lowered or "sign in" in lowered:
        return "โพสต์นี้เป็นแบบส่วนตัวหรือต้องเข้าสู่ระบบก่อน — รองรับเฉพาะโพสต์สาธารณะเท่านั้น"
    if "not exist" in lowered or "404" in lowered or "unavailable" in lowered:
        return "ไม่พบโพสต์นี้ — อาจถูกลบไปแล้วหรือลิงก์ผิด"
    if "rate" in lowered and "limit" in lowered:
        return "แพลตฟอร์มจำกัดจำนวนคำขอชั่วคราว — รอสักครู่แล้วลองใหม่"
    if "timed out" in lowered or "timeout" in lowered:
        return "เชื่อมต่อไม่สำเร็จ (หมดเวลา) — ตรวจสอบอินเทอร์เน็ตแล้วลองใหม่"
    return f"ดึงข้อมูลไม่สำเร็จ: {text.strip()[:200]}"


def fetch_metadata(url: str) -> dict:
    """ดึงรายละเอียดโพสต์โดยไม่ดาวน์โหลดไฟล์วิดีโอ

    Returns: dict ตามโครงสร้างของ build_details()
    Raises: DownloadError ถ้าดึงไม่สำเร็จ
    """
    # Threads ไม่มี extractor ใน yt-dlp เลย ต้องใช้ตัวดึงข้อมูลของเราเอง (ดู threads_extractor.py)
    if detect_platform(url) == "threads":
        try:
            node = threads_extractor.fetch_node(url)
        except threads_extractor.ThreadsExtractError as exc:
            raise DownloadError(str(exc)) from exc
        _cache_set(url, {"kind": "threads", "node": node})
        return threads_extractor.build_details(node, url)

    opts = _build_opts({"skip_download": True})

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(_friendly_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — กันทุกกรณีไม่ให้เซิร์ฟเวอร์ล้ม
        raise DownloadError(_friendly_error(exc)) from exc

    if info is None:
        raise DownloadError("ไม่ได้รับข้อมูลจากลิงก์นี้")

    # ลิงก์ที่เป็นเพลย์ลิสต์/หลายคลิป ให้เอาคลิปแรก
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise DownloadError("ลิงก์นี้ไม่มีวิดีโออยู่ข้างใน")
        info = entries[0]

    _cache_set(url, {"kind": "ytdlp", "info": info})
    return build_details(info)


def _download_threads_media(url: str, output_dir: Path) -> dict:
    cached = _cache_get(url)
    if cached and cached["kind"] == "threads":
        node = cached["node"]
    else:
        try:
            node = threads_extractor.fetch_node(url)
        except threads_extractor.ThreadsExtractError as exc:
            raise DownloadError(str(exc)) from exc

    details = threads_extractor.build_details(node, url)
    video_url = threads_extractor.best_video_url(node)
    # โพสต์รูปภาพล้วน (ไม่มีวิดีโอ) ก็ต้องดาวน์โหลดได้ — ใช้รูปคุณภาพดีที่สุดแทน
    image_url = None if video_url else threads_extractor.best_thumbnail_url(node)
    media_url = video_url or image_url

    if not media_url:
        raise DownloadError("โพสต์นี้ไม่มีวิดีโอหรือรูปภาพให้ดาวน์โหลด")

    # ใช้ code จาก node ที่ parse มาแล้วโดยตรง แทนการแกะ shortcode จาก url ที่ผู้ใช้วางมา
    # เพราะลิงก์แชร์ (threads.com/share/xxxxx/) ไม่มี /post/ ในตัวเอง ต้องรอ redirect
    # ก่อนถึงจะรู้ shortcode จริง — node['code'] คือค่าที่ resolve แล้วเสมอ
    ext = "mp4" if video_url else "jpg"
    media_path = output_dir / f"{node['code']}.{ext}"

    try:
        with requests.get(media_url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(media_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
    except requests.RequestException as exc:
        media_path.unlink(missing_ok=True)
        raise DownloadError(f"โหลดไฟล์{'วิดีโอ' if video_url else 'รูปภาพ'}ไม่สำเร็จ: {exc}") from exc

    return {
        "video_path": str(media_path),
        "filename": media_path.name,
        "details": details,
    }


def download_video(url: str, output_dir: Path | str = DOWNLOAD_DIR) -> dict:
    """ดาวน์โหลดวิดีโอคุณภาพสูงสุดเท่าที่โพสต์นั้นมี พร้อมไฟล์คำบรรยายและข้อมูลกำกับ

    Returns: {"video_path": str, "filename": str, "details": dict}
    Raises: DownloadError ถ้าดาวน์โหลดไม่สำเร็จ
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if detect_platform(url) == "threads":
        return _download_threads_media(url, output_dir)

    opts = _build_opts({
        "format": FORMAT_SPEC,
        "merge_output_format": "mp4",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "writedescription": True,
        "writeinfojson": True,
        "restrictfilenames": True,
    })

    # ถ้าเพิ่งดึงรายละเอียดโพสต์นี้ไปหมาดๆ (ผู้ใช้กด "ดึงข้อมูล" ก่อนแล้วค่อยกด
    # "ดาวน์โหลด") ใช้ info ที่มีอยู่แล้วแทนการดึงหน้าเว็บซ้ำอีกรอบ — process_ie_result
    # จะข้ามขั้นตอนขอหน้าเว็บ+แก้ anti-bot challenge ไปเลย ยิงตรงไปที่ URL ไฟล์วิดีโอ
    # ที่ resolve ไว้แล้ว เร็วขึ้นมาก และลดจำนวนครั้งที่โดน anti-bot ตรวจจับด้วย
    # (ทดสอบแล้วว่าไฟล์ที่ได้ตรงกับดาวน์โหลดสดทุกกรณี — ดูรายละเอียดใน commit message)
    cached = _cache_get(url)
    cached_info = cached["info"] if cached and cached["kind"] == "ytdlp" else None

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            if cached_info is not None:
                info = ydl.process_ie_result(cached_info, download=True)
            else:
                info = ydl.extract_info(url, download=True)
            if info.get("_type") == "playlist":
                entries = [e for e in (info.get("entries") or []) if e]
                if not entries:
                    raise DownloadError("ลิงก์นี้ไม่มีวิดีโออยู่ข้างใน")
                info = entries[0]
            video_path = Path(ydl.prepare_filename(info))
    except DownloadError:
        raise
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(_friendly_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise DownloadError(_friendly_error(exc)) from exc

    # yt-dlp อาจ merge เป็น .mp4 ทำให้ชื่อไฟล์ต่างจากที่ prepare_filename บอก
    if not video_path.exists():
        merged = video_path.with_suffix(".mp4")
        if merged.exists():
            video_path = merged
        else:
            raise DownloadError("ดาวน์โหลดเสร็จแต่หาไฟล์วิดีโอไม่เจอ")

    return {
        "video_path": str(video_path),
        "filename": video_path.name,
        "details": build_details(info),
    }
