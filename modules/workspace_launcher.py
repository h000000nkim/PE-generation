"""
워크스페이스 생성 + Claude Code 터미널 실행
- Notion에서 파싱한 데이터를 파일로 저장 (코드 자동화 영역)
- Claude Code가 수행할 분석/작성 지침을 CLAUDE.md로 작성
- macOS Terminal.app에서 Claude Code 실행
"""

import os
import re
import json
import subprocess
import requests
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "workspaces"
LOCKED_FILE = BASE_DIR / ".locked_tasks.json"

# block_id → workspace path 매핑 (런타임 캐시)
_workspace_map: dict[str, Path] = {}


def get_locked_ids() -> set:
    """잠금된 과제 ID 목록"""
    if LOCKED_FILE.exists():
        return set(json.loads(LOCKED_FILE.read_text(encoding="utf-8")))
    return set()


def set_locked_ids(ids: set):
    """잠금 과제 ID 저장"""
    LOCKED_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCKED_FILE.write_text(json.dumps(list(ids), ensure_ascii=False), encoding="utf-8")


def _safe_dirname(name: str, block_id: str) -> str:
    safe = re.sub(r'[^\w가-힣ㄱ-ㅎㅏ-ㅣ _-]', '_', name or "unknown")
    return f"{safe}_{block_id[:8]}"


def _download_file(url: str, dest: Path):
    try:
        r = requests.get(url, timeout=30, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return True
    except Exception:
        return False


def create_workspace(task: dict) -> Path:
    """
    코드 자동화 영역: STEP 0 + STEP 1 + STEP 2(다운로드) + 학생 데이터 수집
    - 디렉토리 생성
    - 첨부파일/가이드/생기부 다운로드
    - 파싱된 데이터를 구조화된 파일로 저장
    - Claude Code용 CLAUDE.md 작성
    """
    block_id = task.get("block_id", "unknown")
    dirname = _safe_dirname(task.get("name", ""), block_id)
    ws = BASE_DIR / dirname
    ws.mkdir(parents=True, exist_ok=True)

    # block_id → workspace 매핑 저장
    _workspace_map[block_id] = ws

    # ── MCP 설정 복사 (Word MCP 서버 등) ──
    import shutil
    project_mcp = Path(__file__).resolve().parent.parent / ".mcp.json"
    if project_mcp.exists():
        shutil.copy2(project_mcp, ws / ".mcp.json")

    # ── Claude Code 설정 복사 (MCP 자동 승인 등) ──
    claude_dir = ws / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings = {
        "permissions": {
            "allow": [
                "Bash(*)",
                "Read(*)",
                "Write(*)",
                "Edit(*)",
                "Glob(*)",
                "Grep(*)",
                "WebFetch(*)",
                "WebSearch(*)",
                "mcp__word-document-server__*",
                "mcp__claude_ai_Canva__*"
            ]
        },
        "enabledMcpjsonServers": [
            "word-document-server"
        ],
        "enableAllProjectMcpServers": True
    }
    (claude_dir / "settings.local.json").write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── 파일 다운로드 (코드 자동화) ──
    files_dir = ws / "files"
    files_dir.mkdir(exist_ok=True)

    downloaded_attachments = []
    downloaded_guides = []
    downloaded_bio = []

    for att in task.get("attachments", []):
        if att.get("url"):
            fname = att.get("name", "attachment")
            if _download_file(att["url"], files_dir / fname):
                downloaded_attachments.append(fname)

    for gf in task.get("guide_files", []):
        if gf.get("url"):
            fname = gf.get("name", "guide")
            if _download_file(gf["url"], files_dir / fname):
                downloaded_guides.append(fname)

    for bf in task.get("bio_files", []):
        if bf.get("url"):
            fname = bf.get("name", "bio")
            if _download_file(bf["url"], files_dir / fname):
                downloaded_bio.append(fname)

    # ── 문서 텍스트 사전 추출 (.pptx, .docx, .pdf → .txt) ──
    all_downloaded = downloaded_attachments + downloaded_guides + downloaded_bio
    for fname in all_downloaded:
        fpath = files_dir / fname
        txt_path = files_dir / f"{fname}.txt"
        try:
            if fname.lower().endswith(".pptx"):
                from pptx import Presentation
                prs = Presentation(str(fpath))
                lines = []
                for i, slide in enumerate(prs.slides, 1):
                    lines.append(f"=== 슬라이드 {i} ===")
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            for para in shape.text_frame.paragraphs:
                                t = para.text.strip()
                                if t:
                                    lines.append(t)
                    lines.append("")
                txt_path.write_text("\n".join(lines), encoding="utf-8")
            elif fname.lower().endswith(".docx"):
                from docx import Document as DocxDocument
                doc = DocxDocument(str(fpath))
                lines = [p.text for p in doc.paragraphs if p.text.strip()]
                txt_path.write_text("\n".join(lines), encoding="utf-8")
            elif fname.lower().endswith(".pdf"):
                import fitz
                doc = fitz.open(str(fpath))
                text_lines = []
                has_text = False
                for i, page in enumerate(doc, 1):
                    page_text = page.get_text().strip()
                    text_lines.append(f"=== 페이지 {i} ===")
                    text_lines.append(page_text)
                    text_lines.append("")
                    if len(page_text) > 20:
                        has_text = True
                # 텍스트가 있으면 .txt로 저장
                if has_text:
                    txt_path.write_text("\n".join(text_lines), encoding="utf-8")
                else:
                    # 스캔 PDF → 페이지별 이미지로 변환
                    for i, page in enumerate(doc, 1):
                        pix = page.get_pixmap(dpi=150)
                        img_path = files_dir / f"{fname}_p{i}.png"
                        pix.save(str(img_path))
                    # 안내 파일 생성
                    txt_path.write_text(
                        f"스캔 PDF — 텍스트 없음. 페이지별 이미지로 변환됨:\n"
                        + "\n".join(f"  - {fname}_p{i}.png" for i in range(1, len(doc) + 1)),
                        encoding="utf-8"
                    )
                doc.close()
        except Exception as e:
            print(f"[workspace] 텍스트 추출 실패 ({fname}): {e}")

    # ── 과거 과제 이력 정리 (코드 자동화) ──
    past_tasks_text = ""
    if task.get("past_tasks"):
        lines = []
        for pt in task["past_tasks"]:
            line = f"- **{pt.get('title', '(제목없음)')}** | 과목: {pt.get('subject', '—')} | 상태: {pt.get('status', '—')}"
            if pt.get('semester'):
                line += f" | {pt['semester']}"
            if pt.get('due_date'):
                line += f" | 마감: {pt['due_date']}"
            if pt.get('request'):
                line += f"\n  요청 핵심: {pt['request'][:200]}"
            lines.append(line)
        past_tasks_text = "\n".join(lines)

    # ── 파일 목록 텍스트 ──
    att_list = "\n".join(f"  - files/{f} (평가기준/양식)" for f in downloaded_attachments) if downloaded_attachments else "  (없음)"
    guide_list = "\n".join(f"  - files/{f} (완성물/참고용 — 분석 불필요)" for f in downloaded_guides) if downloaded_guides else "  (없음)"
    bio_list = "\n".join(f"  - files/{f} (생기부)" for f in downloaded_bio) if downloaded_bio else "  (없음)"

    # ── CLAUDE.md 작성 ──
    claude_md = f"""# 수행평가 작업 에이전트

## 역할
너는 수행평가 작문 및 기획 전문가다. 아래 데이터와 files/ 폴더의 첨부파일을 바탕으로 작업을 수행한다.

---

## 과제 이름: {task.get('title', '—')}

---

## [파싱 완료] 학생 정보
- 이름: {task.get('name', '—')}
- 학교: {task.get('school', '—')}
- 학년: {task.get('grade', '—')}
- 진로/계열: {task.get('major', '—')}
{f"- 목표 학과: {task['target_dept']}" if task.get('target_dept') else ""}
{f"- 소속: {task['affiliation']}" if task.get('affiliation') else ""}
- 학생 코드: {task.get('student_code', '—')}
{f"- 연락처: {task.get('phone', '')}" if task.get('phone') else ""}

## [파싱 완료] 과제 정보
- 과목(mGaa): {task.get('subject', '—')}
- 학기(wuL:): {task.get('semester', '—')}
- 수행평가 형식(Dogm): {task.get('submit_type', '—')}
- 컨설팅 종류(CrVV): {task.get('activity', '—')}
- 진행 상태(owtr): {task.get('status', '—')}
{f"- 신청일: {task['apply_date']}" if task.get('apply_date') else ""}
{f"- 학교 제출일: {task['due_date']}" if task.get('due_date') else ""}
{f"- 키워드(UfkI): {task['keyword']}" if task.get('keyword') else ""}
{f"- 비고: {task['note']}" if task.get('note') else ""}

## [파싱 완료] 요청사항 (RSt|)
{task.get('request_msg') or '없음'}

{f"## [파싱 완료] 세부능력 및 특기사항 (RuwY)" + chr(10) + task['setech'] if task.get('setech') else ""}

{f"## [파싱 완료] 생기부 방향성 (NVS@)" + chr(10) + task['bio_direction'] if task.get('bio_direction') else ""}

{f"## [파싱 완료] 시험범위 / 수업내용 (HR~K)" + chr(10) + task['study_range'] if task.get('study_range') else ""}

## [파싱 완료] 과거 수행 과제 이력
{past_tasks_text if past_tasks_text else "(이력 없음)"}

## [다운로드 완료] 첨부 파일
평가기준 및 양식 (gAMl):
{att_list}
수행평가 가이드 (mPfP) — 완성물/참고용, 분석 대상 아님:
{guide_list}
생기부 파일:
{bio_list}

---

## 작업 절차 (Claude Code가 수행할 작업)

STEP 1, STEP 2 다운로드는 이미 완료됨. 아래부터 수행한다.

### STEP 2. 이미지/파일 분석
files/ 폴더의 모든 첨부파일을 열어서 분석한다.
- **모든 문서 파일(.pptx, .docx, .pdf)의 텍스트는 이미 추출 완료되어 같은 폴더에 `.txt` 파일로 존재한다**
  - 예: `파일명.pptx` → `파일명.pptx.txt`, `생기부.pdf` → `생기부.pdf.txt`
  - 반드시 `.txt` 파일을 Read로 읽어서 분석할 것
  - 원본 .pptx/.docx/.pdf를 직접 파싱하려고 시도하지 말 것 (패키지 설치 금지: python-pptx, python-docx, pymupdf, poppler 등)
  - `.txt` 파일이 이미 있으므로 별도 도구나 패키지가 필요 없다
- 이미지 파일(.jpeg, .png 등)은 직접 열어서 분석한다
- 평가기준, 양식 항목, 배점, 분량, 지시사항을 빠짐없이 파악한다
- 이미지 첨부파일이 여러 장인 경우 **전부** 분석할 것 (일부만 보고 판단하지 말 것)
- 구글폼 양식이 있는 경우 폼 항목을 빠짐없이 파악할 것

### STEP 3. 사람 분석 (먼저 출력)
위 파싱된 데이터를 바탕으로 아래 항목을 정리해서 출력한다:
- 이름, 학교, 학년(위 grade 값 그대로), 진로/계열
- 생기부 방향성
- 탐구 주제 이력 요약
- 이전 과업 목록 (과목 + 상태 + 요청 핵심)
- 학생의 특징, 관심사, 작업 스타일

### STEP 4. 과제 분석 (이미지 + 텍스트 종합)
아래 항목을 모두 확인하고 출력한다:
- 과목, 수행평가 형식, 제출 마감
- 평가기준 및 양식(gAMl) 이미지에서 파악한 배점/항목
- (수행평가 가이드 mPfP는 완성물이므로 분석 불필요)
- 요청사항 분석 — 선생님 지시, 압박 질문 예상
- 키워드 참고
- 이전 활동과의 연결점
- **제출 형식 확인**: PPT 포함 여부, 발표 여부, 구글폼 여부, Word 여부 등

### STEP 5. 과제 작성
STEP 3, 4의 분석 결과를 출력한 후, 바로 작성에 들어간다.

**작성 원칙:**
- 학생의 진로와 반드시 연결할 것
- 이전 활동 이력을 자연스럽게 녹여낼 것
- 생기부 방향성 필드에 기재된 방향을 반영할 것
- AI 특유의 나열식 문체, "~할 수 있다" 반복 금지
- 소제목/번호 매기기 금지 (양식이 요구하는 경우 제외)
- **학년은 위 파싱된 grade 값 기준** — 임의로 고정하지 말 것
- 분량/형식은 수행평가 가이드 및 평가기준 이미지를 최우선으로 따를 것
- 출처가 필요한 경우 URL에 직접 접속해서 실존 여부를 확인할 것

**발표 대본 작성 원칙 (발표가 포함된 경우):**
- 발표 대본은 반드시 슬라이드별로 문단을 나눠 작성한다
- 각 문단 앞에 `[슬라이드 N — 제목]` 형식으로 표기한다
- 대본은 해당 슬라이드에서 말해야 할 내용을 빠짐없이 포함한다
  - 예산/후원/마케팅/프로그램 구성 등 모든 슬라이드 내용을 대본에 반영할 것
  - 특정 슬라이드 내용을 임의로 생략하지 말 것
- 전체 발표 시간 기준으로 자연스러운 분량을 유지한다

**PPT가 제출 형식에 포함된 경우 — Canva로 실제 PPTX 생성:**
Canva MCP 도구를 사용하여 실제 프레젠테이션을 생성하고 PPTX로 내보낸다.

**1단계: 슬라이드 스크립트 작성**
발표 시간과 과제 요구사항에 맞춰 슬라이드 수를 결정한다 (5분 기준 8슬라이드).
각 슬라이드마다 아래를 정리한다:
  - 제목
  - 발표 대본 (이 슬라이드에서 말할 내용)

**2단계: Canva 전달용 아웃라인 작성 — PPT 퀄리티를 결정하는 핵심 단계**
`generate-design-structured`에는 슬라이드별 `title` + `description`만 전달된다.
description 작성이 PPT 완성도를 좌우한다. 아래 규칙을 반드시 따를 것:

[description 작성 규칙]
1. 슬라이드에 표시할 핵심 텍스트를 구체적으로 기술 (숫자, 키워드, 짧은 문장)
2. 불릿은 3~5개, 한 불릿당 15단어 이내로 유지
3. 데이터가 있으면 구체적 수치 포함
4. 원하는 레이아웃 힌트 포함 (예: "좌측 이미지, 우측 텍스트 3줄")
5. 필요한 시각 요소 명시 (예: "원형 차트", "타임라인 그래픽")

[나쁜 예]
"공연 개요를 설명한다"

[좋은 예]
"공연명 'Ignite: 불꽃이 들려주는 음악의 밤'. 일시: 2026.6.15, 장소: 천안예술의전당 소공연장, 예상 관객 200명. 좌측에 공연장 야경 이미지, 우측에 정보 카드 4개(일시/장소/관객/컨셉). 다크 배경, 주황·빨강 포인트 색상."

[좋은 예 2]
"예산 총 1,900만 원 배분. 원형 차트: 공연장 대관 800만(42%), 음향·조명 400만(21%), 마케팅 300만(16%), 기타 400만(21%). 후원사 3곳 로고 하단 배치: 삼성뮤직펠로우십, 한화재단, 천안시문화재단."

**3단계: Canva 프레젠테이션 생성**
  - ⚠️ `request-outline-review`는 절대 사용하지 말 것 (비대화형 모드에서 위젯 불가)
  - **`generate-design-structured` 도구를 바로 호출**:
    - design_type: "presentation"
    - topic: 과제의 핵심 주제 (150자 이내, 단순 과제명이 아닌 구체적 주제)
    - audience: "educational" (학교 수행평가이므로)
    - style: 과제 분위기에 맞게 선택:
      - 학술/보고서 → "minimalist"
      - 예술/문화 기획 → "elegant"
      - 과학/기술 → "digital" 또는 "geometric"
      - 활동/행사 → "playful"
    - length: "balanced"
    - presentation_outlines: 2단계에서 작성한 슬라이드별 title + description 배열
  - `create-design-from-candidate` 도구로 첫 번째 후보 확정

**3단계: 세부 편집 (필요시)**
  - `start-editing-transaction` → `perform-editing-operations` → `commit-editing-transaction`
  - 텍스트 수정, 이미지 교체, 포맷 조정

**4단계: PPTX + 미리보기 이미지 내보내기**
  - `export-design` 도구로 format type "pptx"로 내보내기 → pptx_download_url 기록
  - `export-design` 도구로 format type "png"로 내보내기 → 슬라이드별 미리보기 이미지 URL 기록
  - result.json의 해당 output에 아래 필드 모두 기록:
    - canva_edit_url, canva_view_url, pptx_download_url
    - preview_images: [슬라이드별 PNG URL 배열]

**발표 대본은 별도로 result.md에 저장한다** (슬라이드별 문단 구분 유지)

**모든 텍스트 산출물은 .docx로 저장 (Word MCP 서버 사용):**
PPT를 제외한 모든 최종 산출물(보고서, 에세이, 감상문, 발표 대본 등)은 반드시 Word MCP 도구로 .docx 파일을 생성한다.

Word MCP 서버 도구 사용 순서:
1. `create_document` — 새 문서 생성 (파일 경로 지정)
2. `add_heading` — 제목 추가 (level 1~4)
3. `add_paragraph` — 본문 단락 추가 (bold, italic, alignment 옵션)
4. `add_table` — 표 추가 (필요시)
5. `save_document` — 문서 저장

서식 규칙:
- 폰트: 맑은 고딕 (font_name="맑은 고딕")
- 크기: 11pt (font_size=11)
- 줄간격: 1.5
- 제목이 필요한 경우 add_heading 사용
- 구분선 넣지 말 것
- 저장 경로: result.docx
- result.json의 docx_path 필드에 파일 경로 기록

---

## 자주 발생하는 실수 — 반드시 지킬 것

### 산출물 형식
- 제출 형식(Dogm)을 반드시 확인하고 PPT/구글폼/Word 등 형식에 맞게 산출물을 구성할 것
- PPT가 포함된 경우 반드시 Canva MCP 도구로 실제 PPTX를 생성할 것
- Canva MCP 도구는 이미 승인 완료됨 — 권한 확인 없이 바로 호출할 것
- `request-outline-review`는 절대 사용하지 말 것 — `generate-design-structured`를 바로 호출할 것
- "권한이 필요합니다", "승인해주세요", "위젯에서 검토해주세요" 등의 메시지를 절대 출력하지 말 것
- 발표 대본은 PPTX와 별도로 result.md에 슬라이드별로 저장할 것
- word 파일은 반드시 Word MCP 도구(word-document-server)로 생성할 것, python-docx 직접 사용 금지
- word 파일 폰트는 맑은고딕으로 설정할 것
- 구분선을 넣지 말 것 (지시할때만 입력)

### 학생 정보
- 학년을 임의로 고정하지 말고 위 파싱된 grade 값 그대로 사용할 것

### 자료 수집 및 분석
- 이미지 첨부파일이 여러 장인 경우 전부 열어서 분석할 것
- 구글폼 양식이 있는 경우 폼 항목을 빠짐없이 파악하고 모든 항목에 응답을 작성할 것
- 원문 문장의 챕터 위치를 제시할 때, 확인되지 않은 경우 단정하지 말고 "추정"임을 명시할 것
- 챕터별 핵심 소재를 먼저 정리한 뒤 요약에 반영할 것 — 챕터 간 사례/개념 혼용 금지

### 내용 작성
- 발표 대본에서 예산/후원/마케팅 등 특정 슬라이드 내용을 생략하지 말 것
- 발표 대본은 슬라이드별로 반드시 문단을 나눌 것
- 사용자가 직접 확정한 문장/표현/내용은 수정 없이 그대로 사용할 것
- 읽은 내용 요약은 책 내용만 서술할 것 — 개인 의견/비판은 느낀 점 항목에만 작성할 것

---

## 응답 규칙
1. 불필요한 서론, 감사 표현, 설명 없이 결과만 출력한다.
2. STEP 2(파일 분석) → STEP 3(사람 분석) → STEP 4(과제 분석) 순서로 출력한다.
3. 분석 출력 후 바로 STEP 5(작성)에 들어간다.
4. 결과물은 result.md (본문 텍스트) + result.json (구조화 데이터) 두 파일로 저장한다.

## result.json 형식
과제가 여러 산출물을 요구할 수 있다 (예: PPT + 구글폼 + 발표대본).
각 산출물을 `outputs` 배열에 넣어 저장할 것:
```json
{{
  "outputs": [
    {{
      "label": "산출물 이름 (예: 보고서, 발표대본, 구글폼 응답 등)",
      "type": "docx | pptx | text | form",
      "file": "파일명 (예: report.docx, script.docx)",
      "canva_edit_url": "Canva 편집 URL (pptx인 경우만)",
      "canva_view_url": "Canva 보기 URL (pptx인 경우만)",
      "pptx_download_url": "PPTX 다운로드 URL (pptx인 경우만)"
    }}
  ]
}}
```
- 산출물 하나당 배열 요소 하나
- type이 docx이면 Word MCP로 .docx 파일 생성 후 file에 파일명 기록
- type이 pptx이면 Canva로 생성 후 URL 기록
- type이 text이면 .md 파일로 저장 (자필 유인물 등 docx 불필요한 경우)
- type이 form이면 구글폼 응답을 .md 파일로 저장
- 모든 산출물의 텍스트 원문은 반드시 개별 파일로도 저장할 것
"""

    (ws / "CLAUDE.md").write_text(claude_md, encoding="utf-8")

    return ws


def launch_pre_analysis(task: dict, workspace: Path) -> bool:
    """
    Claude Code 터미널로 STEP 2~4 사전분석 실행.
    분석 결과는 analysis.md + analysis.json에 저장됨.
    """
    instruction = f"""CLAUDE.md를 읽고, files/ 폴더의 첨부파일을 분석한 뒤,
**STEP 2(파일 분석) → STEP 3(사람 분석) → STEP 4(과제 분석)**만 수행하세요.
STEP 5(과제 작성)는 하지 마세요.

과제: {task.get('title', '')}
과목: {task.get('subject', '')}
형식: {task.get('submit_type', '')}
학생: {task.get('name', '')} ({task.get('grade', '')}, {task.get('school', '')})

분석 결과를 아래 형식으로 출력하고, analysis.md 파일로 저장하세요:

[STEP 3 — 사람 분석]
(이름, 학교, 학년, 진로/계열, 생기부 방향성, 탐구 주제 이력, 이전 과업 이력, 특징 및 작업 스타일)

[STEP 4 — 과제 분석]
(과목, 형식, 마감, 평가기준/배점, 요청사항 분석, 제출 형식 확인, 모호한 점 지적)

[작업 계획]
(어떤 순서로, 어떤 내용을, 어떤 형식으로 작성할지 구체적 계획)

마지막으로 analysis.json 파일도 저장하세요:
{{"status": "ok", "analysis": "(analysis.md 내용 전체)"}}"""

    block_id = task.get("block_id", "")
    return launch_background(workspace, instruction, block_id, "사전분석")


def get_analysis(block_id: str) -> dict | None:
    """워크스페이스에서 캐싱된 사전분석 읽기"""
    ws = get_workspace_path(block_id)
    if not ws:
        return None
    analysis_file = ws / "analysis.json"
    if analysis_file.exists():
        return json.loads(analysis_file.read_text(encoding="utf-8"))
    return None


def _save_memo_log(block_id: str, action: str, memo: str):
    """추가 지시사항/수정 요청 이력 저장"""
    ws = get_workspace_path(block_id)
    if not ws or not memo:
        return
    log_file = ws / "memo_log.json"
    logs = []
    if log_file.exists():
        logs = json.loads(log_file.read_text(encoding="utf-8"))
    logs.append({
        "action": action,
        "memo": memo,
        "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "result_snapshot": None,  # job 완료 시 채워짐
    })
    log_file.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


def _attach_result_to_log(block_id: str, warning: str | None = None):
    """마지막 로그 항목에 현재 result.json 스냅샷 + 오류 정보 첨부"""
    ws = get_workspace_path(block_id)
    if not ws:
        return
    log_file = ws / "memo_log.json"
    if not log_file.exists():
        return
    try:
        logs = json.loads(log_file.read_text(encoding="utf-8"))
        if not logs:
            return

        # 오류 기록
        if warning:
            logs[-1]["error"] = warning
            logs[-1]["result_snapshot"] = logs[-1].get("result_snapshot") or []
        else:
            logs[-1]["error"] = None
            # 정상 완료 시 result.json 스냅샷 첨부
            result_file = ws / "result.json"
            if result_file.exists():
                result = json.loads(result_file.read_text(encoding="utf-8"))
                summary = []
                for o in result.get("outputs", []):
                    s = {"label": o.get("label", ""), "type": o.get("type", ""), "file": o.get("file", "")}
                    if o.get("canva_edit_url"):
                        s["canva_edit_url"] = o["canva_edit_url"]
                    if o.get("pptx_download_url"):
                        s["pptx_download_url"] = o["pptx_download_url"]
                    summary.append(s)
                logs[-1]["result_snapshot"] = summary

        log_file.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_memo_log(block_id: str) -> list:
    """추가 지시사항 이력 조회"""
    ws = get_workspace_path(block_id)
    if not ws:
        return []
    log_file = ws / "memo_log.json"
    if log_file.exists():
        return json.loads(log_file.read_text(encoding="utf-8"))
    return []


def run_verification(task: dict) -> bool:
    """
    산출물 검증 실행 — Claude Code 백그라운드로 검증 수행.
    result.json/result.md를 읽고, CLAUDE.md의 기준 대비 검증.
    결과는 verification.json에 저장됨.
    """
    block_id = task.get("block_id", "")
    ws = get_workspace_path(block_id)
    if not ws:
        return False

    result = get_result(block_id)
    if not result:
        return False

    instruction = f"""CLAUDE.md를 읽고, 현재 산출물(result.json, result.md, 및 관련 파일)을 검증하세요.

## 검증 항목

### 1. 기본 요건 충족 확인
- 제출 형식(Dogm)과 실제 산출물 형식이 일치하는지
- 요청사항(RSt|)에 명시된 사항이 모두 반영되었는지
- 평가기준 이미지의 채점 항목이 모두 충족되었는지

### 2. 내용 품질 검증
- AI 특유의 문체(나열식, "~할 수 있다" 반복 등)가 남아있는지
- 학생의 진로/계열과 내용이 자연스럽게 연결되는지
- 분량이 적절한지 (평가기준 기준)
- 소제목/번호 매기기 남용이 없는지 (양식 요구가 아닌 경우)

### 3. 사실 관계 검증
- 출처 URL이 있는 경우 실제 접속 가능한지 확인
- 학년, 학교 등 기본 정보가 정확한지

### 4. 파일 무결성
- result.json의 outputs 배열과 실제 파일 존재 여부 일치 확인
- docx 파일이 정상적으로 열리는지 (파일 크기 > 0)
- PPT가 있는 경우 canva_edit_url, pptx_download_url 존재 확인

## 출력 형식

검증 결과를 verification.json으로 저장:
```json
{{
  "status": "pass" 또는 "fail" 또는 "warning",
  "timestamp": "검증 시각",
  "score": 0-100,
  "summary": "전체 요약 (1-2줄)",
  "checks": [
    {{
      "category": "기본 요건 | 내용 품질 | 사실 관계 | 파일 무결성",
      "item": "검증 항목명",
      "status": "pass | fail | warning",
      "detail": "상세 설명"
    }}
  ],
  "recommendations": ["개선 제안 1", "개선 제안 2"]
}}
```

과제: {task.get('title', '')}
과목: {task.get('subject', '')}
형식: {task.get('submit_type', '')}
학생: {task.get('name', '')} ({task.get('grade', '')}, {task.get('school', '')})"""

    return launch_background(ws, instruction, block_id, "검증")


def build_instruction(task: dict, user_memo: str = "") -> str:
    """Claude Code에 전달할 초기 프롬프트 — 캐싱된 분석이 있으면 STEP 5부터 시작"""
    block_id = task.get("block_id", "")
    if user_memo:
        _save_memo_log(block_id, "초안 작성", user_memo)
    _refresh_claude_md(task)
    analysis = get_analysis(block_id)

    if analysis and analysis.get("status") == "ok":
        # 사전분석 완료 → STEP 5만 실행
        instruction = f"""CLAUDE.md를 읽고, files/ 폴더의 첨부파일을 확인한 뒤,
아래 사전분석 결과를 바탕으로 **STEP 5(과제 작성)**를 바로 수행해주세요.

## 사전분석 결과 (STEP 3 + STEP 4 완료)
{analysis['analysis']}

## 과제 기본정보
과제: {task.get('title', '')}
과목: {task.get('subject', '')}
형식: {task.get('submit_type', '')}
학생: {task.get('name', '')} ({task.get('grade', '')}, {task.get('school', '')})

{f"## 추가 지시사항" + chr(10) + user_memo if user_memo else ""}

산출물별로 개별 파일 + result.json(outputs 배열)으로 저장해주세요."""
    else:
        # 사전분석 없음 → 전체 수행
        instruction = f"""CLAUDE.md를 읽고, files/ 폴더의 첨부파일을 모두 분석한 뒤,
STEP 2 → STEP 3 → STEP 4 → STEP 5 순서로 작업을 수행해주세요.

과제: {task.get('title', '')}
과목: {task.get('subject', '')}
형식: {task.get('submit_type', '')}
학생: {task.get('name', '')} ({task.get('grade', '')}, {task.get('school', '')})

{f"추가 지시사항: {user_memo}" if user_memo else ""}

산출물별로 개별 파일 + result.json(outputs 배열)으로 저장해주세요."""
    return instruction


def _refresh_claude_md(task: dict):
    """기존 워크스페이스의 CLAUDE.md만 최신 템플릿으로 재생성 (파일 다운로드 안 함)"""
    ws = get_workspace_path(task.get("block_id", ""))
    if not ws:
        return
    # create_workspace를 호출하면 같은 경로에 CLAUDE.md를 덮어씀
    # 이미 다운로드된 파일은 _download_file이 기존 파일 위에 다시 쓰지만 빠름
    create_workspace(task)


def build_revision_instruction(task: dict, revision_memo: str) -> str:
    """기존 산출물 수정 프롬프트"""
    block_id = task.get("block_id", "")
    _refresh_claude_md(task)
    ws = get_workspace_path(block_id)

    # 현재 산출물 목록 파악
    existing_files = []
    if ws:
        for f in ws.iterdir():
            if f.is_file() and f.suffix in (".md", ".docx", ".txt") and f.name not in ("CLAUDE.md", "analysis.md", ".prompt.txt"):
                existing_files.append(f.name)
        result_file = ws / "result.json"
        if result_file.exists():
            result_data = json.loads(result_file.read_text(encoding="utf-8"))
            outputs = result_data.get("outputs", [])
            for o in outputs:
                if o.get("file"):
                    existing_files.append(o["file"])

    file_list = "\n".join(f"  - {f}" for f in sorted(set(existing_files))) if existing_files else "  (산출물 없음)"

    return f"""CLAUDE.md를 읽고, 기존 산출물을 수정해주세요.

## 현재 산출물 파일
{file_list}

## 수정 요청
{revision_memo}

## 수정 원칙
- 기존 파일을 읽고 요청된 부분만 수정할 것
- 수정하지 않은 부분은 원문 그대로 유지할 것
- 수정 후 같은 파일명으로 덮어쓸 것
- result.json도 업데이트할 것
- 사용자가 직접 확정한 문장/표현은 수정하지 말 것

과제: {task.get('title', '')}
학생: {task.get('name', '')} ({task.get('grade', '')}, {task.get('school', '')})"""


def launch_revision(task: dict, revision_memo: str) -> bool:
    """기존 산출물 수정을 위한 Claude Code 백그라운드 실행"""
    block_id = task.get("block_id", "")
    if revision_memo:
        _save_memo_log(block_id, "수정 요청", revision_memo)
    ws = get_workspace_path(block_id)
    if not ws:
        return False
    instruction = build_revision_instruction(task, revision_memo)
    return launch_background(ws, instruction, block_id, "수정")


# 실행 중인 프로세스 추적: block_id → [job, job, ...] (다중 작업 지원)
import time as _time
_running_jobs: dict[str, list] = {}


def launch_background(workspace_path: Path, instruction: str, block_id: str, label: str = "작업") -> bool:
    """Claude Code를 백그라운드 프로세스로 실행 (-p 모드)"""
    ws = str(workspace_path)

    # 작업별 고유 파일 (덮어쓰기 방지)
    job_id = f"{label}_{int(_time.time())}"
    prompt_file = workspace_path / f".prompt_{job_id}.txt"
    prompt_file.write_text(instruction, encoding="utf-8")

    output_file = workspace_path / f".output_{job_id}.txt"
    error_file = workspace_path / f".error_{job_id}.txt"

    try:
        proc = subprocess.Popen(
            [
                "claude", "-p",
                "--output-format", "text",
                "--permission-mode", "bypassPermissions",
            ],
            stdin=open(prompt_file, "r"),
            stdout=open(output_file, "w"),
            stderr=open(error_file, "w"),
            cwd=ws,
        )

        job = {
            "job_id": job_id,
            "pid": proc.pid,
            "process": proc,
            "start_time": _time.time(),
            "status": "running",
            "label": label,
            "workspace": ws,
            "output_file": str(output_file),
            "error_file": str(error_file),
            "warning": None,
        }

        if block_id not in _running_jobs:
            _running_jobs[block_id] = []
        _running_jobs[block_id].append(job)

        # 백그라운드 스레드에서 완료 감시 + 문제 감지 + 임시파일 정리
        import threading
        def _watch():
            proc.wait()
            job["status"] = "complete" if proc.returncode == 0 else "error"
            job["end_time"] = _time.time()
            job["returncode"] = proc.returncode
            # output 파일에서 문제 감지
            warning = _detect_issues(output_file, error_file)
            job["warning"] = warning
            if warning:
                _save_warning(ws, job_id, label, warning)
            else:
                _clear_warning(ws)
            # 결과물 이력 기록 (오류 포함)
            _attach_result_to_log(block_id, warning)
            # 완료된 job의 임시 파일 정리 (최신 1개만 유지)
            _cleanup_job_files(Path(ws))

        threading.Thread(target=_watch, daemon=True).start()
        return True

    except Exception as e:
        print(f"[background] 실행 실패: {e}")
        return False


def _save_warning(workspace: str, job_id: str, label: str, warning: str):
    """경고를 워크스페이스 파일에 저장"""
    wpath = Path(workspace) / ".warning.json"
    wpath.write_text(json.dumps({
        "job_id": job_id,
        "label": label,
        "warning": warning,
        "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False), encoding="utf-8")


def _clear_warning(workspace: str):
    """경고 파일 제거 (정상 완료 시)"""
    wpath = Path(workspace) / ".warning.json"
    if wpath.exists():
        wpath.unlink()


def get_warning(block_id: str) -> dict | None:
    """워크스페이스의 미해결 경고 조회"""
    ws = get_workspace_path(block_id)
    if not ws:
        return None
    wpath = ws / ".warning.json"
    if wpath.exists():
        return json.loads(wpath.read_text(encoding="utf-8"))
    return None


def _cleanup_job_files(workspace: Path):
    """완료된 job 임시 파일 정리 — 최신 1개만 유지"""
    for prefix in [".output_", ".error_", ".prompt_", ".expect_"]:
        files = sorted(workspace.glob(f"{prefix}*"), key=lambda f: f.stat().st_mtime, reverse=True)
        # 최신 1개 유지, 나머지 삭제
        for f in files[1:]:
            try:
                f.unlink()
            except Exception:
                pass


def _detect_issues(output_file: Path, error_file: Path) -> str | None:
    """output/error 파일에서 권한 문제 등 감지"""
    issues = []
    for fpath in [output_file, error_file]:
        fpath = Path(fpath)
        if not fpath.exists():
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")[:3000]
        except Exception:
            continue
        # 권한/승인 문제
        if any(kw in text for kw in ["권한", "permission", "승인", "Permission denied", "not allowed"]):
            if "Canva" in text or "canva" in text:
                issues.append("Canva MCP 권한 문제")
            elif "word" in text.lower() or "Word" in text:
                issues.append("Word MCP 권한 문제")
            else:
                issues.append("MCP 권한 문제")
        # 인증 만료
        if any(kw in text for kw in ["auth", "token expired", "401", "인증"]):
            issues.append("인증 만료 가능성")
        # rate limit
        if any(kw in text for kw in ["rate limit", "429", "too many requests"]):
            issues.append("API 요청 제한")
    return " · ".join(issues) if issues else None


def get_job_status(block_id: str) -> dict | None:
    """실행 중인 작업 상태 조회 — 모든 활성 작업 반환"""
    jobs = _running_jobs.get(block_id, [])
    if not jobs:
        return None

    active = []
    warnings = []
    for j in jobs:
        elapsed = _time.time() - j["start_time"]
        active.append({
            "job_id": j["job_id"],
            "status": j["status"],
            "label": j["label"],
            "elapsed_seconds": int(elapsed),
            "pid": j["pid"],
            "warning": j.get("warning"),
        })
        if j.get("warning"):
            warnings.append(j["warning"])

    # 완료된 지 5분 지난 작업 정리
    _running_jobs[block_id] = [
        j for j in jobs
        if j["status"] == "running" or _time.time() - j.get("end_time", _time.time()) < 300
    ]

    warning_text = " · ".join(set(warnings)) if warnings else None

    # running이 있으면 running 우선 반환
    running = [a for a in active if a["status"] == "running"]
    if running:
        return {"status": "running", "jobs": active, "label": ", ".join(r["label"] for r in running),
                "elapsed_seconds": max(a["elapsed_seconds"] for a in running), "pid": running[0]["pid"],
                "warning": warning_text}

    # 전부 완료면 가장 최근 것
    latest = max(active, key=lambda a: a["elapsed_seconds"])
    return {"status": latest["status"], "jobs": active, "label": latest["label"],
            "elapsed_seconds": latest["elapsed_seconds"], "pid": latest["pid"],
            "warning": warning_text}


def get_workspace_path(block_id: str) -> Path | None:
    """block_id로 워크스페이스 경로 조회 (매핑 캐시 + 디스크 탐색)"""
    if block_id in _workspace_map:
        return _workspace_map[block_id]
    # 디스크에서 탐색 (block_id 앞 8자로 매칭)
    short = block_id[:8]
    if BASE_DIR.exists():
        for d in BASE_DIR.iterdir():
            if d.is_dir() and short in d.name:
                _workspace_map[block_id] = d
                return d
    return None


def get_result(block_id: str) -> dict | None:
    """워크스페이스에서 result.json 읽기"""
    ws = get_workspace_path(block_id)
    if not ws:
        return None
    result_file = ws / "result.json"
    if result_file.exists():
        return json.loads(result_file.read_text(encoding="utf-8"))
    # result.json 없으면 result.md라도 읽기
    md_file = ws / "result.md"
    if md_file.exists():
        return {"text": md_file.read_text(encoding="utf-8")}
    return None


def save_result(block_id: str, data: dict) -> bool:
    """워크스페이스에 result.json 저장"""
    ws = get_workspace_path(block_id)
    if not ws:
        return False
    result_file = ws / "result.json"
    # 기존 결과와 병합
    existing = {}
    if result_file.exists():
        existing = json.loads(result_file.read_text(encoding="utf-8"))
    existing.update(data)
    result_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
