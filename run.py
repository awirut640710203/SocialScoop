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


def lan_ip() -> str | None:
    """หา IP ของเครื่องนี้ในวงแลน เพื่อบอกที่อยู่ให้มือถือเปิดตาม

    ใช้วิธีเปิด UDP socket ไปยังปลายทางภายนอกโดยไม่ส่งข้อมูลจริง
    เพื่อให้ระบบปฏิบัติการเลือก network interface ที่ใช้ออกเน็ตจริงมาให้
    """
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="เปิดเว็บเซิร์ฟเวอร์ SocialScoop")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--lan",
        action="store_true",
        help="เปิดให้เครื่องอื่นในวง Wi-Fi เดียวกันเข้าถึงได้ (เช่น iPhone / iPad)",
    )
    parser.add_argument("--reload", action="store_true", help="รีโหลดอัตโนมัติเมื่อแก้โค้ด (สำหรับพัฒนา)")
    args = parser.parse_args()

    load_dotenv()

    host = "0.0.0.0" if args.lan else args.host  # noqa: S104 — ผู้ใช้ขอเปิดเองผ่าน --lan

    if args.lan:
        ip = lan_ip()
        print("SocialScoop เปิดให้เครื่องในวง Wi-Fi เดียวกันเข้าถึงได้แล้ว", flush=True)
        if ip:
            print(f"  เปิดจากมือถือ/แท็บเล็ตที่:  http://{ip}:{args.port}", flush=True)
        else:
            print(f"  หา IP ของเครื่องไม่ได้ ลองดูจาก ipconfig แล้วเปิด http://<IP>:{args.port}", flush=True)
        print(f"  เปิดจากเครื่องนี้ที่:        http://127.0.0.1:{args.port}", flush=True)
        print()
        print("  หมายเหตุ: การเชื่อมต่อแบบนี้เป็น http ธรรมดา ไม่ใช่ https", flush=True)
        print("  ปุ่มคัดลอกจึงใช้วิธีสำรองแทน Clipboard API ซึ่งบางเบราว์เซอร์อาจคัดลอกไม่สำเร็จ", flush=True)
        print("  ถ้าเจอปัญหา ให้แตะค้างที่ข้อความแล้วคัดลอกเองได้", flush=True)
    else:
        print(f"SocialScoop กำลังทำงานที่ http://{host}:{args.port}", flush=True)
        print("  ถ้าต้องการเปิดจาก iPhone/iPad ให้รันด้วย:  python run.py --lan", flush=True)

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("หมายเหตุ: ยังไม่มี OPENROUTER_API_KEY — ฟีเจอร์ถาม AI จะถูกปิดไว้", flush=True)

    if os.environ.get("SOCIALSCOOP_PASSWORD", "").strip():
        print("การป้องกันด้วยรหัสผ่าน: เปิดอยู่", flush=True)
    elif args.lan:
        print(
            "คำเตือน: เปิดโหมด --lan แต่ยังไม่ได้ตั้ง SOCIALSCOOP_PASSWORD — "
            "ใครก็ตามในวง Wi-Fi นี้เข้าใช้งานได้โดยไม่ต้องใส่รหัส",
            flush=True,
        )

    uvicorn.run("app.main:app", host=host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
