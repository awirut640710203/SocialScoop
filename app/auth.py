"""ป้องกันทั้งเว็บด้วยรหัสผ่านเดียว (HTTP Basic Auth)

จำเป็นเมื่อ deploy ออกอินเทอร์เน็ตจริง (เช่นผ่าน Cloudflare Tunnel) เพราะไม่งั้น
ใครก็ได้ที่รู้ลิงก์จะมาใช้โควตาดาวน์โหลดวิดีโอและโควตา AI ฟรีของเราแบบไม่จำกัด
"""

import base64
import binascii
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REALM = "SocialScoop"

# path ที่ยกเว้นไม่ต้องผ่านรหัสผ่าน — เฉพาะ health check endpoint สำหรับให้
# แพลตฟอร์ม deploy (เช่น Render) ตรวจสอบว่าเซิร์ฟเวอร์ยังตอบสนองอยู่หรือไม่
# ถ้าไม่ยกเว้นตรงนี้ Render จะเจอ 401 ทุกครั้งที่ตรวจสุขภาพ แล้วคิดว่าแอปพัง
# ไม่ยอม mark deploy ว่าสำเร็จ — endpoint นี้คืนแค่ {"ok": true} ไม่มีข้อมูลอ่อนไหว
UNAUTHENTICATED_PATHS = frozenset({"/healthz"})


def configured_password() -> str | None:
    """รหัสผ่านที่ตั้งไว้ผ่าน SOCIALSCOOP_PASSWORD หรือ None ถ้าไม่ได้ตั้ง

    ไม่ตั้งค่านี้ = ไม่มีการป้องกันเลย (โหมดใช้ในเครื่อง/วงแลนส่วนตัวเท่านั้น)
    """
    pw = os.environ.get("SOCIALSCOOP_PASSWORD", "").strip()
    return pw or None


def _unauthorized() -> Response:
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="{REALM}"'},
        content="ต้องใส่รหัสผ่านก่อนใช้งาน",
        media_type="text/plain; charset=utf-8",
    )


def _extract_password(header: str) -> str:
    """ดึงรหัสผ่านออกจาก Authorization: Basic header คืนสตริงว่างถ้ารูปแบบผิด"""
    if not header.startswith("Basic "):
        return ""
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return ""
    _, _, supplied = decoded.partition(":")
    return supplied


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """ครอบทุก route รวมไฟล์สแตติกและ API — ไม่ใช่แค่ซ่อนหน้าแรก

    ใช้ username อะไรก็ได้ (เบราว์เซอร์บังคับให้กรอกแต่เราไม่เช็ก) เช็กเฉพาะรหัสผ่าน
    เทียบด้วย secrets.compare_digest กัน timing attack
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in UNAUTHENTICATED_PATHS:
            return await call_next(request)

        password = configured_password()
        if password is None:
            return await call_next(request)

        supplied = _extract_password(request.headers.get("authorization", ""))
        # compare_digest กับ str รองรับเฉพาะ ASCII (พังถ้ารหัสผ่านมีอักษรไทย)
        # เข้ารหัสเป็น bytes ก่อนเทียบ เพื่อให้ตั้งรหัสผ่านภาษาไทยได้ด้วย
        if supplied and secrets.compare_digest(supplied.encode(), password.encode()):
            return await call_next(request)

        return _unauthorized()
