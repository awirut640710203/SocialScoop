"""ถามตอบและสรุปเนื้อหาจากคำบรรยายโพสต์ ผ่านโมเดลฟรีของ OpenRouter"""

import os
import threading

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# รุ่นฟรี เรียงตามความเร็วที่วัดได้จริง (เร็วไปช้า) ไม่ใช่คะแนนความฉลาดอีกต่อไป
#
# เปลี่ยนจากเรียงตาม Intelligence Index มาเป็นเรียงตามความเร็ว เพราะผู้ใช้ต้องการ
# คำตอบไวเป็นหลัก งานนี้คือสรุป/ตอบคำถามสั้นๆ จากแคปชั่น ไม่ใช่งานที่ต้องใช้โมเดล
# ฉลาดที่สุด — ต่างจากคะแนนความฉลาดที่ค่อนข้างนิ่ง ความเร็ว/ความพร้อมใช้งานของรุ่นฟรี
# บน OpenRouter แกว่งขึ้นลงรายวันมาก (วัดจริงพบว่ารุ่นที่เคยบันทึกไว้ว่า 28.2s
# กลับตอบใน 2.3s ในวันถัดมา) การล็อกลำดับตายตัวตามคะแนนจึงไม่สะท้อนของจริง
#
# เหตุผลที่ต้องแก้ทั้งหมดนี้: ตรวจพบว่า 4 ใน 7 ตัวเดิมพังอยู่ตอนนี้ —
# nvidia/nemotron-3-ultra-550b-a55b (404 provider error), inclusionai/ling-3.0-tiny
# (404 — หลุดจากรายการรุ่นฟรีของ OpenRouter ไปแล้ว), google/gemma-4-31b-it และ
# openai/gpt-oss-20b (429 rate limit ต่อเนื่อง) ทำให้ทุกคำขอต้องไล่ผ่านรุ่นที่พัง
# ก่อนจะถึงรุ่นที่ใช้ได้จริง — นี่คือสาเหตุที่ระบบ "ช้ามาก" และบางทีก็ "ใช้ไม่ได้เลย"
#
# ตัวเลขท้ายบรรทัด = เวลาตอบจริงที่วัดตอนสร้างลิสต์นี้ (2026-08-15) — ทดสอบด้วยโจทย์
# ภาษาไทย 2 ข้อต่อรุ่น ตัดตัวที่ตอบผิดรูปแบบ/ปนภาษาอังกฤษ/พังออก
# ห้ามใส่โมเดลที่ไม่ลงท้าย ":free" เด็ดขาด (มีเทสต์คุมไว้) เพราะจะเริ่มมีค่าใช้จ่าย
FREE_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",           # 2.3s · เร็วสุด ผ่านทดสอบไทย 2/2
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  # 3.2-4.3s · ผ่าน 2/2 คำตอบสะอาด
    "cohere/north-mini-code:free",                      # 4.8s · ผ่าน 2/2 เสถียร
    "dots-studio/dots-3-note-preview:free",             # 3.2-3.9s · ผ่าน 2/2 แต่เคยปนคำอังกฤษ
                                                         # ("priced 990 bath") ครั้งหนึ่ง จึงเรียง
                                                         # ไว้หลัง cohere ทั้งที่เร็วกว่า
    "google/gemma-4-26b-a4b-it:free",                   # 7.6s · ช้าสุดในกลุ่มแต่เสถียร
]

# รุ่นฟรีที่ "ห้ามใช้" พร้อมเหตุผลจากการทดสอบจริง — กันเผลอเพิ่มกลับเข้ามา
#   nvidia/nemotron-3.5-lightning:free  AA 23.6 แต่พ่น chain-of-thought ภาษาอังกฤษ
#                                       แทนคำตอบ ทั้งที่ส่ง reasoning.exclude แล้ว (0/2)
#   nvidia/nemotron-3-nano-30b-a3b:free AA 14.5 อ่อนกว่าตัวอื่นในลิสต์ชัดเจน
#   nvidia/nemotron-nano-9b-v2:free     AA 8.7 (ประมาณการ) อ่อนสุด
#   liquid/lfm-2.5-2.6b:free            ไม่มีคะแนนใน AA และช้า 13.5s
#   openrouter/free                     auto-router คุมไม่ได้ว่าวิ่งไปรุ่นไหน ช้า 22s
#   deepseek/* ทุกตัว                    คะแนนสูง (V4 Pro = 53.0) แต่ไม่มีรุ่นฟรีบน
#                                       OpenRouter — ถูกมากแต่ไม่ใช่ 0
#   google/lyria-3-*                    โมเดลสร้างเพลง ไม่ใช่แชท
#   nvidia/nemotron-3.5-content-safety  โมเดลกรองเนื้อหา ไม่ใช่แชท
#   poolside/laguna-s-2.1:free          ตอบกลับโครงสร้างผิด (response ว่าง/parse ไม่ได้)
#   poolside/laguna-xs-2.1:free         15.5s ช้าเกินไปสำหรับกลุ่มที่เน้นความเร็ว
#   nvidia/nemotron-nano-12b-v2-vl:free 20.6s ช้าเกินไปสำหรับกลุ่มที่เน้นความเร็ว
#
# ออกจากลิสต์ชั่วคราวเพราะพังตอนสร้างลิสต์นี้ (2026-08-15) — เช็กใหม่ได้ทีหลังว่า
# OpenRouter แก้แล้วหรือยัง ก่อนใส่กลับ (ห้ามใส่กลับเฉยๆ โดยไม่ทดสอบซ้ำ):
#   nvidia/nemotron-3-ultra-550b-a55b:free  404 provider error จากต้นทาง
#   inclusionai/ling-3.0-tiny:free          404 — ไม่อยู่ในรายการรุ่นฟรีของ OpenRouter แล้ว
#   google/gemma-4-31b-it:free              429 rate limited ต่อเนื่อง
#   openai/gpt-oss-20b:free                 429 rate limited ต่อเนื่อง

# จำกัดความยาวคำตอบ กันโมเดลร่ายยาวและกันโควตาหมดเร็ว
MAX_TOKENS = 500

# ลดจาก 60s เหลือ 20s — ของเดิมถ้ารุ่นแรกค้าง (ไม่ error แต่ไม่ตอบ) ผู้ใช้ต้องรอเต็ม
# 60 วินาทีก่อนจะข้ามไปรุ่นถัดไป ทำให้รู้สึกว่า "ใช้ไม่ได้เลย" ทั้งที่จริงแค่รุ่นเดียวค้าง
# 20s เผื่อพอสำหรับรุ่นที่ช้าสุดในลิสต์ (gemma-4-26b ~7.6s) แต่ตัดรุ่นที่ค้างจริงๆ ให้เร็วขึ้น
REQUEST_TIMEOUT_SECONDS = 20

SYSTEM_PROMPT = (
    "คุณเป็นผู้ช่วยวิเคราะห์โพสต์โซเชียลมีเดีย "
    "ตอบเป็นภาษาไทยสั้น กระชับ ตรงคำถาม "
    "ตอบจากข้อมูลในโพสต์ที่ให้มาเท่านั้น ถ้าข้อมูลไม่พอให้บอกตรง ๆ ว่าไม่มีข้อมูลในโพสต์"
)

_cache: dict[tuple[str, str], str] = {}
_cache_lock = threading.Lock()
_CACHE_LIMIT = 200


class AIError(RuntimeError):
    """เรียก AI ไม่สำเร็จ พร้อมข้อความที่แสดงให้ผู้ใช้อ่านได้"""


class CostError(AIError):
    """ตรวจพบว่าคำขอมีค่าใช้จ่าย ทั้งที่ต้องเป็นศูนย์เสมอ"""


def _assert_free(model: str, payload: dict) -> None:
    """ยืนยันว่าคำขอนี้ไม่มีค่าใช้จ่ายจริง

    เป็นด่านสุดท้ายกันกรณี OpenRouter เปลี่ยนรุ่นจากฟรีเป็นเสียเงินโดยไม่บอก
    """
    usage = payload.get("usage") or {}
    cost = usage.get("cost")
    if cost is None:
        return
    try:
        if float(cost) > 0:
            raise CostError(
                f"หยุดไว้ก่อน: รุ่น {model} เริ่มมีค่าใช้จ่ายแล้ว ({cost}) "
                "— ตรวจสอบรายการรุ่นฟรีล่าสุดที่ openrouter.ai/models"
            )
    except (TypeError, ValueError):
        return


def has_api_key() -> bool:
    """เช็กว่ามี API key ตั้งไว้หรือยัง — ให้ UI ซ่อน/ปิดช่องถามได้ถ้ายังไม่มี"""
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def ask_ai(caption: str, question: str, api_key: str | None = None) -> str:
    """ส่งคำบรรยายเป็นบริบทพร้อมคำถาม ไปยังโมเดลฟรีของ OpenRouter

    ถ้าถามคำถามเดิมกับคำบรรยายเดิมซ้ำ จะคืนคำตอบจากแคชโดยไม่ยิง API อีก
    เพื่อประหยัดโควตาฟรีที่มีจำกัด (~50 คำขอ/วัน)
    """
    question = (question or "").strip()
    if not question:
        raise AIError("กรุณาพิมพ์คำถามก่อน")

    caption = (caption or "").strip()
    if not caption:
        raise AIError("โพสต์นี้ไม่มีข้อความให้ AI วิเคราะห์")

    api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise AIError(
            "ยังไม่ได้ตั้งค่า OPENROUTER_API_KEY — "
            "คัดลอกไฟล์ .env.example เป็น .env แล้วใส่คีย์จาก openrouter.ai"
        )

    cache_key = (caption, question)
    with _cache_lock:
        if cache_key in _cache:
            return _cache[cache_key]

    prompt = f"เนื้อหาโพสต์:\n{caption}\n\nคำถาม: {question}"
    errors: list[str] = []

    for model in FREE_MODELS:
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": MAX_TOKENS,
                    # หลายรุ่นในลิสต์เป็น reasoning model — ขอไม่เอา reasoning token
                    # กลับมา ลดโทเคนที่เสียเปล่าและลดโอกาสที่ความคิดจะปนมาในคำตอบ
                    "reasoning": {"exclude": True},
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if resp.status_code == 401:
                raise AIError("API key ไม่ถูกต้อง — ตรวจสอบค่า OPENROUTER_API_KEY อีกครั้ง")
            if resp.status_code == 429:
                # ต้นทางจำกัดอัตราชั่วคราว ลองรุ่นถัดไปเลย
                errors.append(f"{model}: rate limited")
                continue
            resp.raise_for_status()

            payload = resp.json()
            _assert_free(model, payload)

            answer = (payload["choices"][0]["message"]["content"] or "").strip()
            if not answer:
                errors.append(f"{model}: ตอบกลับว่าง")
                continue

            with _cache_lock:
                if len(_cache) >= _CACHE_LIMIT:
                    _cache.clear()
                _cache[cache_key] = answer
            return answer

        except AIError:
            raise
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            errors.append(f"{model}: {type(exc).__name__}")
            continue

    raise AIError(
        "โมเดลฟรีใช้ไม่ได้ทั้งหมด (อาจหมดโควตารายวันหรือรายชื่อรุ่นเปลี่ยนไปแล้ว) "
        "— ลองเช็ครุ่นล่าสุดที่ openrouter.ai/models"
    )


def clear_cache() -> None:
    """ล้างแคชคำตอบ — ใช้ในเทสต์"""
    with _cache_lock:
        _cache.clear()
