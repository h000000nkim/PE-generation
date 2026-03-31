## 문서 산출물 — Word / HWPX MCP 서버 사용 규칙

PPT를 제외한 모든 최종 산출물(보고서, 에세이, 감상문, 발표 대본, 자필 유인물 등)은 제출 형식에 따라 Word MCP 또는 HWPX MCP 도구로 생성한다.

### 형식 판단 기준
- 수행평가 형식(Dogm)이 "한글", "HWP", "hwp", "hwpx"를 포함하면 → **HWPX MCP** (`hwpx-document-server`) 사용
- 그 외(워드, Word, docx 등) → **Word MCP** (`word-document-server`) 사용
- 자필(유인물) 형식이더라도 반드시 문서 파일로 작성한다 — 학생이 옮겨 쓸 원본으로 사용된다

### 도구 사용 순서
1. `create_document` — 새 문서 생성 (파일 경로 지정)
2. `add_heading` — 제목 추가 (level 1~4)
3. `add_paragraph` — 본문 단락 추가 (bold, italic, alignment 옵션)
4. `add_table` — 표 추가 (필요시)
5. `save_document` — 문서 저장

### 서식 규칙
- 폰트: "Malgun Gothic" (font_name="Malgun Gothic") — Word 환경에 따라 영문명으로 입력해야 적용되므로 영문명 우선
- 크기: 11pt (font_size=11)
- 줄간격: 1.5
- 본문 단락 정렬: 양끝 맞춤(justify) 고정 — 대제목(add_heading) 제외
- **글자 색상: 반드시 검정(#000000)만 사용** — 컬러 글자 금지
- **표 배경색: 색상이 필요한 경우 흑백 음영(회색 계열)만 사용** — 컬러 배경 금지 (예: 헤더 행은 연한 회색 #D9D9D9)
- 제목이 필요한 경우 add_heading 사용
- 구분선 넣지 말 것
- **저장 파일명: `과목_과제제목_이름.확장자` 형식** (response_rules.md 참조) — `result.docx` 같은 임시 이름 금지
- result.json의 file 필드에 파일명 기록

## HWPX 산출물 — HWPX MCP 서버 사용 규칙

제출 형식이 한글(HWP/HWPX)인 경우 HWPX MCP 도구(`hwpx-document-server`)로 .hwpx 파일을 생성한다.

### 도구 사용 순서
1. `create_document` — 새 문서 생성 (파일 경로 지정)
2. `add_heading` — 제목 추가
3. `add_paragraph` — 본문 단락 추가
4. `add_table` — 표 추가 (필요시)
5. `format_text` — 서식 적용 (필요시)

### 서식 규칙
- 기본 서식은 HWPX 기본값을 따름 (한글 프로그램 기본 설정과 호환)
- **글자 색상: 반드시 검정만 사용** — 컬러 글자 금지
- **표 배경색: 색상이 필요한 경우 흑백 음영(회색 계열)만 사용** — 컬러 배경 금지
- 제목이 필요한 경우 `add_heading` 사용
- 구분선 넣지 말 것
- **저장 파일명: `과목_과제제목_이름.hwpx` 형식** (response_rules.md 참조) — `result.hwpx` 같은 임시 이름 금지
- result.json의 file 필드에 파일명 기록, type은 `"hwpx"`로 설정
