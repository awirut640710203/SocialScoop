# SocialScoop

ดาวน์โหลดวิดีโอจาก **TikTok / Instagram / Threads** พร้อมดึงแคปชั่น แฮชแท็ก สถิติ และลิงก์ Shopee ที่ซ่อนอยู่ในโพสต์ แล้วถาม AI เกี่ยวกับเนื้อหาได้ทันที

---

## เริ่มใช้งาน

```bash
# 1. ติดตั้ง (ครั้งแรกครั้งเดียว)
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. เปิดเว็บ
venv\Scripts\python.exe run.py
# เปิดเบราว์เซอร์ไปที่ http://127.0.0.1:8000
```

ถ้าอยากใช้ AI ถามตอบ ให้คัดลอก `.env.example` เป็น `.env` แล้วใส่คีย์ฟรีจาก [openrouter.ai/keys](https://openrouter.ai/keys)
(ไม่ใส่ก็ใช้ส่วนอื่นได้ปกติ แค่ช่องถาม AI จะถูกปิดไว้)

---

## ใช้จากบรรทัดคำสั่ง

```bash
python main.py <url>                    # ดึงรายละเอียด + ดาวน์โหลดวิดีโอ
python main.py <url> --info-only        # ดูรายละเอียดอย่างเดียว ไม่โหลดไฟล์
python main.py <url> --json             # แสดงผลเป็น JSON
python main.py -f links.txt             # ดาวน์โหลดหลายลิงก์
python main.py <url> -a "สรุปให้หน่อย"   # ถาม AI ต่อ
```

---

## สิ่งที่ดึงมาให้

| ข้อมูล | หมายเหตุ |
|---|---|
| วิดีโอ | คุณภาพสูงสุดเท่าที่โพสต์นั้นมี — **ไม่มีตัวเลือกให้เลือก** ตั้งใจให้ได้ตัวดีที่สุดเสมอ |
| แคปชั่น | ข้อความเต็มของโพสต์ |
| แฮชแท็ก | แยกออกมาจากแคปชั่น รองรับภาษาไทย |
| สถิติ | ไลก์ / คอมเมนต์ / วิว — **ซ่อนแถวถ้าไม่มีข้อมูล** ไม่โชว์ 0 หลอก |
| ลิงก์ Shopee | ตรวจจับอัตโนมัติจากแคปชั่น แยกแถวไฮไลต์ต่างหาก |

ทุกช่องมีปุ่มคัดลอก และมีปุ่ม "คัดลอกทั้งหมด" รวมทุกอย่างเป็นข้อความเดียว

### ลิงก์ Shopee ใช้ทำอะไร

พบบ่อยในโพสต์ Threads ที่เขียนลิงก์เต็มลงในข้อความ เวิร์กโฟลว์คือ:

1. คัดลอกลิงก์ Shopee ที่เจอ
2. เปิดหาสินค้าตัวจริงจากลิงก์นั้น (เร็วกว่าเดาชื่อสินค้าแล้วค้นเอง)
3. สร้างลิงก์ affiliate **ของคุณเอง** จากสินค้านั้น

เครื่องมือนี้ช่วยแค่ขั้นที่ 1–2 — ไม่ได้สร้างลิงก์ affiliate ให้อัตโนมัติ

---

## เมื่อโดนบล็อก

TikTok และ Instagram บล็อกคำขอที่ยิงถี่หรือไม่มีคุกกี้เป็นระยะ ถ้าเจอ error ให้ลองตามลำดับ:

1. **รอ 1–2 นาทีแล้วลองใหม่** — ส่วนใหญ่เป็นการจำกัดชั่วคราว
2. **ใช้ไฟล์คุกกี้** — export `cookies.txt` จากส่วนขยายเบราว์เซอร์ แล้วตั้งใน `.env`:
   ```
   SOCIALSCOOP_COOKIES_FILE=cookies.txt
   ```
3. **ดึงคุกกี้จากเบราว์เซอร์ตรง ๆ** — `SOCIALSCOOP_COOKIES_BROWSER=firefox`
   (Chrome/Edge บน Windows มักไม่ได้ผลเพราะ App-Bound Encryption)

---

## เทสต์

```bash
venv\Scripts\python.exe -m pytest
```

เทสต์ทั้งหมด mock เน็ตเวิร์กไว้ รันได้โดยไม่ต้องต่ออินเทอร์เน็ต

---

## โครงสร้าง

```
SocialScoop/
├── app/
│   ├── main.py           # FastAPI endpoints
│   ├── downloader.py     # yt-dlp: fetch_metadata() / download_video()
│   ├── extract.py        # parse แคปชั่น: แฮชแท็ก, ลิงก์ Shopee, แพลตฟอร์ม
│   ├── ai_chat.py        # OpenRouter + แคชคำตอบ
│   ├── templates/index.html
│   └── static/{style.css, app.js}
├── tests/                # pytest — 65 เทสต์
├── main.py               # CLI
├── run.py                # เปิดเซิร์ฟเวอร์
└── downloads/            # ไฟล์ที่ดาวน์โหลด (gitignored)
```

---

## ข้อควรระวังทางเทคนิค

**อย่าใส่ `[height<=1080]` กลับเข้าไปใน format string** — คลิปแนวตั้ง 1080p มีขนาด 1080×1920
ความสูงคือ 1920 การกรองด้วย height จะตัดไฟล์ดีที่สุดทิ้งแล้วเหลือ 540p
มี regression test คุมไว้ที่ `tests/test_format_spec.py`

---

## หมายเหตุ

- ใช้เพื่อการใช้งานส่วนตัว เคารพลิขสิทธิ์และกฎของแต่ละแพลตฟอร์ม
- รองรับเฉพาะโพสต์สาธารณะ
- รายชื่อโมเดลฟรีของ OpenRouter เปลี่ยนบ่อย ถ้าใช้ไม่ได้ให้เช็กที่ [openrouter.ai/models](https://openrouter.ai/models) แล้วแก้ `FREE_MODELS` ใน `app/ai_chat.py`
- yt-dlp ยังไม่มี extractor เฉพาะของ Threads (ใช้ generic) จึงอาจได้ข้อมูลไม่ครบเท่า TikTok/Instagram
