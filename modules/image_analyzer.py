"""
이미지 처리 모듈
- Notion signed URL에서 이미지 다운로드
- Claude API 멀티모달 입력용 base64 변환
- 리사이즈 (토큰 절약)
"""

import requests
import base64
import math
from io import BytesIO
from PIL import Image


MAX_DIM = 1568
MAX_PIXELS = 1_150_000


def download_image(url: str) -> bytes:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content


def resize_for_claude(img: Image.Image) -> Image.Image:
    """Anthropic 공식 기준 리사이즈"""
    w, h = img.size

    if w > MAX_DIM or h > MAX_DIM:
        ratio = min(MAX_DIM / w, MAX_DIM / h)
        w, h = int(w * ratio), int(h * ratio)
        img = img.resize((w, h), Image.LANCZOS)

    if w * h > MAX_PIXELS:
        ratio = (MAX_PIXELS / (w * h)) ** 0.5
        w, h = int(w * ratio), int(h * ratio)
        img = img.resize((w, h), Image.LANCZOS)

    return img


def estimate_tokens(img: Image.Image) -> int:
    w, h = img.size
    tiles = math.ceil(w / 512) * math.ceil(h / 512)
    return tiles * 1750


def image_to_base64(raw: bytes, media_type: str = "image/jpeg") -> dict:
    """Claude API multimodal content block 형식으로 변환"""
    img = Image.open(BytesIO(raw))

    # RGBA → RGB 변환 (JPEG 저장 시 필요)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img = resize_for_claude(img)
    tokens = estimate_tokens(img)

    buf = BytesIO()
    fmt = "JPEG" if "jpeg" in media_type or "jpg" in media_type else "PNG"
    img.save(buf, format=fmt, quality=85)
    b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": b64
        },
        "_meta": {
            "size": img.size,
            "estimated_tokens": tokens
        }
    }


def prepare_images(attachments: list) -> list:
    """
    첨부파일 목록 → Claude API용 이미지 블록 리스트
    실패한 항목은 건너뜀
    """
    results = []
    for att in attachments:
        url  = att.get("url", "")
        name = att.get("name", "")
        if not url:
            continue

        # 미디어 타입 추정
        name_lower = name.lower()
        if name_lower.endswith(".png"):
            media_type = "image/png"
        else:
            media_type = "image/jpeg"

        try:
            raw   = download_image(url)
            block = image_to_base64(raw, media_type)
            block["_meta"]["name"] = name
            results.append(block)
        except Exception as e:
            print(f"[image_analyzer] 이미지 처리 실패 ({name}): {e}")
            continue

    return results
