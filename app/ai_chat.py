"""ถามตอบ / สรุปเนื้อหาจากแคปชั่น ผ่านโมเดลฟรีของ OpenRouter"""

import os
import threading

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# รุ่นฟรี เรียงลำดับ fallback — รายการนี้เปลี่ยนบ่อยมาก
# ยืนยันล่าสุด 2026-08-13 จาก https://openrouter.ai/api/v1/models (กรอง ":free")
FREE_MODELS = [
    "liquid/lfm-2.5-2.6b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "inclusionai/ling-3.0-tiny:free",
    "poolside/laguna-s-2.1:free",
    "poolside/laguna-xs-2.1:free",
]

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


def has_api_key() -> bool:
    """เช็กว่ามี API key ตั้งไว้หรือยัง — ให้ UI ซ่อน/ปิดช่องถามได้ถ้ายังไม่มี"""
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def ask_ai(caption: str, question: str, api_key: str | None = None) -> str:
    """ส่งแคปชั่นเป็น context พร้อมคำถาม ไปยังโมเดลฟรีของ OpenRouter

    ถ้าถามคำถามเดิมกับแคปชั่นเดิมซ้ำ จะคืนคำตอบจากแคชโดยไม่ยิง API อีก
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
                },
                timeout=60,
            )
            if resp.status_code == 401:
                raise AIError("API key ไม่ถูกต้อง — ตรวจสอบค่า OPENROUTER_API_KEY อีกครั้ง")
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"].strip()
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
