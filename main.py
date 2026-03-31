"""
수행평가 대시보드 - FastAPI 메인
"""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from modules.notion_parser  import parse_task_from_block, get_my_tasks
from modules.workspace_launcher import (
    create_workspace, build_instruction, launch_background,
    get_result, save_result, get_workspace_path,
    launch_pre_analysis, get_analysis, delete_analysis, launch_revision, get_job_status,
    get_locked_ids, set_locked_ids, get_memo_log, get_warning,
    run_verification, get_verification_status,
)

import json
import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

@asynccontextmanager
async def lifespan(app):
    asyncio.get_event_loop().run_in_executor(None, get_my_tasks)
    yield


app = FastAPI(title="수행평가 대시보드", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")




# ──────────────────────────────────────────────
# 1. 대시보드
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html", context={})


@app.get("/api/my-tasks")
async def api_my_tasks(refresh: bool = False):
    """내 과업 목록 반환 (캐시 / 로딩 중이면 status=loading)"""
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_my_tasks(force=refresh)
    )
    # 잠금 상태 + 분석 상태 추가 + detail 캐시 미리 워밍
    if result.get("status") == "ok":
        def _enrich_tasks(tasks):
            locked = get_locked_ids()
            for t in tasks:
                try:
                    t["locked"] = t["block_id"] in locked
                    t["has_analysis"] = get_analysis(t["block_id"]) is not None
                    t["has_result"] = get_result(t["block_id"]) is not None
                    job = get_job_status(t["block_id"])
                    t["job_status"] = job["status"] if job else None
                    t["job_label"] = job["label"] if job else None
                    t["job_elapsed"] = job["elapsed_seconds"] if job else None
                    t["job_start_time"] = job.get("jobs", [{}])[0].get("elapsed_seconds", 0) if job and job.get("status") == "running" else None
                    t["verify_status"] = get_verification_status(t["block_id"])
                    t["job_warning"] = job.get("warning") if job else None
                    # memo_log에서 단계별 횟수 집계
                    logs = get_memo_log(t["block_id"])
                    t["count_analysis"] = sum(1 for l in logs if l.get("action") == "사전분석")
                    t["count_draft"] = sum(1 for l in logs if l.get("action") == "초안 작성")
                    t["count_revision"] = sum(1 for l in logs if l.get("action") == "수정 요청")
                    t["count_verify"] = sum(1 for l in logs if l.get("verification"))
                    last_v = next((l.get("verification") for l in reversed(logs) if l.get("verification")), None)
                    t["verify_score"] = last_v.get("score") if isinstance(last_v, dict) else None
                except Exception as e:
                    logger.warning(f"[api] task enrichment error ({t.get('block_id','')}): {e}")
                    for k in ["locked","has_analysis","has_result","job_status","job_label","job_elapsed",
                               "job_start_time","verify_status","job_warning","count_analysis","count_draft",
                               "count_revision","count_verify","verify_score"]:
                        t.setdefault(k, None)
            return tasks
        result["tasks"] = await asyncio.get_event_loop().run_in_executor(None, _enrich_tasks, result["tasks"])
        # detail 페이지 캐시 워밍 (백그라운드)
        for t in result["tasks"]:
            bid = t["block_id"]
            if bid not in _task_cache or _time_mod.time() - _task_cache.get(bid, {}).get("ts", 0) > _TASK_CACHE_TTL:
                asyncio.get_event_loop().run_in_executor(None, _warm_task_cache, bid)
    return JSONResponse(result)


def _warm_task_cache(block_id: str):
    """detail 페이지 캐시 미리 로드"""
    try:
        task = parse_task_from_block(block_id)
        with _task_cache_lock:
            _task_cache[block_id] = {"task": task, "ts": _time_mod.time()}
    except Exception:
        pass


@app.post("/api/lock-tasks")
async def lock_tasks(request: Request):
    """선택된 과제를 잠금 처리"""
    data = await request.json()
    ids = set(data.get("block_ids", []))
    locked = get_locked_ids()
    locked |= ids
    set_locked_ids(locked)
    return JSONResponse({"status": "ok", "locked_count": len(locked)})


@app.post("/api/unlock-tasks")
async def unlock_tasks(request: Request):
    """선택된 과제를 잠금 해제"""
    data = await request.json()
    ids = set(data.get("block_ids", []))
    locked = get_locked_ids()
    locked -= ids
    set_locked_ids(locked)
    return JSONResponse({"status": "ok", "locked_count": len(locked)})


@app.post("/api/batch-analysis")
async def batch_analysis(request: Request):
    """선택된 과제들 일괄 사전분석 (순차 실행, 이벤트루프 블로킹 방지)"""
    data = await request.json()
    block_ids = data.get("block_ids", [])

    def _run_batch():
        results = []
        for bid in block_ids:
            try:
                task = parse_task_from_block(bid)
                ws = create_workspace(task)
                success = launch_pre_analysis(task, ws)
                results.append({"block_id": bid, "success": success})
            except Exception as e:
                results.append({"block_id": bid, "success": False, "error": str(e)})
        return results

    results = await asyncio.get_event_loop().run_in_executor(None, _run_batch)
    return JSONResponse({"status": "ok", "results": results})


# ──────────────────────────────────────────────
# 2. 과업 상세
# ──────────────────────────────────────────────
@app.get("/api/debug-task/{block_id}")
async def debug_task(block_id: str):
    task = parse_task_from_block(block_id)
    return JSONResponse({k: v for k, v in task.items() if not isinstance(v, list) or k in ("attachments","guide_files","bio_files")})


# 과제 상세 캐시 (TTL 10분, 최대 20개)
import time as _time_mod
import threading as _threading
_task_cache: dict[str, dict] = {}
_task_cache_lock = _threading.Lock()
_TASK_CACHE_TTL = 600
_TASK_CACHE_MAX = 20


@app.get("/task/{block_id}", response_class=HTMLResponse)
async def task_detail(request: Request, block_id: str):
    now = _time_mod.time()
    with _task_cache_lock:
        cached = _task_cache.get(block_id)

    if cached and now - cached["ts"] < _TASK_CACHE_TTL:
        task = cached["task"]
    else:
        try:
            task = await asyncio.get_event_loop().run_in_executor(
                None, parse_task_from_block, block_id
            )
        except Exception as e:
            logger.error(f"[detail] 과제 파싱 실패 ({block_id}): {e}")
            raise HTTPException(status_code=500, detail="과제 정보를 불러올 수 없습니다")
        with _task_cache_lock:
            _task_cache[block_id] = {"task": task, "ts": now}
            # 캐시 크기 제한 — 가장 오래된 항목 제거
            if len(_task_cache) > _TASK_CACHE_MAX:
                oldest = min(_task_cache, key=lambda k: _task_cache[k]["ts"])
                del _task_cache[oldest]

    locked = block_id in get_locked_ids()
    return templates.TemplateResponse(
        request=request,
        name="detail.html",
        context={"task": task, "locked": locked}
    )



@app.get("/api/task-detail/{block_id}")
async def api_task_detail(block_id: str):
    """상세 페이지에 필요한 모든 데이터를 한번에 반환"""
    def _gather():
        data = {}
        # 분석 결과
        analysis = get_analysis(block_id)
        data["analysis"] = analysis if analysis and analysis.get("status") == "ok" else None
        # 경고
        data["warning"] = get_warning(block_id)
        # 산출물
        data["result"] = get_result(block_id)
        # 지시 이력
        data["memo_log"] = get_memo_log(block_id)
        # 작업 상태
        data["job_status"] = get_job_status(block_id)
        return data
    data = await asyncio.get_event_loop().run_in_executor(None, _gather)
    return JSONResponse(data)


# ──────────────────────────────────────────────
# 6. Claude Code 터미널 실행
# ──────────────────────────────────────────────
# 이미 처리한 과제 ID 추적 (새 과제 감지용)
_known_task_ids: set = set()

@app.post("/api/launch-claude/{block_id}")
async def launch_claude(block_id: str, user_memo: str = Form("")):
    """워크스페이스 생성 후 Terminal에서 Claude Code 실행"""
    _check_locked(block_id)
    try:
        task = parse_task_from_block(block_id)
    except Exception as e:
        logger.error(f"[launch-claude] Notion 파싱 실패 ({block_id}): {e}")
        raise HTTPException(status_code=500, detail="Notion 파싱 실패")

    workspace = await asyncio.get_event_loop().run_in_executor(
        None, create_workspace, task
    )
    instruction = build_instruction(task, user_memo)
    success = launch_background(workspace, instruction, block_id, "초안 작성")

    _known_task_ids.add(block_id)

    return JSONResponse({
        "success": success,
        "workspace": str(workspace),
        "message": "백그라운드에서 작업이 시작되었습니다." if success else "실행 실패"
    })


@app.get("/api/check-new-tasks")
async def check_new_tasks():
    """새로운 과제가 있는지 확인 (이전에 없던 과제 감지) → 자동 사전분석"""
    global _known_task_ids
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_my_tasks(force=False)
    )

    if result["status"] != "ok":
        return JSONResponse({"new_tasks": [], "initialized": False})

    current_ids = {t["block_id"] for t in result["tasks"]}

    # 첫 로드 시 초기화만 수행
    if not _known_task_ids:
        _known_task_ids = current_ids.copy()
        return JSONResponse({"new_tasks": [], "initialized": True})

    new_ids = current_ids - _known_task_ids
    new_tasks = [t for t in result["tasks"] if t["block_id"] in new_ids]

    # 새 과제 감지 시 백그라운드로 워크스페이스 생성 (사전분석은 수동)
    for nt in new_tasks:
        asyncio.get_event_loop().run_in_executor(
            None, _auto_prepare_task, nt["block_id"]
        )

    # 감지한 새 과제를 known에 추가
    _known_task_ids = current_ids.copy()

    return JSONResponse({
        "new_tasks": new_tasks,
        "initialized": True
    })


def _auto_prepare_task(block_id: str):
    """새 과제 자동 준비: 파싱 → 워크스페이스 생성 → 사전분석 자동 시작"""
    try:
        task = parse_task_from_block(block_id)
        ws = create_workspace(task)
        logger.info(f"[auto-prepare] {task.get('title', block_id)} 워크스페이스 생성 완료: {ws}")
        # 사전분석까지만 자동 시작 (초안 작성은 사용자가 수동으로)
        launch_pre_analysis(task, ws)
        logger.info(f"[auto-prepare] {task.get('title', block_id)} 사전분석 자동 시작")
    except Exception as e:
        logger.error(f"[auto-prepare] {block_id} 실패: {e}")


# ──────────────────────────────────────────────
# 7. 사전분석 조회 / 수동 실행
# ──────────────────────────────────────────────
@app.get("/api/analysis/{block_id}")
async def api_get_analysis(block_id: str):
    """캐싱된 사전분석 결과 조회"""
    analysis = get_analysis(block_id)
    if not analysis:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse(analysis)


def _check_locked(block_id: str):
    """잠금된 과제면 403 에러"""
    if block_id in get_locked_ids():
        raise HTTPException(status_code=403, detail="잠금된 과제는 수정할 수 없습니다")


@app.post("/api/analysis/{block_id}")
async def api_run_analysis(block_id: str):
    """Claude Code 터미널로 사전분석 실행 (워크스페이스 생성 + STEP 2-4)"""
    _check_locked(block_id)
    try:
        task = await asyncio.get_event_loop().run_in_executor(
            None, parse_task_from_block, block_id
        )
        ws = await asyncio.get_event_loop().run_in_executor(
            None, create_workspace, task
        )
        success = launch_pre_analysis(task, ws)
        return JSONResponse({
            "success": success,
            "workspace": str(ws),
            "message": "Terminal에서 사전분석이 시작되었습니다." if success else "Terminal 실행 실패"
        })
    except Exception as e:
        logger.error(f"[analysis] 사전분석 실패 ({block_id}): {e}")
        raise HTTPException(status_code=500, detail="사전분석 실행에 실패했습니다")


@app.post("/api/analysis/{block_id}/revise")
async def api_revise_analysis(
    block_id: str,
    memo: str = Form(...),
    files: list[UploadFile] = File(default=[]),
):
    """사전분석 보충/수정 — 추가 자료 + 메모로 재분석"""
    _check_locked(block_id)
    try:
        # 첨부 파일 저장
        uploaded_names = []
        ws = get_workspace_path(block_id)
        if ws and files:
            files_dir = ws / "files"
            files_dir.mkdir(exist_ok=True)
            for f in files:
                if f.filename:
                    dest = files_dir / f.filename
                    content = await f.read()
                    dest.write_bytes(content)
                    uploaded_names.append(f.filename)

        task = await asyncio.get_event_loop().run_in_executor(
            None, parse_task_from_block, block_id
        )
        if not ws:
            ws = await asyncio.get_event_loop().run_in_executor(
                None, create_workspace, task
            )

        # 기존 분석 결과 로드
        existing_analysis = get_analysis(block_id)
        existing_text = ""
        if existing_analysis and existing_analysis.get("analysis"):
            existing_text = existing_analysis["analysis"]

        file_info = ""
        if uploaded_names:
            file_info = "\n\n## 추가 첨부 파일 (files/ 폴더에 저장됨)\n" + "\n".join(f"- files/{n}" for n in uploaded_names)

        from modules.workspace_launcher import launch_background, _save_memo_log
        _save_memo_log(block_id, "사전분석 보충", memo)

        instruction = f"""CLAUDE.md를 읽고, files/ 폴더의 첨부파일을 분석한 뒤,
기존 사전분석 결과를 보충/수정해주세요.

## 기존 사전분석 결과
{existing_text}

## 보충/수정 요청
{memo}
{file_info}

수정된 전체 분석 결과를 analysis.md 파일로 저장하세요.
마지막으로 analysis.json 파일도 저장하세요:
{{"status": "ok", "analysis": "(analysis.md 내용 전체)"}}"""

        success = launch_background(ws, instruction, block_id, "사전분석")
        return JSONResponse({
            "success": success,
            "message": f"사전분석 보충 시작 (첨부 {len(uploaded_names)}개)" if success else "실행 실패"
        })
    except Exception as e:
        logger.error(f"[analysis-revise] 보충 실패 ({block_id}): {e}")
        raise HTTPException(status_code=500, detail="사전분석 보충에 실패했습니다")


@app.delete("/api/analysis/{block_id}")
async def api_delete_analysis(block_id: str):
    """사전분석 결과 삭제"""
    _check_locked(block_id)
    deleted = delete_analysis(block_id)
    if not deleted:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse({"status": "ok"})


# ──────────────────────────────────────────────
# 7-0. 작업 상태 폴링
# ──────────────────────────────────────────────
@app.get("/api/job-status/{block_id}")
async def api_job_status(block_id: str):
    """백그라운드 작업 상태 조회"""
    status = get_job_status(block_id)
    if not status:
        return JSONResponse({"status": "idle"})
    return JSONResponse(status)


# ──────────────────────────────────────────────
# 7-1. 산출물 수정
# ──────────────────────────────────────────────
@app.post("/api/revise/{block_id}")
async def revise_output(
    block_id: str,
    revision_memo: str = Form(...),
    files: list[UploadFile] = File(default=[]),
):
    """기존 산출물 수정 — 첨부 파일 저장 + Claude Code 터미널 실행"""
    _check_locked(block_id)
    try:
        # 첨부 파일을 워크스페이스 files/에 저장
        uploaded_names = []
        if files:
            ws = get_workspace_path(block_id)
            if ws:
                files_dir = ws / "files"
                files_dir.mkdir(exist_ok=True)
                for f in files:
                    if f.filename:
                        dest = files_dir / f.filename
                        content = await f.read()
                        dest.write_bytes(content)
                        uploaded_names.append(f.filename)
                        logger.info(f"[revise] 첨부 파일 저장: {f.filename} ({len(content)} bytes)")

        # 첨부 파일이 있으면 메모에 추가
        memo = revision_memo
        if uploaded_names:
            memo += "\n\n## 첨부 파일 (files/ 폴더에 저장됨)\n" + "\n".join(f"- files/{n}" for n in uploaded_names)

        task = await asyncio.get_event_loop().run_in_executor(
            None, parse_task_from_block, block_id
        )
        success = launch_revision(task, memo)
        return JSONResponse({
            "success": success,
            "message": f"수정 시작 (첨부 {len(uploaded_names)}개)" if success else "실행 실패"
        })
    except Exception as e:
        logger.error(f"[revise] 수정 실패 ({block_id}): {e}")
        raise HTTPException(status_code=500, detail="수정 실행에 실패했습니다")


@app.get("/api/warning/{block_id}")
async def api_warning(block_id: str):
    """미해결 경고 조회"""
    w = get_warning(block_id)
    if not w:
        return JSONResponse({"status": "ok"})
    return JSONResponse({"status": "warning", **w})


@app.get("/api/memo-log/{block_id}")
async def api_memo_log(block_id: str):
    """추가 지시사항 이력 조회"""
    logs = get_memo_log(block_id)
    return JSONResponse(logs)


@app.delete("/api/memo-log/{block_id}")
async def api_delete_memo_log(block_id: str):
    """지시사항 이력 전체 삭제"""
    _check_locked(block_id)
    ws = get_workspace_path(block_id)
    if ws:
        log_file = ws / "memo_log.json"
        if log_file.exists():
            log_file.unlink()
    return JSONResponse({"status": "ok"})


@app.delete("/api/memo-log/{block_id}/{index}")
async def api_delete_memo_entry(block_id: str, index: int):
    """지시사항 이력 개별 삭제"""
    _check_locked(block_id)
    ws = get_workspace_path(block_id)
    if not ws:
        return JSONResponse({"status": "error"}, status_code=404)
    log_file = ws / "memo_log.json"
    if not log_file.exists():
        return JSONResponse({"status": "error"}, status_code=404)
    logs = json.loads(log_file.read_text(encoding="utf-8"))
    if 0 <= index < len(logs):
        logs.pop(index)
        log_file.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    return JSONResponse({"status": "ok"})


@app.delete("/api/result/{block_id}")
async def api_delete_result(block_id: str):
    _check_locked(block_id)
    """워크스페이스의 산출물 삭제 (result.json + 산출물 파일)"""
    ws = get_workspace_path(block_id)
    if not ws:
        return JSONResponse({"status": "error", "message": "워크스페이스 없음"}, status_code=404)

    # result.json 읽어서 파일 목록 확인
    result_file = ws / "result.json"
    if result_file.exists():
        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
            for o in data.get("outputs", []):
                f = ws / o.get("file", "")
                if f.exists() and f.is_file():
                    f.unlink()
        except Exception:
            pass
        result_file.unlink()

    # result.md도 삭제
    md_file = ws / "result.md"
    if md_file.exists():
        md_file.unlink()

    return JSONResponse({"status": "ok"})


# ──────────────────────────────────────────────
# 7-2. 결과 조회 / 저장
# ──────────────────────────────────────────────
@app.get("/api/result/{block_id}")
async def api_get_result(block_id: str):
    """워크스페이스에서 result.json 읽기"""
    result = await asyncio.get_event_loop().run_in_executor(
        None, get_result, block_id
    )
    if result is None:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return JSONResponse({"status": "ok", "result": result})


@app.post("/api/result/{block_id}")
async def api_save_result(block_id: str, request: Request):
    """워크스페이스에 result.json 저장/업데이트"""
    data = await request.json()
    success = await asyncio.get_event_loop().run_in_executor(
        None, save_result, block_id, data
    )
    if not success:
        return JSONResponse({"status": "error", "message": "워크스페이스를 찾을 수 없습니다"}, status_code=404)
    return JSONResponse({"status": "ok"})


@app.get("/api/download/{block_id}/{filename:path}")
async def download_file(block_id: str, filename: str):
    """워크스페이스 파일 다운로드 (docx, hwp, files/첨부 등)"""
    ws = get_workspace_path(block_id)
    if not ws:
        raise HTTPException(status_code=404, detail="워크스페이스를 찾을 수 없습니다")
    if '..' in filename:
        raise HTTPException(status_code=400, detail="잘못된 파일명입니다")
    file_path = (ws / filename).resolve()
    if not file_path.is_relative_to(ws.resolve()):
        raise HTTPException(status_code=403, detail="접근이 거부되었습니다")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
    # 파일명만 추출해서 다운로드명으로 사용
    download_name = file_path.name
    return FileResponse(file_path, filename=download_name)


@app.get("/api/preview-hwp/{block_id}/{filename:path}")
async def preview_hwp(block_id: str, filename: str):
    """HWP 파일을 HTML로 변환하여 미리보기 제공"""
    ws = get_workspace_path(block_id)
    if not ws:
        raise HTTPException(status_code=404, detail="워크스페이스를 찾을 수 없습니다")
    if '..' in filename:
        raise HTTPException(status_code=400, detail="잘못된 파일명입니다")
    # 워크스페이스 루트 또는 files/ 하위에서 찾기
    file_path = (ws / filename).resolve()
    if not file_path.exists():
        file_path = (ws / "files" / filename).resolve()
    if not file_path.is_relative_to(ws.resolve()):
        raise HTTPException(status_code=403, detail="접근이 거부되었습니다")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

    import subprocess
    converter = os.path.join(os.path.dirname(__file__), "modules", "hwp_converter.js")
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ["node", converter, str(file_path), "html"],
                capture_output=True, timeout=15,
            )
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail="HWP 변환 실패")
        return HTMLResponse(content=result.stdout.decode("utf-8", errors="ignore"))
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="HWP 변환 시간 초과")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"HWP 변환 오류: {str(e)}")


_PROXY_ALLOWED_DOMAINS = {
    "www.notion.so", "notion.so", "s3.us-west-2.amazonaws.com",
    "prod-files-secure.s3.us-west-2.amazonaws.com",
    "file.notion.so", "export-download.canva.com",
    "storage.tally.so",
}

@app.get("/api/proxy-file")
async def proxy_file(url: str):
    """외부 URL을 프록시하여 CORS 우회 (허용 도메인만)"""
    import httpx
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="허용되지 않는 프로토콜입니다")
    if parsed.hostname not in _PROXY_ALLOWED_DOMAINS:
        raise HTTPException(status_code=403, detail=f"허용되지 않는 도메인입니다: {parsed.hostname}")
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "application/octet-stream")
            # URL에서 파일명 추출
            from urllib.parse import unquote
            fname = unquote(parsed.path.split("/")[-1]) or "download"
            return StreamingResponse(
                iter([resp.content]),
                media_type=ct,
                headers={
                    "Content-Disposition": f'inline; filename="{fname}"',
                    "X-Filename": fname,
                }
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail="외부 파일 요청 실패")


# ──────────────────────────────────────────────
# 8. 산출물 검증 API
# ──────────────────────────────────────────────
@app.post("/api/verify/{block_id}")
async def api_verify(block_id: str):
    """산출물 검증 실행 — Claude Code 백그라운드로 검증 수행"""
    try:
        task = await asyncio.get_event_loop().run_in_executor(
            None, parse_task_from_block, block_id
        )
        success = run_verification(task)
        return JSONResponse({
            "success": success,
            "message": "검증이 시작되었습니다." if success else "검증 실행 실패"
        })
    except Exception as e:
        logger.error(f"[verify] 검증 실패 ({block_id}): {e}")
        raise HTTPException(status_code=500, detail="검증 실행에 실패했습니다")


@app.get("/api/verify/{block_id}")
async def api_get_verification(block_id: str):
    """검증 결과 조회"""
    ws = get_workspace_path(block_id)
    if not ws:
        return JSONResponse({"status": "not_found"}, status_code=404)
    verify_file = ws / "verification.json"
    if verify_file.exists():
        return JSONResponse(json.loads(verify_file.read_text(encoding="utf-8")))
    return JSONResponse({"status": "not_found"}, status_code=404)


@app.post("/api/batch-verify")
async def batch_verify(request: Request):
    """선택된 과제들 일괄 검증"""
    data = await request.json()
    block_ids = data.get("block_ids", [])

    def _run_batch():
        results = []
        for bid in block_ids:
            try:
                task = parse_task_from_block(bid)
                success = run_verification(task)
                results.append({"block_id": bid, "success": success})
            except Exception as e:
                results.append({"block_id": bid, "success": False, "error": str(e)})
        return results

    results = await asyncio.get_event_loop().run_in_executor(None, _run_batch)
    return JSONResponse({"status": "ok", "results": results})


# ──────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    is_dev = os.getenv("ENV", "dev") == "dev"
    uvicorn.run(
        "main:app", host="0.0.0.0", port=8000,
        reload=is_dev,
        reload_dirs=[".", "modules", "templates", "static", "rules"] if is_dev else None,
        reload_includes=["main.py", "modules/*.py", "templates/*.html", "static/*.css", "rules/*.md"] if is_dev else None,
    )
