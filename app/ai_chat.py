"""ถามตอบและสรุปเนื้อหาจากคำบรรยายโพสต์ ผ่านโมเดลฟรีของ OpenRouter"""

import os
import threading

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# รุ่นฟรี เรียงตาม Intelligence Index ของ Artificial Analysis (มากไปน้อย)
#
# ที่มาของลำดับ — ไม่ได้จัดเอง แต่อ้างอิง 2 แหล่งประกอบกัน:
#   1. คะแนนความสามารถ: https://artificialanalysis.ai/leaderboards/models
#      (ดึงคะแนน intelligenceIndex ของ 591 โมเดล เทียบกับรายชื่อรุ่นฟรี)
#   2. ราคา: https://openrouter.ai/api/v1/models
#      (คัดเฉพาะรุ่นที่ราคาเป็น 0 ทุกช่อง — เหลือ 19 จาก 410 โมเดล)
# แล้วทดสอบจริงด้วยโจทย์ภาษาไทย 2 ข้อต่อรุ่น ตัดตัวที่ตอบผิดรูปแบบออก
#
# ตัวเลขท้ายบรรทัด = คะแนน AA / เวลาตอบเฉลี่ยที่วัดได้จริง (2026-08-13)
# ห้ามใส่โมเดลที่ไม่ลงท้าย ":free" เด็ดขาด (มีเทสต์คุมไว้) เพราะจะเริ่มมีค่าใช้จ่าย
FREE_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",   # AA 38.3 · 9.3s · ผ่านทดสอบไทย 2/2
    "google/gemma-4-31b-it:free",               # AA 29.7 · มักโดน 429 ต้นทาง ระบบข้ามให้เอง
    "google/gemma-4-26b-a4b-it:free",           # AA 26.1 · 2.1s · โดน 429 เป็นช่วง ๆ
    "nvidia/nemotron-3-super-120b-a12b:free",   # AA 25.7 · 28.2s · ผ่าน 2/2 แต่ช้า
    "inclusionai/ling-3.0-tiny:free",           # AA 24.5 · 2.0s · ผ่าน 2/2 เร็วสุดในกลุ่ม
    "cohere/north-mini-code:free",              # AA 20.2 · 8.4s · ผ่าน 2/2
    "openai/gpt-oss-20b:free",                  # AA 15.2 · 16.6s · ผ่าน 2/2
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

# จำกัดความยาวคำตอบ กันโมเดลร่ายยาวและกันโควตาหมดเร็ว
MAX_TOKENS = 500

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
                timeout=60,
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
