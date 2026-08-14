"""FastAPI backend ของ SocialScoop

หมายเหตุสำคัญ: endpoint ที่เรียก yt-dlp ประกาศเป็น `def` ธรรมดา (ไม่ใช่ `async def`)
โดยตั้งใจ — FastAPI จะรันฟังก์ชันแบบ sync ใน threadpool ให้เอง ทำให้งานที่บล็อก
(อย่าง yt-dlp และ requests) ไม่ไปหยุด event loop ของทั้งเซิร์ฟเวอร์
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from . import ai_chat, downloader
from .auth import BasicAuthMiddleware
from .extract import PLATFORM_LABELS, detect_platform

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = (BASE_DIR.parent / "downloads").resolve()

app = FastAPI(title="SocialScoop", version="0.1.0")
app.add_middleware(BasicAuthMiddleware)
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
        context={"ai_enabled": ai_chat.has_api_key()},
    )


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


# [DBG-th01] endpoint ชั่วคราวสำหรับ debug ว่า Threads fetch ช้าตรงขั้นไหนบน Render
# (launch เบราว์เซอร์ / new_page / goto+content) ลบทิ้งหลัง debug เสร็จ
@app.get("/api/_debug/threads-timing")
def debug_threads_timing(
    url: str = "https://www.threads.com/@humblemogger/post/DTOPIHBkgte/",
):
    import time

    from playwright.sync_api import sync_playwright

    timings = {}
    t_start = time.time()
    with sync_playwright() as p:
        t_pw = time.time()
        timings["sync_playwright_start"] = round(t_pw - t_start, 3)

        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        t_launch = time.time()
        timings["chromium_launch"] = round(t_launch - t_pw, 3)

        page = browser.new_page()
        t_page = time.time()
        timings["new_page"] = round(t_page - t_launch, 3)

        page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ("image", "stylesheet", "font", "media")
            else route.continue_(),
        )
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        t_goto = time.time()
        timings["goto_domcontentloaded"] = round(t_goto - t_page, 3)

        html = page.content()
        t_content = time.time()
        timings["content"] = round(t_content - t_goto, 3)
        timings["has_data"] = "video_versions" in html or "image_versions2" in html

        browser.close()
        t_close = time.time()
        timings["browser_close"] = round(t_close - t_content, 3)

    timings["total"] = round(time.time() - t_start, 3)
    return timings
