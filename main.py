"""
수행평가 대시보드 - FastAPI 메인
"""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from modules.notion_parser  import parse_task_from_block
from modules.image_analyzer import prepare_images
from modules.claude_pipeline import run_pipeline

import anthropic
import json
import asyncio

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

app = FastAPI(title="수행평가 대시보드")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")




# ──────────────────────────────────────────────
# 1. 대시보드
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Notion 링크 입력 페이지 (단일 과업만 처리)"""
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={}
    )


# ──────────────────────────────────────────────
# 2. 과업 상세
# ──────────────────────────────────────────────
@app.get("/task/{block_id}", response_class=HTMLResponse)
async def task_detail(request: Request, block_id: str):
    try:
        task   = parse_task_from_block(block_id)
        images = prepare_images(task.get("attachments", []))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    image_meta = [
        {
            "name":   img["_meta"].get("name", ""),
            "tokens": img["_meta"].get("estimated_tokens", 0),
            "size":   "×".join(map(str, img["_meta"].get("size", [])))
        }
        for img in images
    ]

    return templates.TemplateResponse(
        request=request,
        name="detail.html",
        context={"task": task, "image_meta": image_meta}
    )


# ──────────────────────────────────────────────
# 3. 프롬프트 조립 API
# ──────────────────────────────────────────────
@app.post("/api/build-prompt")
async def build_prompt(
    block_id:  str = Form(...),
    user_memo: str = Form(""),
):
    try:
        task   = parse_task_from_block(block_id)
        images = prepare_images(task.get("attachments", []))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    user_text = f"""[과제 정보]
과목: {task['subject']}
학년/학기: {task['grade']} {task['semester']}
활동유형: {task['activity']}
제출방식: {task['submit_type']}
진행상태: {task['status']}

[요청사항 / 선생님 안내]
{task['request_msg'] or '없음'}

[작성자 추가 아이디어]
{user_memo or '없음'}

위 지침과 첨부 이미지의 평가기준을 참고하여 작성해 주세요."""

    image_tokens = sum(img["_meta"]["estimated_tokens"] for img in images)
    text_tokens  = len(user_text) // 2

    return JSONResponse({
        "system":                  "당신은 수행평가 작문 전문가입니다. 유저 메시지에 포함된 [요청사항]과 첨부 이미지의 평가기준을 최우선으로 따르세요. 출처는 실제 접속 가능한 URL로 검증 후 사용하고, AI 특유의 문체를 피해 자연스러운 문어체로 작성하세요.",
        "user_text":               user_text,
        "image_count":             len(images),
        "estimated_input_tokens":  image_tokens + text_tokens,
        "estimated_cost_krw":      round((image_tokens + text_tokens) * 3 / 1_000_000 * 1380),
    })


# ──────────────────────────────────────────────
# 4. Claude API 전송
# ──────────────────────────────────────────────
@app.post("/api/send-to-claude")
async def send_to_claude(
    block_id:  str = Form(...),
    user_memo: str = Form(""),
):
    """Claude API에 과업 + 이미지 전송하고 응답 받기"""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "sk-ant-여기에_실제_키_입력":
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

    try:
        task   = parse_task_from_block(block_id)
        images = prepare_images(task.get("attachments", []))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Notion 데이터 파싱 실패: {str(e)}")

    # System prompt
    system_prompt = "당신은 수행평가 작문 전문가입니다. 유저 메시지에 포함된 [요청사항]과 첨부 이미지의 평가기준을 최우선으로 따르세요. 출처는 실제 접속 가능한 URL로 검증 후 사용하고, AI 특유의 문체를 피해 자연스러운 문어체로 작성하세요."

    # User message (텍스트 + 이미지)
    user_content = []

    # 텍스트 부분
    user_text = f"""[과제 정보]
과목: {task['subject']}
학년/학기: {task['grade']} {task['semester']}
활동유형: {task['activity']}
제출방식: {task['submit_type']}
진행상태: {task['status']}

[요청사항 / 선생님 안내]
{task['request_msg'] or '없음'}

[작성자 추가 아이디어]
{user_memo or '없음'}

위 지침과 첨부 이미지의 평가기준을 참고하여 작성해 주세요."""

    user_content.append({
        "type": "text",
        "text": user_text
    })

    # 이미지 추가
    for img in images:
        user_content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["source"]["media_type"],
                "data": img["source"]["data"]
            }
        })

    # Claude API 호출
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": user_content
                }
            ]
        )

        response_text = message.content[0].text if message.content else ""

        return JSONResponse({
            "success": True,
            "response": response_text,
            "usage": {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens
            }
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude API 호출 실패: {str(e)}")


# ──────────────────────────────────────────────
# 5. Claude 5단계 파이프라인 (SSE 스트리밍)
# ──────────────────────────────────────────────
@app.post("/api/run-claude")
async def run_claude_pipeline(
    block_id:  str = Form(...),
    user_memo: str = Form(""),
    test_mode: str = Form("false"),  # 테스트 모드 플래그
):
    """5단계 Claude 파이프라인 실행 + 진행상황 SSE 스트리밍"""

    try:
        task   = parse_task_from_block(block_id)
        images = prepare_images(task.get("attachments", []))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Notion 데이터 파싱 실패: {str(e)}")

    async def event_generator():
        """SSE 이벤트 생성기"""

        # 테스트 모드
        if test_mode == "true":
            steps = [
                (1, "과업 분석 + 개요 + 분량 파악"),
                (2, "출처 탐색 (웹 검색)"),
                (3, "초안 작성 (1600자+)"),
                (4, "문체 조정 (AI 표현 제거)"),
                (5, "최종본 + 참고자료"),
            ]

            for step, label in steps:
                await asyncio.sleep(1.5)
                yield f"data: {json.dumps({'status': 'running', 'step': step, 'label': label})}\n\n"

            # 목업 결과
            mock_result = f"""제목: {task['subject']} 수행평가 - {task['title']}

[서론]
{task['request_msg'][:100] if task.get('request_msg') else '과제 안내 내용'}에 따라 본 과제를 수행하였다.

[본론]
현대 사회에서는 다양한 이슈들이 존재한다. 첫째, 의료 접근성 문제가 있다. 독거노인과 도서산간 지역 주민들은 적절한 의료 서비스를 받기 어려운 실정이다.

둘째, 사회적 양극화 현상이 심화되고 있다. 통계청 자료에 따르면 소득 격차가 지속적으로 확대되고 있다.

셋째, 환경 문제 해결을 위한 노력이 필요하다. 기후변화에 대응하기 위해 정부와 시민사회가 협력하고 있다.

[결론]
이러한 문제들을 해결하기 위해서는 제도적 개선과 시민의식 향상이 필요하다.

(테스트 모드로 생성된 목업 결과입니다. 실제 API 호출 시 더 상세한 내용이 작성됩니다.)"""

            mock_refs = [
                {
                    "title": "통계청 - 2024년 소득분배지표",
                    "cleaned_url": "https://kostat.go.kr/example",
                    "accessible": True,
                    "suspicious_ai": []
                },
                {
                    "title": "보건복지부 - 의료 접근성 개선 방안",
                    "cleaned_url": "https://mohw.go.kr/example",
                    "accessible": True,
                    "suspicious_ai": []
                },
                {
                    "title": "환경부 - 기후변화 대응 정책",
                    "cleaned_url": "https://me.go.kr/example?utm_source=chatgpt",
                    "accessible": False,
                    "suspicious_ai": ["utm_source"]
                }
            ]

            yield f"data: {json.dumps({
                'status': 'complete',
                'result': mock_result,
                'verified_references': mock_refs,
                'total_tokens': 25000,
                'estimated_cost_krw': 937
            })}\n\n"
            return

        # 실제 모드
        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "sk-ant-여기에_실제_키_입력":
            yield f"data: {json.dumps({'status': 'error', 'message': 'ANTHROPIC_API_KEY가 설정되지 않았습니다.'})}\n\n"
            return

        progress_events = []

        def progress_callback(step, label, status):
            """진행상황 수집"""
            progress_events.append({
                "status": status,
                "step": step,
                "label": label
            })

        try:
            # 별도 스레드에서 파이프라인 실행
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                run_pipeline,
                task,
                images,
                user_memo,
                progress_callback
            )

            # 완료 이벤트 전송
            yield f"data: {json.dumps({
                'status': 'complete',
                'result': result['result'],
                'verified_references': result['verified_references'],
                'total_tokens': result['total_tokens'],
                'estimated_cost_krw': result['estimated_cost_krw']
            })}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ──────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
