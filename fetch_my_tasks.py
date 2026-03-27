"""
DASHBOARD에서 담당멘토 = 훈 김 / 김훈 / h000000nkim@gmail.com 인 과업 링크 추출
"""

import requests
import json

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0"
}
NOTION_BASE = "https://www.notion.so/api/v3"

DASHBOARD_PAGE_ID = "6102e4c2-aca1-4f6b-a378-1a29e2dee3d0"

MY_MENTOR_NAMES = {"훈 김", "김훈", "h000000nkim@gmail.com"}


def get_text(props: dict, key: str) -> str:
    chunks = props.get(key, [])
    return "".join(str(c[0]) for c in chunks if isinstance(c, list) and c)


def load_page_chunk(page_id: str, limit: int = 100) -> dict:
    resp = requests.post(
        f"{NOTION_BASE}/loadPageChunk",
        json={
            "pageId": page_id,
            "limit": limit,
            "cursor": {"stack": []},
            "chunkNumber": 0,
            "verticalColumns": False
        },
        headers=HEADERS,
        timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def find_collection_info(page_id: str):
    """DASHBOARD 페이지에서 collection_id, space_id, view_id 추출"""
    data = load_page_chunk(page_id, limit=100)
    record_map = data.get("recordMap", {})

    # collection_id: recordMap['collection'] 첫 번째 키
    collections = record_map.get("collection", {})
    collection_id = next(iter(collections), None)

    # view_id: collection_view 블록의 view_ids 첫 번째
    view_id = None
    space_id = None
    blocks = record_map.get("block", {})
    for bid, bval in blocks.items():
        val = bval.get("value", {})
        btype = val.get("type", "")
        if btype in ("collection_view", "collection_view_page"):
            view_ids = val.get("view_ids", [])
            view_id = view_ids[0] if view_ids else None
            space_id = val.get("space_id")
            print(f"  [발견] block={bid}, type={btype}")
            print(f"         collection_id={collection_id}")
            print(f"         view_id={view_id}")
            print(f"         space_id={space_id}")
            break

    return collection_id, view_id, space_id


def get_collection_schema(collection_id: str, space_id: str) -> dict:
    """컬렉션 스키마(컬럼 목록) 가져오기"""
    resp = requests.post(
        f"{NOTION_BASE}/syncRecordValues",
        json={
            "requests": [
                {"pointer": {"table": "collection", "id": collection_id, "spaceId": space_id}, "version": -1}
            ]
        },
        headers=HEADERS,
        timeout=15
    )
    if resp.status_code != 200:
        return {}
    data = resp.json()
    record_map = data.get("recordMap", {})
    coll_block = record_map.get("collection", {}).get(collection_id, {})
    return coll_block.get("value", {}).get("schema", {})


def query_block_ids(collection_id: str, view_id: str, space_id: str, limit: int = 9999) -> list:
    """queryCollection으로 block ID 목록만 가져오기"""
    resp = requests.post(
        f"{NOTION_BASE}/queryCollection",
        json={
            "collection": {"id": collection_id, "spaceId": space_id},
            "collectionView": {"id": view_id, "spaceId": space_id},
            "query": {},
            "loader": {
                "type": "reducer",
                "reducers": {
                    "collection_group_results": {"type": "results", "limit": limit}
                },
                "userTimeZone": "Asia/Seoul"
            }
        },
        headers=HEADERS,
        timeout=20
    )
    resp.raise_for_status()
    data = resp.json()
    return (data.get("result", {})
                .get("reducerResults", {})
                .get("collection_group_results", {})
                .get("blockIds", []))


def fetch_blocks_batch(block_ids: list, batch_size: int = 50) -> dict:
    """syncRecordValues로 블록 properties 배치 조회"""
    all_blocks = {}
    for i in range(0, len(block_ids), batch_size):
        batch = block_ids[i:i + batch_size]
        resp = requests.post(
            f"{NOTION_BASE}/syncRecordValues",
            json={"requests": [
                {"pointer": {"table": "block", "id": bid}, "version": -1}
                for bid in batch
            ]},
            headers=HEADERS,
            timeout=20
        )
        if resp.status_code == 200:
            blocks = resp.json().get("recordMap", {}).get("block", {})
            all_blocks.update(blocks)
        print(f"  배치 {i // batch_size + 1}/{(len(block_ids) - 1) // batch_size + 1} 완료 ({len(all_blocks)}개)")
    return all_blocks


_user_cache: dict = {}


def get_user_info(user_id: str) -> dict:
    """유저 ID로 이름/이메일 조회 (캐시)"""
    if user_id in _user_cache:
        return _user_cache[user_id]
    try:
        resp = requests.post(
            f"{NOTION_BASE}/syncRecordValues",
            json={"requests": [{"pointer": {"table": "notion_user", "id": user_id}, "version": -1}]},
            headers=HEADERS, timeout=10
        )
        if resp.status_code == 200:
            val = resp.json().get("recordMap", {}).get("notion_user", {}).get(user_id, {}).get("value", {})
            _user_cache[user_id] = val
            return val
    except Exception:
        pass
    return {}


def extract_mentor_user_ids(props: dict, mentor_key: str) -> list:
    """담당멘토 person 필드에서 유저 ID 목록 추출"""
    # 형식: [["‣", [["u", "USER_ID"]]]]
    chunks = props.get(mentor_key, [])
    user_ids = []
    for chunk in chunks:
        if not isinstance(chunk, list) or len(chunk) < 2:
            continue
        attrs = chunk[1]
        if not isinstance(attrs, list):
            continue
        for attr in attrs:
            if isinstance(attr, list) and len(attr) >= 2 and attr[0] == "u":
                user_ids.append(attr[1])
    return user_ids


def find_mentor_key(schema: dict) -> str | None:
    """스키마에서 '담당멘토' 컬럼 키 찾기"""
    for key, val in schema.items():
        name = val.get("name", "")
        if "멘토" in name or "mentor" in name.lower():
            print(f"  [스키마] 담당멘토 키={key}, name={name}, type={val.get('type')}")
            return key
    # 못 찾으면 스키마 전체 출력
    print("  [스키마] '멘토' 컬럼을 찾지 못했습니다. 전체 스키마:")
    for k, v in schema.items():
        print(f"    {k}: {v.get('name')} ({v.get('type')})")
    return None


def main():
    print("=" * 60)
    print("DASHBOARD 페이지 정보 로드 중...")
    collection_id, view_id, space_id = find_collection_info(DASHBOARD_PAGE_ID)

    if not collection_id or not view_id:
        print("[오류] collection_id 또는 view_id를 찾을 수 없습니다.")
        return

    print(f"\n컬렉션 스키마 로드 중...")
    schema = get_collection_schema(collection_id, space_id)

    mentor_key = find_mentor_key(schema)
    if not mentor_key:
        print("[오류] 담당멘토 컬럼을 스키마에서 찾지 못했습니다.")
        return

    print(f"\n전체 과업 목록 쿼리 중...")
    block_ids = query_block_ids(collection_id, view_id, space_id, limit=9999)
    print(f"  총 {len(block_ids)}개 블록 발견")
    print(f"\n블록 properties 배치 로드 중...")
    blocks = fetch_blocks_batch(block_ids)

    my_tasks = []
    for bid in block_ids:
        block_val = blocks.get(bid, {}).get("value", {})
        props = block_val.get("properties", {})
        if not props:
            continue

        user_ids = extract_mentor_user_ids(props, mentor_key)
        if not user_ids:
            continue

        matched_mentor = None
        for uid in user_ids:
            info = get_user_info(uid)
            name = info.get("name", "")
            email = info.get("email", "")
            if name in MY_MENTOR_NAMES or email in MY_MENTOR_NAMES:
                matched_mentor = f"{name} ({email})"
                break

        if not matched_mentor:
            continue

        title = get_text(props, "title")
        notion_link = f"https://www.notion.so/{bid.replace('-', '')}"
        my_tasks.append({
            "block_id": bid,
            "title": title,
            "mentor": matched_mentor,
            "link": notion_link
        })

    print(f"\n{'=' * 60}")
    print(f"담당멘토 매칭 과업: {len(my_tasks)}개")
    print("=" * 60)
    for t in my_tasks:
        print(f"\n제목: {t['title']}")
        print(f"멘토: {t['mentor']}")
        print(f"링크: {t['link']}")

    # JSON 저장
    with open("my_tasks.json", "w", encoding="utf-8") as f:
        json.dump(my_tasks, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: my_tasks.json ({len(my_tasks)}개)")


if __name__ == "__main__":
    main()
