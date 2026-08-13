# SocialScoop — แนวทางการสร้างโปรเจค

ดาวน์โหลดวิดีโอจาก TikTok / Instagram / Threads พร้อมดึงข้อความ (caption) ของผู้โพสต์ และให้ AI ถามตอบ / สรุปเนื้อหาได้

---

## 1. ภาพรวมโปรเจค

| หัวข้อ | รายละเอียด |
|---|---|
| ภาษา | Python |
| ฟีเจอร์หลัก | ดาวน์โหลดวิดีโอคุณภาพสูงสุด (≤1080p) จาก TikTok, Instagram (Reels/โพสต์), Threads |
| ข้อมูลเสริม | ดึง caption / แฮชแท็ก / ชื่อผู้โพสต์ / ยอดไลก์ (metadata) |
| AI | เชื่อมต่อโมเดลฟรี (OpenRouter) เพื่อถามตอบ / สรุปเนื้อหาจาก caption |
| เป้าหมายผู้ใช้ | ผู้ใช้งานทั่วไปที่อยากเก็บคลิป + ข้อความไว้ใช้ / วิเคราะห์ |

---

## 2. เทคโนโลยีที่ใช้

### 2.1 ดาวน์โหลดวิดีโอ — `yt-dlp`
- รองรับทั้ง 3 แพลตฟอร์มในไลบรารีเดียว
- เลือกคุณภาพสูงสุดไม่เกิน 1080p
- บันทึกไฟล์: วิดีโอ mp4 + `.description` (ข้อความ) + `.info.json` (เมตาดาต้าเต็ม)

```python
opts = {
    "format": "bv*+ba/b",          # คุณภาพสูงสุดเท่าที่มี
    "merge_output_format": "mp4",
    "outtmpl": "%(id)s.%(ext)s",
    "writedescription": True,
    "writeinfojson": True,
}
```

> **คำเตือน (พบตอนพัฒนา 2026-08-13):** ห้ามใส่ `[height<=1080]` กลับเข้ามาเด็ดขาด
> คลิปจาก TikTok/Reels/Threads เป็นแนวตั้ง ไฟล์ 1080p ตัวจริงมีขนาด 1080×1920
> ซึ่งความสูงคือ 1920 การกรอง `height<=1080` จึงตัดไฟล์คุณภาพสูงสุดทิ้ง แล้วไปเลือก
> 576×1024 (540p) ที่แย่ที่สุดแทน — มี regression test คุมไว้ที่ `tests/test_format_spec.py`

### 2.2 AI ถามตอบ — OpenRouter (ฟรี)
- ใช้โมเดล open-source ฟรี (รุ่น `:free`)
- **หมายเหตุ:** รายการรุ่นฟรีเปลี่ยนบ่อย ต้องเช็กล่าสุดที่ `openrouter.ai/models` (กรอง "Free") หรือ repo `github.com/ClawLabsAI/free-ai-models`
- รุ่นแนะนำ (ส.ค. 2026): `openrouter/free` (auto-router เลือกให้เอง), `meta-llama/llama-3.3-70b-instruct:free`, `google/gemma-4-31b-it:free`, `openai/gpt-oss-20b:free`
- ข้อจำกัด: ประมาณ 50 คำขอ/วัน (บัญชีใหม่), 1,000/วัน (ถ้าซื้อเครดิต $10)

```python
import requests
resp = requests.post("https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    json={"model": "openrouter/free",
          "messages": [{"role": "user", "content": "สรุปคลิปนี้ให้หน่อย: " + caption}]})
```

---

## 3. ข้อควรรู้ / ข้อจำกัดของแต่ละแพลตฟอร์ม

### TikTok
- ไม่มี API ดาวน์โหลดอย่างเป็นทางการ — ใช้ yt-dlp (เจอ watermark บางคลิป)
- 1080p เฉพาะคลิปที่ผู้โพสต์อัปโหลดความชัดนั้นจริง ๆ

### Instagram
- บล็อก/จำกัดบ่อย — ถ้า error ให้ใช้ `"cookiesfrombrowser": ("chrome",)` (ดึงคุกกี้จากเบราว์เซอร์ที่ล็อกอิน)
- ต้องเป็นโพสต์ public

### Threads
- yt-dlp รองรับอยู่แล้ว (อัปเดต yt-dlp ให้ล่าสุดเสมอ: `pip install -U yt-dlp`)
- ต้องเป็นโพสต์ public

---

## 4. แนวทางพัฒนา (Roadmap)

1. **MVP — ดาวน์โหลดอย่างเดียว**
   - รับ URL → ดาวน์โหลดวิดีโอ + caption + metadata
2. **เก็บข้อมูลเป็นไฟล์เดียว**
   - รวม caption + ลิงก์ + ชื่อไฟล์วิดีโอ ไว้ในไฟล์สรุป
3. **เชื่อม AI ถามตอบ**
   - ผู้ใช้ถามคำถาม → ใช้ caption เป็น context → ส่งให้โมเดลฟรีผ่าน OpenRouter
4. **รองรับหลายลิงก์ / batch**
   - ใส่ไฟล์ลิงก์ทีเดียวแล้วดาวน์โหลดทั้งหมด
5. **ทางเลือกเพิ่มเติม (ยังไม่ตัดสินใจ)**
   - Shopee Affiliate API: ค้นสินค้า + สร้างลิงก์ affiliate (ต้องสมัครบัญชี Affiliate ที่ affiliate.shopee.co.th ก่อน ขอสิทธิ์ Open API ได้ App ID + Secret Key)

---

## 5. โครงสร้างไฟล์ที่เสนอ

```
SocialScoop/
├── main.py              # จุดเริ่มต้น (รับ URL / ไฟล์ลิงก์)
├── downloader.py        # ฟังก์ชัน yt-dlp + บันทึก caption/metadata
├── ai_chat.py           # เชื่อม OpenRouter สำหรับถาม-ตอบ / สรุป
├── requirements.txt     # yt-dlp, requests
└── PROJECT_PLAN.md      # ไฟล์นี้
```

---

## 6. ขั้นตอนติดตั้ง (เร็ว ๆ)

```bash
pip install -U yt-dlp requests
python main.py https://www.tiktok.com/...   # ตัวอย่าง
```

---

## 7. หมายเหตุ

- ดาวน์โหลดวิดีโอ/ข้อความของคนอื่น: ควรใช้เพื่อการใช้งานส่วนตัว อ้างอิงตามกฎของแต่ละแพลตฟอร์ม
- ของฟรี (โมเดล AI / quota) เปลี่ยนตลอดเวลา — ออกแบบโค้ดให้เปลี่ยน model ได้ง่าย
- ถ้าต้องการความเสถียรระดับ production ควรใช้ API แบบจ่ายเงิน
