"""
Notion 비공식 API 파서 (비동기 병렬 버전)
"""

import os
import asyncio
import time
import requests
import httpx
from typing import Optional

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent":   "Mozilla/5.0"
}
NOTION_BASE   = "https://www.notion.so/api/v3"
COLLECTION_ID = "d25a15be-d215-4ad0-ab35-618729fdd0b3"
SPACE_ID      = "02ad9178-8750-46bf-aa9e-e5d704cecb8a"
VIEW_ID       = "032050be-e46c-4403-8ccc-5556016e40c9"

# 대시보드 — 담당 멘토 필터용
DASHBOARD_VIEW_ID = "21146991-dbbd-808c-b149-000cb8eff257"
MY_USER_ID        = "0705e077-d8dc-4ff5-b0ef-5e45c4e65477"   # 훈 김
MENTOR_PROP_KEY   = "~~_I"

# 내 과업 캐시 (TTL: 30분) + 디스크 영속화
import json as _json
_CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspaces", ".tasks_cache.json")
_my_tasks_cache: dict = {"tasks": None, "ts": 0.0, "loading": False}
MY_TASKS_TTL = 1800

# 서버 시작 시 디스크 캐시 로드
try:
    if os.path.exists(_CACHE_FILE):
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            _disk = _json.load(f)
        _my_tasks_cache["tasks"] = _disk.get("tasks")
        _my_tasks_cache["ts"] = _disk.get("ts", 0.0)
except Exception:
    pass


def _get_text(props: dict, key: str) -> str:
    chunks = props.get(key, [])
    return "".join(str(c[0]) for c in chunks if isinstance(c, list) and c)


def _get_date(props: dict, key: str) -> str:
    """date 필드에서 start_date 문자열 추출"""
    for chunk in props.get(key, []):
        if not isinstance(chunk, list) or len(chunk) < 2:
            continue
        for attr in chunk[1] if isinstance(chunk[1], list) else []:
            if isinstance(attr, list) and len(attr) >= 2 and attr[0] == "d":
                d = attr[1]
                if isinstance(d, dict):
                    return d.get("start_date", "")
    return ""


def _get_files(props: dict, key: str) -> tuple[list, list]:
    """file 필드에서 (names, urls) 추출"""
    names, urls = [], []
    for chunk in props.get(key, []):
        if not isinstance(chunk, list) or not chunk:
            continue
        name = str(chunk[0])
        if name == ",":
            continue
        names.append(name)
        if len(chunk) > 1 and isinstance(chunk[1], list):
            for attr in chunk[1]:
                if isinstance(attr, list) and len(attr) >= 2 and attr[0] == "a":
                    urls.append(attr[1])
    return names, urls


def _get_relation_id(props: dict, key: str) -> str:
    """relation 필드에서 첫 번째 연결된 페이지 ID 추출"""
    for chunk in props.get(key, []):
        if isinstance(chunk, list) and len(chunk) > 1 and isinstance(chunk[1], list):
            for item in chunk[1]:
                if isinstance(item, list) and len(item) >= 3 and item[0] == "p":
                    return item[1]
    return ""


# 네임택 collection schema: key → 표시 이름 매핑
# (스키마에 없는 실측 키도 포함, 불필요한 checkbox/formula/relation 제외)
_NT_SCHEMA: dict[str, str] = {
    "G_Ne":  "학생명",
    "JoO@":  "학년",
    "P<YH":  "진로",
    "ualG":  "학교",
    "Zkps":  "학생코드",
    "`zyo":  "등록여부",
    "ntTg":  "탐구 주제 이력",
    "HR~K":  "시험범위 / 수업내용",
    "BBel":  "전화번호",
    "{`IL":  "전화번호2",
    "sEss":  "플래그",
    "xFw<":  "동명이인",
    "O]eT":  "목표 학과",
    "CQqT":  "소속",
    "nR|}":  "_file_bio",       # 생기부 파일 (file 타입 — 별도 처리)
}
# 숨길 checkbox / formula / relation / 운영 키
_NT_SKIP = {"DqMh","LZ|d","S|zF","Au=i","jnKc","nfig","xKxD","{VG~",
            "sFYD","o\\dt",":?PH","De>:","title","Kk>H"}


def _fetch_past_tasks_summary(task_ids: list) -> list:
    """과거 과제 ID 목록에서 제목/과목/상태/학기 요약 반환 (50개씩 배치)"""
    results = []
    for i in range(0, len(task_ids), 50):
        batch = task_ids[i:i + 50]
        try:
            r = requests.post(
                f"{NOTION_BASE}/syncRecordValues",
                json={"requests": [
                    {"pointer": {"table": "block", "id": bid}, "version": -1}
                    for bid in batch
                ]},
                headers=HEADERS, timeout=20
            )
            if r.status_code != 200:
                continue
            blocks = r.json().get("recordMap", {}).get("block", {})
        except Exception:
            continue
        for bid in batch:
            props = blocks.get(bid, {}).get("value", {}).get("properties", {})
            if not props:
                continue
            results.append({
                "block_id":  bid,
                "title":     _get_text(props, "title"),
                "subject":   _get_text(props, "mGaa"),
                "status":    _get_text(props, "owtr"),
                "semester":  _get_text(props, "wuL:"),
                "due_date":  _get_date(props, "<odt"),
            })
    return results


def _fetch_nametag(nametag_id: str) -> dict:
    """네임택 페이지의 모든 properties를 동적으로 파싱해 반환"""
    try:
        resp = requests.post(
            f"{NOTION_BASE}/loadPageChunk",
            json={"pageId": nametag_id, "limit": 50,
                  "cursor": {"stack": []}, "chunkNumber": 0, "verticalColumns": False},
            headers=HEADERS, timeout=10
        )
        if resp.status_code != 200:
            return {}
        nt = (resp.json()
                  .get("recordMap", {})
                  .get("block", {})
                  .get(nametag_id, {})
                  .get("value", {})
                  .get("properties", {}))

        bio_names, bio_urls = _get_files(nt, "nR|}")
        # 생기부 파일은 네임택 블록 기준으로 signed URL 처리
        signed_bio = get_signed_urls(bio_urls, nametag_id)
        bio_files = [
            {"name": n, "url": u}
            for n, u in zip(bio_names, signed_bio)
            if u
        ]

        # sFYD: 수행평가 관리 역방향 관계 → 이 학생의 모든 과제 ID
        past_task_ids = []
        for chunk in nt.get("sFYD", []):
            if isinstance(chunk, list) and len(chunk) > 1 and isinstance(chunk[1], list):
                for item in chunk[1]:
                    if isinstance(item, list) and len(item) >= 2 and item[0] == "p":
                        past_task_ids.append(item[1])
        past_tasks = _fetch_past_tasks_summary(past_task_ids) if past_task_ids else []

        # 고정 키 추출 (상세 페이지에서 위치 고정이 필요한 필드)
        fixed = {
            "name":          _get_text(nt, "G_Ne"),
            "grade_nt":      _get_text(nt, "JoO@"),
            "major":         _get_text(nt, "P<YH"),
            "school":        _get_text(nt, "ualG"),
            "student_code":  _get_text(nt, "Zkps"),
            "reg_status":    _get_text(nt, "`zyo"),
            "bio_direction": _get_text(nt, "ntTg"),
            "study_range":   _get_text(nt, "HR~K"),
            "phone":         _get_text(nt, "BBel"),
            "phone2":        _get_text(nt, "{`IL"),
            "flag":          _get_text(nt, "sEss"),
            "alias":         _get_text(nt, "xFw<"),
            "target_dept":   _get_text(nt, "O]eT"),
            "affiliation":   _get_text(nt, "CQqT"),
            "bio_files":     bio_files,
            "past_tasks":    past_tasks,
            "_bio_names":    [],
            "_bio_urls":     [],
        }

        # 스키마에 정의되지 않은 추가 텍스트 필드 동적 수집
        known_keys = set(_NT_SCHEMA) | _NT_SKIP
        extra = []
        for key, val_raw in nt.items():
            if key in known_keys:
                continue
            text = _get_text(nt, key)
            # relation 값("‣") 또는 빈 값 제외
            cleaned = text.strip().replace("‣", "").strip()
            if cleaned:
                extra.append({"key": key, "value": cleaned})

        fixed["extra_fields"] = extra
        return fixed
    except Exception:
        return {}


def _parse_props(block_id: str, props: dict) -> dict:
    # 평가기준 파일
    att_names, att_urls = _get_files(props, "gAMl")
    # 수행평가 가이드 파일
    guide_names, guide_urls = _get_files(props, "mPfP")

    # 네임택 학생 정보
    student = {}
    nametag_id = _get_relation_id(props, "Qpmm")
    if nametag_id:
        student = _fetch_nametag(nametag_id)

    return {
        # 기본
        "block_id":         block_id,
        "title":            _get_text(props, "title"),
        # 학생 정보
        "name":          student.get("name", ""),
        "grade":         _get_text(props, "Tv~<") or student.get("grade_nt", ""),
        "major":         student.get("major", ""),
        "school":        student.get("school", ""),
        "student_code":  student.get("student_code", ""),
        "reg_status":    student.get("reg_status", ""),
        "bio_direction": student.get("bio_direction", ""),
        "study_range":   student.get("study_range", ""),
        "phone":         student.get("phone", ""),
        "phone2":        student.get("phone2", ""),
        "flag":          student.get("flag", ""),
        "alias":         student.get("alias", ""),
        "target_dept":   student.get("target_dept", ""),
        "affiliation":   student.get("affiliation", ""),
        "extra_fields":  student.get("extra_fields", []),
        "bio_files":     student.get("bio_files", []),
        "past_tasks":    student.get("past_tasks", []),
        "_bio_names":    [],
        "_bio_urls":     [],
        # 과제 정보
        "subject":          _get_text(props, "mGaa"),
        "semester":         _get_text(props, "wuL:"),
        "status":           _get_text(props, "owtr"),
        "activity":         _get_text(props, "CrVV"),
        "submit_type":      _get_text(props, "Dogm"),
        "apply_date":       _get_date(props, "MmFA"),
        "due_date":         _get_date(props, "<odt"),
        "req_check":        _get_text(props, "VckQ"),
        "eval_check":       _get_text(props, "i[}D"),
        "request_msg":      _get_text(props, "RSt|"),
        "keyword":          _get_text(props, "UfkI"),
        "setech":           _get_text(props, "RuwY"),
        "note":             _get_text(props, "j^}="),
        # 파일
        "_att_names":       att_names,
        "_att_urls":        att_urls,
        "_guide_names":     guide_names,
        "_guide_urls":      guide_urls,
    }


def get_signed_urls(file_urls: list, block_id: str) -> list:
    if not file_urls:
        return []
    internal = [u for u in file_urls if u.startswith("attachment:")]
    external = [u for u in file_urls if not u.startswith("attachment:")]
    signed = list(external)
    if internal:
        try:
            resp = requests.post(
                f"{NOTION_BASE}/getSignedFileUrls",
                json={"urls": [
                    {"url": u, "permissionRecord": {"table": "block", "id": block_id}}
                    for u in internal
                ]},
                headers=HEADERS, timeout=15
            )
            if resp.status_code == 200:
                signed = resp.json().get("signedUrls", []) + external
        except Exception:
            pass
    return signed


def parse_task_from_block(block_id: str) -> dict:
    resp = requests.post(
        f"{NOTION_BASE}/loadPageChunk",
        json={"pageId": block_id, "limit": 100,
              "cursor": {"stack": []}, "chunkNumber": 0, "verticalColumns": False},
        headers=HEADERS, timeout=15
    )
    resp.raise_for_status()
    data  = resp.json()
    block = data.get("recordMap", {}).get("block", {}).get(block_id, {}).get("value", {})
    task  = _parse_props(block_id, block.get("properties", {}))

    # 평가기준 파일
    signed_att = get_signed_urls(task["_att_urls"], block_id)
    task["attachments"] = [
        {"name": n, "url": u}
        for n, u in zip(task["_att_names"], signed_att)
    ]
    del task["_att_names"], task["_att_urls"]

    # 수행평가 가이드 파일
    signed_guide = get_signed_urls(task["_guide_urls"], block_id)
    task["guide_files"] = [
        {"name": n, "url": u}
        for n, u in zip(task["_guide_names"], signed_guide)
    ]
    del task["_guide_names"], task["_guide_urls"]

    # 생기부 파일 — _fetch_nametag 안에서 이미 처리됨
    del task["_bio_names"], task["_bio_urls"]

    return task


async def _load_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, page_id: str) -> Optional[dict]:
    async with sem:
        try:
            resp = await client.post(
                f"{NOTION_BASE}/loadPageChunk",
                json={"pageId": page_id, "limit": 30,
                      "cursor": {"stack": []}, "chunkNumber": 0, "verticalColumns": False},
                timeout=12
            )
            if resp.status_code != 200:
                return None
            data  = resp.json()
            block = data.get("recordMap", {}).get("block", {}).get(page_id, {}).get("value", {})
            props = block.get("properties", {})
            if not props:
                return None
            task = _parse_props(page_id, props)
            # 목록에서는 첨부파일 URL 불필요 — 메타만 반환
            task.pop("_att_names", None)
            task.pop("_att_urls", None)
            task["attachments"] = []
            return task if task["title"] else None
        except Exception:
            return None


async def _fetch_all(block_ids: list, concurrency: int = 12) -> list:
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(headers=HEADERS) as client:
        results = await asyncio.gather(*[_load_one(client, sem, bid) for bid in block_ids])
    return [t for t in results if t]


def fetch_task_list(page_id: str, limit: int = 50) -> list:
    resp = requests.post(
        f"{NOTION_BASE}/queryCollection",
        json={
            "collection":     {"id": COLLECTION_ID, "spaceId": SPACE_ID},
            "collectionView": {"id": VIEW_ID,        "spaceId": SPACE_ID},
            "query": {},
            "loader": {
                "type": "reducer",
                "reducers": {"collection_group_results": {"type": "results", "limit": limit}},
                "userTimeZone": "Asia/Seoul"
            }
        },
        headers=HEADERS, timeout=15
    )
    resp.raise_for_status()
    data      = resp.json()
    block_ids = (data.get("result", {})
                     .get("reducerResults", {})
                     .get("collection_group_results", {})
                     .get("blockIds", []))
    if not block_ids:
        return []
    return asyncio.run(_fetch_all(block_ids))


# ──────────────────────────────────────────────
# 내 과업 목록 (담당 멘토 필터)
# ──────────────────────────────────────────────

def _extract_mentor_user_ids(props: dict) -> list:
    user_ids = []
    for chunk in props.get(MENTOR_PROP_KEY, []):
        if isinstance(chunk, list) and len(chunk) >= 2 and isinstance(chunk[1], list):
            for attr in chunk[1]:
                if isinstance(attr, list) and len(attr) >= 2 and attr[0] == "u":
                    user_ids.append(attr[1])
    return user_ids


def _fetch_my_tasks_blocking() -> list:
    """전체 컬렉션을 배치 스캔해 MY_USER_ID가 담당멘토인 블록만 반환"""
    # 1. block_id 목록
    resp = requests.post(
        f"{NOTION_BASE}/queryCollection",
        json={
            "collection":     {"id": COLLECTION_ID,       "spaceId": SPACE_ID},
            "collectionView": {"id": DASHBOARD_VIEW_ID,   "spaceId": SPACE_ID},
            "query": {},
            "loader": {
                "type": "reducer",
                "reducers": {"collection_group_results": {"type": "results", "limit": 9999}},
                "userTimeZone": "Asia/Seoul"
            }
        },
        headers=HEADERS, timeout=20
    )
    resp.raise_for_status()
    block_ids = (resp.json().get("result", {})
                            .get("reducerResults", {})
                            .get("collection_group_results", {})
                            .get("blockIds", []))

    # 2. 50개씩 배치 fetch → 멘토 필터
    tasks = []
    for i in range(0, len(block_ids), 50):
        batch = block_ids[i:i + 50]
        try:
            r = requests.post(
                f"{NOTION_BASE}/syncRecordValues",
                json={"requests": [
                    {"pointer": {"table": "block", "id": bid}, "version": -1}
                    for bid in batch
                ]},
                headers=HEADERS, timeout=20
            )
            if r.status_code != 200:
                continue
            blocks = r.json().get("recordMap", {}).get("block", {})
        except Exception:
            continue

        for bid in batch:
            props = blocks.get(bid, {}).get("value", {}).get("properties", {})
            if not props:
                continue
            if MY_USER_ID not in _extract_mentor_user_ids(props):
                continue
            tasks.append({
                "block_id": bid,
                "title":       _get_text(props, "title"),
                "subject":     _get_text(props, "mGaa"),
                "grade":       _get_text(props, "Tv~<"),
                "semester":    _get_text(props, "wuL:"),
                "status":      _get_text(props, "owtr"),
                "activity":    _get_text(props, "CrVV"),
                "submit_type": _get_text(props, "Dogm"),
                "link": f"https://www.notion.so/{bid.replace('-', '')}",
            })

    return tasks


def _do_fetch_and_cache() -> list:
    """Notion에서 실제로 fetch 후 캐시에 저장"""
    global _my_tasks_cache
    _my_tasks_cache["loading"] = True
    try:
        tasks = _fetch_my_tasks_blocking()
        _my_tasks_cache["tasks"] = tasks
        _my_tasks_cache["ts"]    = time.time()
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            _json.dump({"tasks": tasks, "ts": _my_tasks_cache["ts"]}, f, ensure_ascii=False)
        return tasks
    except Exception:
        return _my_tasks_cache.get("tasks") or []
    finally:
        _my_tasks_cache["loading"] = False


def get_my_tasks(force: bool = False) -> dict:
    """캐시된 내 과업 목록 반환. {'status': 'ok'|'loading', 'tasks': [...]}"""
    global _my_tasks_cache
    now = time.time()

    # force=True: 동기로 즉시 재조회
    if force:
        tasks = _do_fetch_and_cache()
        return {"status": "ok", "tasks": tasks}

    # 캐시 유효
    if _my_tasks_cache["tasks"] is not None:
        if now - _my_tasks_cache["ts"] < MY_TASKS_TTL:
            return {"status": "ok", "tasks": _my_tasks_cache["tasks"]}

    # 이미 로딩 중
    if _my_tasks_cache["loading"]:
        cached = _my_tasks_cache["tasks"]
        if cached is not None:
            return {"status": "ok", "tasks": cached}
        return {"status": "loading", "tasks": []}

    # 백그라운드 스레드에서 갱신 (일반 TTL 만료 시)
    import threading
    threading.Thread(target=_do_fetch_and_cache, daemon=True).start()

    if _my_tasks_cache["tasks"] is not None:
        return {"status": "ok", "tasks": _my_tasks_cache["tasks"]}
    return {"status": "loading", "tasks": []}
