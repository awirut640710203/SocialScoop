"""ถามตอบ / สรุปเนื้อหาจากแคปชั่น ผ่านโมเดลฟรีของ OpenRouter"""

import os
import threading

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# รุ่นฟรีที่คัดแล้ว เรียงตามลำดับ fallback
#
# ทุกตัวต้องมีราคา 0 ทุกช่อง (prompt/completion/request/image/reasoning)
# ยืนยันจาก https://openrouter.ai/api/v1/models และทดสอบจริงด้วยโจทย์ภาษาไทย
# เมื่อ 2026-08-13 — ตัวเลขในวงเล็บคือเวลาตอบที่วัดได้จริง
#
# ห้ามใส่โมเดลที่ไม่ลงท้าย ":free" เด็ดขาด (มีเทสต์คุมไว้) เพราะจะเริ่มมีค่าใช้จ่าย
FREE_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",   # 550B ฉลาดสุดในกลุ่ม ตอบไทยตรง (4.4s)
    "google/gemma-4-26b-a4b-it:free",           # เร็วและตอบไทยดี เหมาะเป็นตัวหลัก (1.4s)
    "nvidia/nemotron-3-nano-30b-a3b:free",      # เร็ว ตอบไทยตรง (1.6s)
    "inclusionai/ling-3.0-tiny:free",           # เร็วสุด ตอบไทยตรง (1.1s)
    "openai/gpt-oss-20b:free",                  # สำรอง ตอบไทยได้ (5.1s)
    "google/gemma-4-31b-it:free",               # ดีแต่ตอนทดสอบโดน rate limit ต้นทาง
]

# โมเดลฟรีที่ทดสอบแล้ว "ห้ามใช้" — บันทึกไว้กันเผลอเพิ่มกลับเข้ามา
#   nvidia/nemotron-3.5-lightning:free  -> พ่น chain-of-thought ภาษาอังกฤษแทนคำตอบ
#   nvidia/nemotron-3-super-120b-a12b:free -> ตอบถูกแต่ใช้เวลา 34 วินาที
#   openrouter/free                     -> auto-router ช้า (22s) และคุมรุ่นไม่ได้
#   liquid/lfm-2.5-2.6b:free            -> ตอบถูกแต่ช้าผิดปกติ (13.5s)
#   google/lyria-3-*                    -> โมเดลสร้างเพลง ไม่ใช่แชท
#   nvidia/nemotron-3.5-content-safety  -> โมเดลกรองเนื้อหา ไม่ใช่แชท

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
                    "max_tokens": MAX_TOKENS,
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
