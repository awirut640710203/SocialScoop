"""ป้องกันทั้งเว็บด้วยบัญชีเดียว (ชื่อผู้ใช้ + รหัสผ่าน)

จำเป็นเมื่อ deploy ออกอินเทอร์เน็ตจริง เพราะไม่งั้นใครก็ได้ที่รู้ลิงก์จะมาใช้โควตา
ดาวน์โหลดวิดีโอและโควตา AI ฟรีของเราแบบไม่จำกัด

รองรับการเข้าใช้งาน 2 ทาง:
  1. คุกกี้เซสชัน — ล็อกอินผ่านหน้า /login ครั้งเดียวแล้วจำไว้ 1 ปี ไม่ต้องล็อกอินซ้ำ
     ทุกครั้งที่เปิดเว็บ (นี่คือทางหลักสำหรับใช้งานบนมือถือ/ไอแพด)
  2. HTTP Basic Auth — เก็บไว้ให้เครื่องมือบรรทัดคำสั่ง (curl) และการทดสอบยังยิง API
     ตรงได้โดยไม่ต้องผ่านหน้าเว็บ

หมายเหตุความปลอดภัย: ทั้งชื่อผู้ใช้และรหัสผ่านอ่านจาก environment variable เท่านั้น
ห้ามฝังค่าจริงลงในไฟล์นี้เด็ดขาด เพราะ repo นี้เป็น public บน GitHub
"""

import base64
import binascii
import hashlib
import hmac
import os
import secrets
import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

REALM = "SocialScoop"

# ชื่อผู้ใช้ตั้งต้น — ไม่ใช่ความลับ (ความลับอยู่ที่รหัสผ่าน) จึงใส่ค่าเริ่มต้นไว้ได้
# เผื่อลืมตั้ง env var บน Render ระบบก็ยังใช้ชื่อที่ถูกต้อง
DEFAULT_USERNAME = "AUM"

SESSION_COOKIE = "socialscoop_session"
# 1 ปี — ผู้ใช้ต้องการล็อกอินครั้งเดียวจากมือถือ/ไอแพดแล้วไม่ต้องกรอกซ้ำอีก
SESSION_MAX_AGE = 365 * 24 * 60 * 60

# path ที่ยกเว้นไม่ต้องผ่านรหัสผ่าน
#   /healthz — ให้แพลตฟอร์ม deploy (Render) ตรวจสุขภาพเซิร์ฟเวอร์ได้ ถ้าไม่ยกเว้น
#              Render จะเจอ 401 ทุกครั้งแล้วคิดว่าแอปพัง ไม่ยอม mark deploy ว่าสำเร็จ
#              (คืนแค่ {"ok": true} ไม่มีข้อมูลอ่อนไหว)
#   /login   — หน้าล็อกอินเอง ถ้าไม่ยกเว้นจะวนลูป redirect ไม่จบ
UNAUTHENTICATED_PATHS = frozenset({"/healthz", "/login"})


def configured_username() -> str:
    """ชื่อผู้ใช้ที่ยอมรับ อ่านจาก SOCIALSCOOP_USERNAME (ไม่ตั้ง = ใช้ค่าตั้งต้น)"""
    return os.environ.get("SOCIALSCOOP_USERNAME", "").strip() or DEFAULT_USERNAME


def configured_password() -> str | None:
    """รหัสผ่านที่ตั้งไว้ผ่าน SOCIALSCOOP_PASSWORD หรือ None ถ้าไม่ได้ตั้ง

    ไม่ตั้งค่านี้ = ไม่มีการป้องกันเลย (โหมดใช้ในเครื่อง/วงแลนส่วนตัวเท่านั้น)
    """
    pw = os.environ.get("SOCIALSCOOP_PASSWORD", "").strip()
    return pw or None


def session_token() -> str:
    """โทเคนสำหรับคุกกี้เซสชัน — คำนวณจากชื่อผู้ใช้+รหัสผ่านปัจจุบัน

    ผูกค่ากับรหัสผ่านโดยตรง ทำให้ "เปลี่ยนรหัสผ่าน = เตะทุกอุปกรณ์ออกทันที"
    โดยไม่ต้องเก็บรายการเซสชันไว้ที่ไหนเลย (เซิร์ฟเวอร์ไม่มี state) — เหมาะกับ
    Render free tier ที่รีสตาร์ทเครื่องบ่อยและไม่มีที่เก็บข้อมูลถาวร

    ใช้ HMAC ไม่ใช่ hash ตรงๆ เพื่อไม่ให้เดารหัสผ่านย้อนกลับจากค่าคุกกี้ได้
    """
    password = configured_password() or ""
    key = hashlib.sha256(f"{configured_username()}:{password}".encode()).digest()
    return hmac.new(key, b"socialscoop-session-v1", hashlib.sha256).hexdigest()


def credentials_valid(username: str, password: str) -> bool:
    """เทียบชื่อผู้ใช้+รหัสผ่านแบบกัน timing attack

    เข้ารหัสเป็น bytes ก่อนเทียบ เพราะ compare_digest กับ str รองรับเฉพาะ ASCII
    (จะพังถ้ารหัสผ่านมีอักษรไทย)
    """
    expected_password = configured_password()
    if expected_password is None:
        return False
    # เทียบทั้งสองค่าเสมอ ไม่ลัดวงจรตั้งแต่ชื่อผู้ใช้ผิด เพื่อให้เวลาที่ใช้คงที่
    user_ok = secrets.compare_digest(username.encode(), configured_username().encode())
    pass_ok = secrets.compare_digest(password.encode(), expected_password.encode())
    return user_ok and pass_ok


# --- จำกัดจำนวนครั้งที่เดารหัสผ่านผิด ---
#
# จำเป็นเพราะรหัสผ่านอาจเป็นตัวเลขล้วนซึ่งเดาง่ายกว่ารหัสผสม และเว็บเปิดสาธารณะบน
# อินเทอร์เน็ต ถ้าไม่จำกัดจะยิงเดาได้ไม่จำกัดครั้ง เก็บในหน่วยความจำเฉยๆ (หายตอน
# รีสตาร์ท) ซึ่งพอสำหรับแอปผู้ใช้คนเดียว ไม่ต้องพึ่งฐานข้อมูลเพิ่ม
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60
_ATTEMPT_WINDOW = 15 * 60  # ไม่เดาผิดเลยนานเท่านี้ ให้เริ่มนับใหม่
_attempts: dict[str, tuple[int, float]] = {}
_attempts_lock = threading.Lock()


def throttle_retry_after(client_ip: str) -> int:
    """คืนจำนวนวินาทีที่ยังต้องรอ (0 = ลองได้เลย)"""
    with _attempts_lock:
        entry = _attempts.get(client_ip)
        if not entry:
            return 0
        count, last_failure = entry
        if count < _MAX_ATTEMPTS:
            return 0
        remaining = _LOCKOUT_SECONDS - (time.monotonic() - last_failure)
        return max(0, int(remaining) + 1) if remaining > 0 else 0


def record_failed_attempt(client_ip: str) -> None:
    with _attempts_lock:
        now = time.monotonic()
        # เก็บกวาดรายการเก่าไปด้วย กัน dict โตไม่มีที่สิ้นสุดจากการโดนยิงสุ่ม IP
        stale = [ip for ip, (_, ts) in _attempts.items() if now - ts > _ATTEMPT_WINDOW]
        for ip in stale:
            del _attempts[ip]

        count, last_failure = _attempts.get(client_ip, (0, now))
        if now - last_failure > _ATTEMPT_WINDOW:
            count = 0
        # ครบโควตาแล้วเดาผิดซ้ำ ให้เริ่มนับเวลาล็อกใหม่ กันยิงรัวระหว่างโดนล็อกอยู่
        _attempts[client_ip] = (count + 1, now)


def clear_failed_attempts(client_ip: str) -> None:
    with _attempts_lock:
        _attempts.pop(client_ip, None)


def reset_throttle() -> None:
    """ล้างตัวนับทั้งหมด — ใช้ในเทสต์"""
    with _attempts_lock:
        _attempts.clear()


def has_valid_session(request: Request) -> bool:
    cookie = request.cookies.get(SESSION_COOKIE, "")
    if not cookie:
        return False
    return secrets.compare_digest(cookie, session_token())


def is_secure_request(request: Request) -> bool:
    """เช็กว่าคำขอมาทาง https หรือไม่ เพื่อตัดสินใจติดแฟล็ก Secure ให้คุกกี้

    ต้องดู X-Forwarded-Proto ด้วยเพราะบน Render แอปอยู่หลัง reverse proxy —
    ตัว request ที่วิ่งมาถึง uvicorn เป็น http ธรรมดา ทั้งที่ผู้ใช้เข้ามาทาง https
    (ถ้าดูแต่ url.scheme จะไม่ติด Secure เลยบน production)
    """
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded:
        return forwarded.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def set_session_cookie(response: Response, request: Request) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_token(),
        max_age=SESSION_MAX_AGE,
        httponly=True,          # JS อ่านไม่ได้ ลดผลกระทบถ้ามีช่องโหว่ XSS
        samesite="lax",         # กันคำขอข้ามเว็บแบบ CSRF แต่ยังกดลิงก์เข้ามาตรงๆ ได้
        secure=is_secure_request(request),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _extract_basic_credentials(header: str) -> tuple[str, str]:
    """ดึง (ชื่อผู้ใช้, รหัสผ่าน) จาก Authorization: Basic — คืนค่าว่างถ้ารูปแบบผิด"""
    if not header.startswith("Basic "):
        return "", ""
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return "", ""
    username, sep, password = decoded.partition(":")
    if not sep:
        return "", ""
    return username, password


def _reject(request: Request) -> Response:
    """ปฏิเสธคำขอที่ยังไม่ได้ล็อกอิน

    คำขอ API คืน 401 ตรงๆ ให้ frontend/curl จัดการต่อได้ ส่วนคำขอหน้าเว็บพาไป
    หน้าล็อกอินแทน (ถ้าตอบ 401 เฉยๆ ผู้ใช้บนมือถือจะเห็นแค่หน้าเปล่าไม่รู้ว่าต้องทำอะไร)
    """
    if request.url.path.startswith("/api/"):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": f'Basic realm="{REALM}"'},
            content="ต้องเข้าสู่ระบบก่อนใช้งาน",
            media_type="text/plain; charset=utf-8",
        )
    return RedirectResponse("/login", status_code=303)


class AuthMiddleware(BaseHTTPMiddleware):
    """ครอบทุก route รวมไฟล์สแตติกและ API — ไม่ใช่แค่ซ่อนหน้าแรก"""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in UNAUTHENTICATED_PATHS:
            return await call_next(request)

        if configured_password() is None:
            return await call_next(request)

        if has_valid_session(request):
            return await call_next(request)

        username, password = _extract_basic_credentials(request.headers.get("authorization", ""))
        if password and credentials_valid(username, password):
            return await call_next(request)

        return _reject(request)
