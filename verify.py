"""
산출물 검증 CLI — claude -p 없이도 웹 API를 통해 검증 실행/조회 가능

사용법:
  uv run python verify.py                     # 결과 있는 전체 과제 검증
  uv run python verify.py <block_id>          # 특정 과제 검증
  uv run python verify.py --status            # 전체 검증 상태 조회
  uv run python verify.py --status <block_id> # 특정 과제 검증 결과 조회
"""

import sys
import json
import time
import requests

BASE = "http://localhost:8000"


def get_tasks():
    resp = requests.get(f"{BASE}/api/my-tasks")
    data = resp.json()
    if data.get("status") != "ok":
        print("과제 목록을 불러올 수 없습니다. 서버가 실행 중인지 확인하세요.")
        sys.exit(1)
    return data["tasks"]


def run_verify(block_id: str, title: str = "") -> bool:
    resp = requests.post(f"{BASE}/api/verify/{block_id}")
    data = resp.json()
    if not data.get("success"):
        print(f"  [{block_id[:8]}] {title} — 검증 실행 실패: {data.get('message', '산출물 없음')}")
        return False
    print(f"  [{block_id[:8]}] {title} — 검증 시작됨")
    return True


def wait_for_completion(block_id: str, timeout: int = 300) -> dict | None:
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"{BASE}/api/job-status/{block_id}")
        data = resp.json()
        if data.get("status") != "running":
            return data
        elapsed = data.get("elapsed_seconds", 0)
        print(f"    진행 중... {elapsed}초", end="\r")
        time.sleep(3)
    print(f"    타임아웃 ({timeout}초)")
    return None


def get_verification(block_id: str) -> dict | None:
    resp = requests.get(f"{BASE}/api/verify/{block_id}")
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("status") == "not_found":
        return None
    return data


def print_verification(block_id: str, title: str, v: dict):
    status_icon = {"pass": "PASS", "fail": "FAIL", "warning": "WARN"}.get(v.get("status"), "?")
    score = v.get("score", "?")
    summary = v.get("summary", "")
    print(f"  [{block_id[:8]}] {title}")
    print(f"    {status_icon} ({score}/100) — {summary}")

    checks = v.get("checks", [])
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warning"]
    if fails:
        for c in fails:
            print(f"    FAIL [{c['category']}] {c['item']}: {c['detail'][:80]}")
    if warns:
        for c in warns:
            print(f"    WARN [{c['category']}] {c['item']}: {c['detail'][:80]}")

    recs = v.get("recommendations", [])
    if recs:
        print("    개선 제안:")
        for r in recs:
            print(f"      - {r}")
    print()


def cmd_status(block_id: str | None = None):
    tasks = get_tasks()
    if block_id:
        tasks = [t for t in tasks if t["block_id"] == block_id]
    if not tasks:
        print("해당 과제를 찾을 수 없습니다.")
        return

    print(f"\n=== 검증 상태 ({len(tasks)}개 과제) ===\n")
    for t in tasks:
        v = get_verification(t["block_id"])
        if v:
            print_verification(t["block_id"], t.get("title", ""), v)
        else:
            has_result = t.get("has_result") or get_result_exists(t["block_id"])
            tag = "(산출물 없음)" if not has_result else "(미검증)"
            print(f"  [{t['block_id'][:8]}] {t.get('title', '')} — {tag}\n")


def get_result_exists(block_id: str) -> bool:
    resp = requests.get(f"{BASE}/api/result/{block_id}")
    return resp.status_code == 200


def cmd_verify(block_id: str | None = None):
    tasks = get_tasks()

    if block_id:
        tasks = [t for t in tasks if t["block_id"] == block_id]
        if not tasks:
            print("해당 과제를 찾을 수 없습니다.")
            return
    else:
        # 결과가 있는 과제만 필터
        tasks = [t for t in tasks if t.get("has_result")]
        if not tasks:
            print("검증할 산출물이 있는 과제가 없습니다.")
            return

    print(f"\n=== 검증 실행 ({len(tasks)}개 과제) ===\n")

    # 검증 실행
    running = []
    for t in tasks:
        if run_verify(t["block_id"], t.get("title", "")):
            running.append(t)

    if not running:
        print("\n검증할 과제가 없습니다.")
        return

    # 완료 대기
    print(f"\n{len(running)}개 검증 진행 중...\n")
    for t in running:
        print(f"  [{t['block_id'][:8]}] {t.get('title', '')} 대기 중...")
        wait_for_completion(t["block_id"])
        print()

    # 결과 출력
    print(f"\n=== 검증 결과 ===\n")
    for t in running:
        v = get_verification(t["block_id"])
        if v:
            print_verification(t["block_id"], t.get("title", ""), v)
        else:
            print(f"  [{t['block_id'][:8]}] {t.get('title', '')} — 결과 없음\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--status" in args:
        args.remove("--status")
        bid = args[0] if args else None
        cmd_status(bid)
    elif args:
        cmd_verify(args[0])
    else:
        cmd_verify()
