"""
Claude API 5단계 파이프라인 + URL 검증
"""

import os
import json
import anthropic
from modules.url_validator import clean_url, verify_url

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL  = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """당신은 수행평가 작문 전문가입니다.
유저 메시지에 포함된 [요청사항]과 첨부 이미지의 평가기준을 최우선으로 따르세요.
출처는 반드시 실제 접속 가능한 URL로 검증 후 사용하세요.
AI 특유의 나열식 문체를 피하고 자연스러운 고등학생 문어체로 작성하세요.
'~할 수 있다', '~라고 할 수 있다' 반복 금지. 소제목, 번호 매기기 금지."""


def _text(response) -> str:
    """응답에서 텍스트 추출"""
    return "".join(b.text for b in response.content if hasattr(b, "text"))


def _run_with_search(messages: list) -> tuple[str, list]:
    """웹 검색 tool 사용하여 출처 수집"""
    tools = [{"type": "web_search_20250305", "name": "web_search"}]
    collected_urls = []

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=messages,
    )

    # tool_result에서 URL 추출
    for block in response.content:
        if block.type == "tool_result":
            try:
                data = json.loads(block.content) if isinstance(block.content, str) else block.content
                if isinstance(data, list):
                    for item in data:
                        url = item.get("url") or item.get("link") or ""
                        if url.startswith("http"):
                            collected_urls.append({
                                "title": item.get("title", ""),
                                "url": url
                            })
            except Exception:
                pass

    return _text(response), collected_urls


def verify_references(references: list) -> list:
    """수집된 참고자료 URL 검증"""
    results = []
    for ref in references:
        url = ref.get("url", "")
        if not url:
            continue

        v = verify_url(url)
        results.append({
            "title":         ref.get("title", ""),
            "original_url":  url,
            "cleaned_url":   v["cleaned"],
            "accessible":    v["accessible"],
            "http_status":   v["http_status"],
            "suspicious_ai": v["suspicious_ai"],
            "was_modified":  v["was_modified"],
        })
    return results


def run_pipeline(task: dict, images: list, user_memo: str = "", progress_callback=None) -> dict:
    """
    5단계 Claude 파이프라인 실행
    progress_callback(step, label, status): 진행상황 콜백 (optional)
    """

    # 초기 메시지 구성 (이미지 + 텍스트)
    user_content = []
    for img in images:
        user_content.append({"type": img["type"], "source": img["source"]})

    user_content.append({"type": "text", "text": f"""[과제 정보]
과목: {task['subject']}
학년/학기: {task['grade']} {task['semester']}
활동유형: {task['activity']}
제출방식: {task['submit_type']}

[요청사항 / 선생님 안내]
{task['request_msg'] or '없음'}

[작성자 추가 아이디어]
{user_memo or '없음'}

위 평가기준 이미지와 요청사항을 분석하고 작문 개요를 잡아주세요."""})

    messages = [{"role": "user", "content": user_content}]
    steps, collected_urls, total_tokens = [], [], 0

    # STEP 1: 과업 분석 + 개요 + 분량 파악
    if progress_callback:
        progress_callback(1, "과업 분석 + 개요 + 분량 파악", "running")

    r1 = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    s1 = _text(r1)
    total_tokens += r1.usage.input_tokens + r1.usage.output_tokens
    steps.append({"step": 1, "label": "과업 분석 + 개요"})

    # 분량 요구사항 추출 (기본값 1600자)
    required_length = 1600
    if "자" in s1 or "글자" in s1:
        import re
        match = re.search(r'(\d+)\s*자', s1)
        if match:
            required_length = int(match.group(1))

    messages += [
        {"role": "assistant", "content": s1},
        {"role": "user", "content": "현대 사회 사례와 통계를 뒷받침할 출처를 공신력 있는 기관(정부, 학술기관) 위주로 검색해주세요."}
    ]

    # STEP 2: 출처 탐색 (웹 검색)
    if progress_callback:
        progress_callback(2, "출처 탐색 (웹 검색)", "running")

    s2, urls = _run_with_search(messages)
    collected_urls.extend(urls)
    steps.append({"step": 2, "label": "출처 탐색", "urls_found": len(urls)})

    messages += [
        {"role": "assistant", "content": s2},
        {"role": "user", "content": f"찾은 출처를 활용해서 {required_length}자 이상으로 본문을 작성해주세요. 평가기준의 모든 영역을 충족해야 합니다."}
    ]

    # STEP 3: 초안 작성
    if progress_callback:
        progress_callback(3, f"초안 작성 ({required_length}자+)", "running")

    r3 = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    s3 = _text(r3)
    total_tokens += r3.usage.input_tokens + r3.usage.output_tokens
    steps.append({"step": 3, "label": "초안 작성"})

    messages += [
        {"role": "assistant", "content": s3},
        {"role": "user", "content": "AI가 쓴 것처럼 느껴지는 표현을 모두 자연스럽게 바꿔주세요. 나열식 구조, 반복 접속어, 단정적 어미를 제거하고 사람이 쓴 것처럼 다듬어주세요."}
    ]

    # STEP 4: 문체 조정
    if progress_callback:
        progress_callback(4, "문체 조정 (AI 표현 제거)", "running")

    r4 = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    s4 = _text(r4)
    total_tokens += r4.usage.input_tokens + r4.usage.output_tokens
    steps.append({"step": 4, "label": "문체 조정"})

    messages += [
        {"role": "assistant", "content": s4},
        {"role": "user", "content": "최종본을 완성해주세요.\n\n[본문]\n(완성된 글)\n\n[참고자료]\n- 출처명, 발행기관, 연도, URL"}
    ]

    # STEP 5: 최종본
    if progress_callback:
        progress_callback(5, "최종본 + 참고자료", "running")

    r5 = client.messages.create(
        model=MODEL,
        max_tokens=5000,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    s5 = _text(r5)
    total_tokens += r5.usage.input_tokens + r5.usage.output_tokens
    steps.append({"step": 5, "label": "최종본"})

    # 결과 파싱
    result_text = s5
    references  = list(collected_urls)

    if "[참고자료]" in s5:
        parts       = s5.split("[참고자료]")
        result_text = parts[0].replace("[본문]", "").strip()

        # 참고자료에서 URL 추출
        for line in parts[1].strip().splitlines():
            line = line.strip("- ").strip()
            if not line:
                continue
            url = next((t for t in line.split() if t.startswith("http")), "")
            references.append({"title": line, "url": url})

    # STEP 6: URL 검증
    if progress_callback:
        progress_callback(6, "URL 검증 중...", "running")

    verified = verify_references([r for r in references if r.get("url")])

    if progress_callback:
        progress_callback(6, "완료", "done")

    return {
        "result":              result_text,
        "references":          references,
        "verified_references": verified,
        "steps":               steps,
        "total_tokens":        total_tokens,
        "estimated_cost_krw":  round(total_tokens * 3 / 1_000_000 * 1380),
    }
