## 응답 규칙
1. 불필요한 서론, 감사 표현, 설명 없이 결과만 출력한다.
2. STEP 2(파일 분석) → STEP 3(사람 분석) → STEP 4(과제 분석) 순서로 출력한다.
3. 분석 출력 후 바로 STEP 5(작성)에 들어간다.
4. 결과물은 result.md (본문 텍스트) + result.json (구조화 데이터) 두 파일로 저장한다.

## result.json 형식
과제가 여러 산출물을 요구할 수 있다 (예: PPT + 구글폼 + 발표대본).
각 산출물을 `outputs` 배열에 넣어 저장할 것:
```json
{
  "outputs": [
    {
      "label": "산출물 이름 (예: 보고서, 발표대본, 구글폼 응답 등)",
      "type": "docx | pptx | text | form",
      "file": "파일명 (예: report.docx, script.docx)",
      "canva_edit_url": "Canva 편집 URL (pptx인 경우만)",
      "canva_view_url": "Canva 보기 URL (pptx인 경우만)",
      "pptx_download_url": "PPTX 다운로드 URL (pptx인 경우만)"
    }
  ]
}
```
- 산출물 하나당 배열 요소 하나
- type이 docx이면 Word MCP로 .docx 파일 생성 후 file에 파일명 기록
- type이 pptx이면 Canva로 생성 후 URL 기록
- type이 text이면 .md 파일로 저장 (자필 유인물 등 docx 불필요한 경우)
- type이 form이면 구글폼 응답을 .md 파일로 저장
- 모든 산출물의 텍스트 원문은 반드시 개별 파일로도 저장할 것
