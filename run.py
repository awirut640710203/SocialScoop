"""เปิดเว็บเซิร์ฟเวอร์ SocialScoop

    python run.py            # เปิดที่ http://127.0.0.1:8000
    python run.py --port 9000
"""

import argparse
import os
from pathlib import Path

import uvicorn


def load_dotenv(path: Path = Path(".env")) -> None:
    """อ่านไฟล์ .env แบบง่าย ๆ ไม่ต้องพึ่งไลบรารีเพิ่ม

    รองรับรูปแบบ KEY=VALUE บรรทัดละตัว, ข้ามบรรทัดว่างและ comment
    ค่าที่ตั้งไว้ใน environment อยู่แล้วจะไม่ถูกเขียนทับ
    """
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description="เปิดเว็บเซิร์ฟเวอร์ SocialScoop")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="รีโหลดอัตโนมัติเมื่อแก้โค้ด (สำหรับพัฒนา)")
    args = parser.parse_args()

    load_dotenv()

    print(f"SocialScoop กำลังทำงานที่ http://{args.host}:{args.port}")
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("หมายเหตุ: ยังไม่มี OPENROUTER_API_KEY — ฟีเจอร์ถาม AI จะถูกปิดไว้")

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
