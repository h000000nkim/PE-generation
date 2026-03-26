"""
URL 검증 모듈
- UTM / AI 추적 파라미터 제거
- 실제 접속 가능 여부 확인
"""

import requests
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "source", "ref", "referrer", "session_id",
    "fbclid", "gclid", "msclkid", "ttclid",
    "mc_cid", "mc_eid", "_hsenc", "_hsmi",
}

AI_KEYWORDS = {"gpt", "openai", "chatgpt", "claude", "ai", "llm"}


def clean_url(url: str) -> dict:
    parsed     = urlparse(url)
    params     = parse_qs(parsed.query, keep_blank_values=True)
    removed    = []
    suspicious = []
    clean      = {}

    for k, v in params.items():
        val = v[0] if v else ""
        k_l = k.lower()
        v_l = val.lower()

        is_ai = any(kw in k_l or kw in v_l for kw in AI_KEYWORDS)
        if is_ai:
            suspicious.append(f"{k}={val}")

        if k_l in TRACKING_PARAMS:
            removed.append(f"{k}={val}")
        else:
            clean[k] = v

    clean_query = urlencode(clean, doseq=True)
    clean_url   = urlunparse(parsed._replace(query=clean_query))

    return {
        "original":       url,
        "cleaned":        clean_url,
        "removed":        removed,
        "suspicious_ai":  suspicious,
        "was_modified":   url != clean_url
    }


def verify_url(url: str, timeout: int = 8) -> dict:
    """실제 접속 가능 여부 확인"""
    cleaned = clean_url(url)
    target  = cleaned["cleaned"]

    try:
        resp = requests.head(target, timeout=timeout, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
        accessible = resp.status_code < 400
        status     = resp.status_code
    except requests.exceptions.Timeout:
        accessible, status = False, "timeout"
    except Exception as e:
        accessible, status = False, str(e)

    return {
        **cleaned,
        "accessible":    accessible,
        "http_status":   status,
    }
