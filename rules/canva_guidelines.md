## PPT 제출 형식 — Canva로 실제 PPTX 생성

Canva MCP 도구를 사용하여 실제 프레젠테이션을 생성하고 PPTX로 내보낸다.

### 1단계: 슬라이드 스크립트 작성
발표 시간과 과제 요구사항에 맞춰 슬라이드 수를 결정한다 (5분 기준 8슬라이드).
각 슬라이드마다 아래를 정리한다:
  - 제목
  - 발표 대본 (이 슬라이드에서 말할 내용)

### 2단계: Canva 전달용 아웃라인 작성 — PPT 퀄리티를 결정하는 핵심 단계
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

### 3단계: Canva 프레젠테이션 생성
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

### 4단계: 세부 편집 (필요시)
  - `start-editing-transaction` → `perform-editing-operations` → `commit-editing-transaction`
  - 텍스트 수정, 이미지 교체, 포맷 조정

### 5단계: PPTX + 미리보기 이미지 내보내기
  - `export-design` 도구로 format type "pptx"로 내보내기 → pptx_download_url 기록
  - `export-design` 도구로 format type "png"로 내보내기 → 슬라이드별 미리보기 이미지 URL 기록
  - result.json의 해당 output에 아래 필드 모두 기록:
    - canva_edit_url, canva_view_url, pptx_download_url
    - preview_images: [슬라이드별 PNG URL 배열]

**발표 대본은 별도로 result.md에 저장한다** (슬라이드별 문단 구분 유지)
