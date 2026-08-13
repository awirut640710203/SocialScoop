# สำหรับ deploy บน Render.com (หรือ container platform ใดก็ได้ที่รองรับ Docker)
#
# ใช้ python:3.12-slim เพราะเบากว่า image เต็ม แต่ยังมี apt ให้ติดตั้ง ffmpeg ได้
# (ffmpeg จำเป็นสำหรับ yt-dlp ใช้ merge วิดีโอ+เสียงเข้าด้วยกัน)

FROM python:3.12-slim

# ffmpeg: yt-dlp ต้องใช้ merge สตรีมวิดีโอ/เสียง
# --no-install-recommends กันแพ็กเกจเสริมที่ไม่จำเป็นทำให้ image บวม
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# copy requirements ก่อน copy โค้ดทั้งหมด เพื่อให้ Docker cache เลเยอร์ pip install
# ไว้ได้ — แก้แค่โค้ดแอปจะไม่ต้องติดตั้ง dependency ใหม่ทุกครั้งที่ build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# รันด้วย user ที่ไม่ใช่ root ตามหลักปฏิบัติด้านความปลอดภัย
# ต้อง chown /app ให้ appuser ก่อนสลับ user เพราะ downloader.py จะสร้างโฟลเดอร์
# downloads/ เองตอนรันไทม์ (mkdir(parents=True)) — ถ้า /app ยังเป็นของ root
# appuser จะไม่มีสิทธิ์สร้างโฟลเดอร์นั้น แล้วดาวน์โหลดครั้งแรกจะพังทันที
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Render (และ container platform ส่วนใหญ่) กำหนดพอร์ตผ่าน environment variable
# $PORT มาให้เอง ไม่ใช่พอร์ตตายตัว — ต้อง bind 0.0.0.0 ไม่ใช่ 127.0.0.1 เพราะ
# ต้องรับ request จากภายนอก container ได้
ENV PORT=8000
EXPOSE 8000

# ใช้ shell form (ไม่ใช่ JSON array) เพื่อให้ $PORT ถูกขยายค่าจริงตอนรัน
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
