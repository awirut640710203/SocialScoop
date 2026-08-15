"""FastAPI backend ของ SocialScoop

หมายเหตุสำคัญ: endpoint ที่เรียก yt-dlp ประกาศเป็น `def` ธรรมดา (ไม่ใช่ `async def`)
โดยตั้งใจ — FastAPI จะรันฟังก์ชันแบบ sync ใน threadpool ให้เอง ทำให้งานที่บล็อก
(อย่าง yt-dlp และ requests) ไม่ไปหยุด event loop ของทั้งเซิร์ฟเวอร์
"""

from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from . import ai_chat, auth, downloader
from .auth import AuthMiddleware
from .extract import PLATFORM_LABELS, detect_platform

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = (BASE_DIR.parent / "downloads").resolve()

app = FastAPI(title="SocialScoop", version="0.1.0")
app.add_middleware(AuthMiddleware)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class UrlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class AskRequest(BaseModel):
    caption: str = Field(min_length=1, max_length=20000)
    question: str = Field(min_length=1, max_length=1000)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "ai_enabled": ai_chat.has_api_key(),
            # ไม่ได้ตั้งรหัสผ่าน = ไม่มีระบบล็อกอิน จึงไม่ต้องโชว์ปุ่มออกจากระบบให้งง
            "auth_enabled": auth.configured_password() is not None,
        },
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """หน้าล็อกอิน — ถ้าล็อกอินอยู่แล้วเด้งกลับหน้าหลักเลย ไม่ต้องกรอกซ้ำ"""
    if auth.configured_password() is None or auth.has_valid_session(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@app.post("/login")
async def login_submit(request: Request):
    """ตรวจชื่อผู้ใช้+รหัสผ่าน แล้วออกคุกกี้เซสชันอายุ 1 ปีให้เครื่องนี้จำไว้

    แกะฟอร์มเองด้วย parse_qs แทนการใช้ request.form() ของ Starlette เพราะตัวนั้น
    บังคับให้ติดตั้ง python-multipart เพิ่ม ทั้งที่ฟอร์มนี้เป็น urlencoded ธรรมดา
    แค่ 2 ช่อง — เลี่ยง dependency เพิ่มเพื่อให้ image ที่ deploy เล็กและ build เร็ว
    """
    client_ip = request.client.host if request.client else "unknown"

    retry_after = auth.throttle_retry_after(client_ip)
    if retry_after:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": f"ลองผิดหลายครั้งเกินไป — รออีก {retry_after} วินาทีแล้วลองใหม่"},
            status_code=429,
        )

    raw_body = (await request.body()).decode("utf-8", errors="replace")
    fields = parse_qs(raw_body, keep_blank_values=True)
    username = (fields.get("username") or [""])[0]
    password = (fields.get("password") or [""])[0]

    if not auth.credentials_valid(username, password):
        auth.record_failed_attempt(client_ip)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"},
            status_code=401,
        )

    auth.clear_failed_attempts(client_ip)
    response = RedirectResponse("/", status_code=303)
    auth.set_session_cookie(response, request)
    return response


@app.post("/logout")
def logout():
    """ออกจากระบบเฉพาะเครื่องนี้ (ลบคุกกี้) — เครื่องอื่นที่ล็อกอินไว้ยังใช้ได้ต่อ"""
    response = RedirectResponse("/login", status_code=303)
    auth.clear_session_cookie(response)
    return response


@app.get("/api/detect")
def detect(url: str):
    """ตรวจแพลตฟอร์มจาก URL แบบเร็ว ไม่แตะเน็ต — ใช้โชว์ chip ตอนผู้ใช้วางลิงก์"""
    platform = detect_platform(url)
    return {
        "platform": platform,
        "label": PLATFORM_LABELS.get(platform) if platform else None,
    }


@app.post("/api/fetch")
def fetch(payload: UrlRequest):
    """ดึงรายละเอียดโพสต์ (ยังไม่โหลดไฟล์วิดีโอ)"""
    url = payload.url.strip()
    try:
        details = downloader.fetch_metadata(url)
    except downloader.DownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"ok": True, "details": details, "url": url}


@app.post("/api/download")
def download(payload: UrlRequest):
    """ดาวน์โหลดไฟล์วิดีโอจริง คืนชื่อไฟล์ให้ frontend เอาไปขอต่อที่ /api/file"""
    url = payload.url.strip()
    try:
        result = downloader.download_video(url, DOWNLOAD_DIR)
    except downloader.DownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"ok": True, "filename": result["filename"], "details": result["details"]}


@app.get("/api/file/{filename}")
def get_file(filename: str):
    """ส่งไฟล์ที่ดาวน์โหลดไว้ให้ผู้ใช้

    ป้องกัน path traversal ด้วยการ resolve แล้วเช็กว่าไฟล์อยู่ใน downloads/ จริง
    """
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="ชื่อไฟล์ไม่ถูกต้อง")

    target = (DOWNLOAD_DIR / filename).resolve()

    if not target.is_relative_to(DOWNLOAD_DIR):
        raise HTTPException(status_code=400, detail="ชื่อไฟล์ไม่ถูกต้อง")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์นี้ อาจถูกลบไปแล้ว")

    return FileResponse(target, filename=filename, media_type="application/octet-stream")


@app.post("/api/ask")
def ask(payload: AskRequest):
    """ถาม AI เกี่ยวกับแคปชั่นของโพสต์"""
    try:
        answer = ai_chat.ask_ai(payload.caption, payload.question)
    except ai_chat.AIError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"ok": True, "answer": answer}


@app.get("/api/health")
def health():
    return {"ok": True, "ai_enabled": ai_chat.has_api_key()}


@app.get("/healthz")
def healthz():
    """Health check สำหรับแพลตฟอร์ม deploy (Render ฯลฯ) — ไม่ต้องผ่านรหัสผ่าน

    ตั้งใจให้คืนข้อมูลน้อยที่สุด ไม่มีอะไรอ่อนไหว เพราะ path นี้ยกเว้นจาก
    BasicAuthMiddleware ไว้ (ดู app/auth.py: UNAUTHENTICATED_PATHS)
    """
    return {"ok": True}
