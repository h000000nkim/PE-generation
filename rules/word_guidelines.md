## Word 산출물 — Word MCP 서버 사용 규칙

PPT를 제외한 모든 최종 산출물(보고서, 에세이, 감상문, 발표 대본, 자필 유인물 등)은 반드시 Word MCP 도구로 .docx 파일을 생성한다.
자필(유인물) 형식이더라도 반드시 .docx로 작성한다 — 학생이 옮겨 쓸 원본으로 사용된다.

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
- 제목이 필요한 경우 add_heading 사용
- 구분선 넣지 말 것
- 저장 경로: 파일명 규칙에 따라 저장 (response_rules.md 참조)
- result.json의 file 필드에 파일명 기록
