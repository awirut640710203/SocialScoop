"""เปิด SocialScoop ออกอินเทอร์เน็ตจริงด้วยคำสั่งเดียว ผ่าน Cloudflare Tunnel

    python serve_public.py

เปิดเซิร์ฟเวอร์ที่ 127.0.0.1 แล้วเจาะทะลุออกอินเทอร์เน็ตผ่าน Cloudflare Quick Tunnel
(ฟรี ไม่ต้องมีบัญชี Cloudflare ก็ใช้ได้) ได้ URL สาธารณะรูปแบบ
https://xxxx.trycloudflare.com ให้ทันที

ข้อจำกัดของ Quick Tunnel: URL เปลี่ยนทุกครั้งที่รันคำสั่งนี้ใหม่ ถ้าต้องการ URL
ถาวรที่ไม่เปลี่ยน ต้องตั้งค่า named tunnel ผูกกับโดเมนของคุณเองใน Cloudflare
(ดูวิธีใน README หัวข้อ "URL ถาวร")

กด Ctrl+C เพื่อปิดทั้งเซิร์ฟเวอร์และ tunnel พร้อมกัน
"""

import os
import re
import shutil
import subprocess
import sys
import threading

from run import load_dotenv

PORT = 8000
URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

CLOUDFLARED_CANDIDATES = [
    "cloudflared",
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
]


def find_cloudflared() -> str:
    for candidate in CLOUDFLARED_CANDIDATES:
        if shutil.which(candidate) or os.path.isfile(candidate):
            return candidate
    print("ไม่พบ cloudflared — ติดตั้งก่อนด้วย: winget install Cloudflare.cloudflared")
    raise SystemExit(1)


def pump(proc: subprocess.Popen, prefix: str, on_line=None) -> None:
    """อ่าน stdout ของ subprocess อย่างต่อเนื่องในเธรดแยก

    จำเป็นต้องมี — ถ้าไม่มีใครอ่าน stdout ที่ผูก pipe ไว้ บัฟเฟอร์จะเต็มแล้ว
    ทำให้ subprocess ค้างตอนพยายาม print (พังทั้งเซิร์ฟเวอร์แบบเงียบ ๆ)
    """
    for line in proc.stdout:
        line = line.rstrip()
        if on_line and on_line(line):
            continue  # จัดการเป็นพิเศษแล้ว ไม่ต้อง print ซ้ำ
        if prefix:
            print(f"[{prefix}] {line}", flush=True)


def main() -> None:
    load_dotenv()

    if not os.environ.get("SOCIALSCOOP_PASSWORD", "").strip():
        print(
            "คำเตือน: ยังไม่ได้ตั้ง SOCIALSCOOP_PASSWORD ใน .env — "
            "เว็บจะเปิดสาธารณะโดยไม่มีรหัสผ่านป้องกันเลย"
        )

    cloudflared = find_cloudflared()

    # PYTHONUNBUFFERED กัน print()/logging ของ subprocess ค้างในบัฟเฟอร์เมื่อ
    # stdout ไม่ใช่ terminal จริง (เช่นตอนรันผ่าน harness หรือ redirect เข้าไฟล์)
    child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    server = subprocess.Popen(
        [sys.executable, "run.py", "--port", str(PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=child_env,
    )
    threading.Thread(target=pump, args=(server, "server"), daemon=True).start()

    tunnel = subprocess.Popen(
        [cloudflared, "tunnel", "--url", f"http://127.0.0.1:{PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    found_url = threading.Event()

    def catch_url(line: str) -> bool:
        if found_url.is_set():
            return False
        match = URL_PATTERN.search(line)
        if not match:
            return False
        found_url.set()
        print(flush=True)
        print("=" * 64, flush=True)
        print(f"  เปิดใช้งานได้แล้วที่:  {match.group(0)}", flush=True)
        print("  (URL นี้เปลี่ยนทุกครั้งที่รันคำสั่งนี้ใหม่)", flush=True)
        print("  กด Ctrl+C เพื่อปิด", flush=True)
        print("=" * 64, flush=True)
        print(flush=True)
        return True

    threading.Thread(target=pump, args=(tunnel, None, catch_url), daemon=True).start()

    try:
        tunnel.wait()
    except KeyboardInterrupt:
        pass
    finally:
        tunnel.terminate()
        server.terminate()


if __name__ == "__main__":
    main()
