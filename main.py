"""SocialScoop CLI — ใช้ตอนไม่อยากเปิดหน้าเว็บ

    python main.py <url>                    # ดึงรายละเอียด + ดาวน์โหลดวิดีโอ
    python main.py <url> --info-only        # ดึงรายละเอียดอย่างเดียว ไม่โหลดไฟล์
    python main.py -f links.txt             # ดาวน์โหลดหลายลิงก์จากไฟล์
    python main.py <url> -a "สรุปให้หน่อย"   # ถาม AI ต่อ (ต้องมี OPENROUTER_API_KEY)

ถ้าอยากใช้หน้าเว็บให้รัน:  python run.py
"""

import argparse
import json
import sys
from pathlib import Path

from app import ai_chat, downloader
from run import load_dotenv


def show_details(details: dict) -> None:
    print(f"  ชื่อ      : {details.get('title') or '-'}")
    print(f"  ผู้โพสต์  : {details.get('uploader') or '-'}")

    caption = details.get("caption")
    print(f"  คำบรรยาย  : {caption or '(ไม่มีคำบรรยาย)'}")

    if details.get("hashtags"):
        print(f"  แฮชแท็ก   : {' '.join(details['hashtags'])}")

    for link in details.get("shopee_links") or []:
        print(f"  Shopee    : {link}")
        print("              (คัดลอกไปเปิดหน้าสินค้าจริง แล้วสร้างลิงก์ affiliate ของคุณเอง)")

    stats = details.get("stats") or {}
    labels = {"like": "ถูกใจ", "comment": "ความคิดเห็น", "view": "การเข้าชม"}
    parts = [f"{labels.get(k, k)} {v}" for k, v in stats.items() if v]
    if parts:
        print(f"  ยอดมีส่วนร่วม: {' · '.join(parts)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ดาวน์โหลดวิดีโอ + ดึงรายละเอียดโพสต์จาก TikTok/Instagram/Threads",
    )
    parser.add_argument("url", nargs="?", help="ลิงก์โพสต์")
    parser.add_argument("-f", "--file", help="ไฟล์รวมลิงก์ (บรรทัดละ 1 ลิงก์)")
    parser.add_argument("--info-only", action="store_true", help="ดึงรายละเอียดอย่างเดียว ไม่ดาวน์โหลดไฟล์")
    parser.add_argument("--json", action="store_true", help="แสดงผลเป็น JSON")
    parser.add_argument("-a", "--ask", help="ถาม AI เกี่ยวกับคำบรรยายที่ดึงมา")
    args = parser.parse_args()

    load_dotenv()

    urls: list[str] = []
    if args.url:
        urls.append(args.url)
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_file():
            parser.error(f"ไม่พบไฟล์: {args.file}")
        urls.extend(
            line.strip()
            for line in file_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    if not urls:
        parser.error("ต้องระบุ url หรือ --file")

    failures = 0
    for url in urls:
        print(f"\n>> {url}")
        try:
            if args.info_only:
                details = downloader.fetch_metadata(url)
            else:
                result = downloader.download_video(url)
                details = result["details"]
                print(f"  ไฟล์      : {result['video_path']}")
        except downloader.DownloadError as exc:
            print(f"  ผิดพลาด   : {exc}", file=sys.stderr)
            failures += 1
            continue

        if args.json:
            print(json.dumps(details, ensure_ascii=False, indent=2))
        else:
            show_details(details)

        if args.ask:
            try:
                print(f"  AI        : {ai_chat.ask_ai(details.get('caption') or '', args.ask)}")
            except ai_chat.AIError as exc:
                print(f"  AI ผิดพลาด: {exc}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
