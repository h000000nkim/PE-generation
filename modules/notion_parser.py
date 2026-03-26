"""
Notion 비공식 API 파서 (비동기 병렬 버전)
"""

import asyncio
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


def _get_text(props: dict, key: str) -> str:
    chunks = props.get(key, [])
    return "".join(str(c[0]) for c in chunks if isinstance(c, list) and c)


def _get_relation_id(props: dict, key: str) -> str:
    """relation 필드에서 연결된 페이지 ID 추출"""
    chunks = props.get(key, [])
    for chunk in chunks:
        if isinstance(chunk, list) and len(chunk) > 1:
            if isinstance(chunk[1], list):
                for item in chunk[1]:
                    if isinstance(item, list) and len(item) >= 3 and item[0] == 'p':
                        return item[1]  # 연결된 페이지 ID
    return ""


def _parse_props(block_id: str, props: dict) -> dict:
    file_raw         = props.get("gAMl", [])
    attachment_names = []
    attachment_urls  = []
    for chunk in file_raw:
        if not isinstance(chunk, list) or not chunk:
            continue
        name = str(chunk[0])
        if name == ",":
            continue
        attachment_names.append(name)
        if len(chunk) > 1 and isinstance(chunk[1], list):
            for attr in chunk[1]:
                if isinstance(attr, list) and len(attr) >= 2 and attr[0] == "a":
                    attachment_urls.append(attr[1])
    # 네임택 relation 조회하여 이름, 진로 가져오기
    name = ""
    major = ""
    nametag_id = _get_relation_id(props, "Qpmm")
    if nametag_id:
        try:
            nametag_resp = requests.post(
                f"{NOTION_BASE}/loadPageChunk",
                json={"pageId": nametag_id, "limit": 30,
                      "cursor": {"stack": []}, "chunkNumber": 0, "verticalColumns": False},
                headers=HEADERS, timeout=10
            )
            if nametag_resp.status_code == 200:
                nametag_data = nametag_resp.json()
                nametag_props = nametag_data.get("recordMap", {}).get("block", {}).get(nametag_id, {}).get("value", {}).get("properties", {})
                name = _get_text(nametag_props, "G_Ne")
                major = _get_text(nametag_props, "P<YH")
        except Exception:
            pass

    return {
        "block_id":    block_id,
        "title":       _get_text(props, "title"),
        "subject":     _get_text(props, "mGaa"),
        "grade":       _get_text(props, "Tv~<"),
        "semester":    _get_text(props, "wuL:"),
        "status":      _get_text(props, "owtr"),
        "activity":    _get_text(props, "CrVV"),
        "submit_type": _get_text(props, "Dogm"),
        "request_msg": _get_text(props, "RSt|"),
        "name":        name,
        "major":       major,
        "_att_names":  attachment_names,
        "_att_urls":   attachment_urls,
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
    signed = get_signed_urls(task["_att_urls"], block_id)
    task["attachments"] = [
        {"name": n, "url": u}
        for n, u in zip(task["_att_names"], signed)
    ]
    del task["_att_names"], task["_att_urls"]
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
