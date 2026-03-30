# PE-generation 작업 기록

## 2026-03-30 — 검증 워크플로우 완성 (3차)

### 다른 세션에서 추가된 변경 (7696d44 → 1eff501)
- 보안 패치: Path Traversal 방어, 프록시 도메인 허용 목록, 스레드 안전 캐시(`_task_cache_lock`)
- 프로세스 관리: `_kill_same_label_jobs()` — 같은 작업 재실행 시 기존 프로세스 종료
- 신규: `delete_analysis()`, `DELETE /api/analysis/{id}`, 로깅 인프라(`logging`)
- 구조 개선: CLAUDE.md → `rules/` 디렉토리로 분리, 대시보드 날짜 정렬
- 레거시 삭제: `claude_pipeline.py`, `image_analyzer.py` 완전 삭제

### 이번 세션 구현 내역

#### 1. CLI 검증 스크립트 (`verify.py`)
- `uv run python verify.py` — 결과 있는 전체 과제 검증
- `uv run python verify.py <block_id>` — 특정 과제 검증
- `uv run python verify.py --status` — 전체 검증 상태 조회
- `uv run python verify.py --status <block_id>` — 특정 과제 검증 결과 조회
- 웹 API(`localhost:8000`)를 통해 실행하므로 서버가 실행 중이어야 함

#### 2. 일괄 검증 API (`POST /api/batch-verify`)
- 대시보드에서 여러 과제 선택 후 "검증" 버튼으로 일괄 실행
- `run_in_executor`로 비동기 처리

#### 3. 대시보드 검증 배지
- `my-tasks` API에 `verify_status` 필드 추가 (pass/fail/warning/null)
- `get_verification_status()` 함수 — verification.json에서 상태만 빠르게 읽기
- 대시보드 카드에 검증통과/검증실패/검증경고 배지 표시
- 검증 중일 때는 배지 숨김

#### 4. 초안 완료 후 자동 검증
- `_watch()` 스레드에서 `label == "초안 작성"` && 정상 완료 && 경고 없음 시 `_auto_verify()` 호출
- `_auto_verify()` — `parse_task_from_block` + `run_verification` 순차 실행
- 초안 작성 → 자동 검증 → 대시보드 배지 갱신까지 자동

### 검증 시스템 전체 아키텍처
```
[웹 UI]
  상세 페이지 "검증 실행" 버튼 → POST /api/verify/{id}
  대시보드 "검증" 버튼 (일괄) → POST /api/batch-verify
  검증 결과 카드 표시 ← GET /api/verify/{id}
  대시보드 배지 ← GET /api/my-tasks (verify_status 필드)

[CLI]
  uv run python verify.py [--status] [block_id]
  → localhost:8000 API 경유

[자동]
  초안 작성 완료 → _watch() → _auto_verify() → run_verification()

[실행 엔진]
  run_verification() → launch_background()
    → claude -p --permission-mode bypassPermissions
    → verification.json 생성
```

### 프로젝트 구조
```
main.py                          — FastAPI 서버
verify.py                        — CLI 검증 도구 (NEW)
CLAUDE.md                        — 전역 규칙 (rules/ 참조)
rules/
  writing_principles.md          — 작성 원칙
  canva_guidelines.md            — Canva PPT 생성 가이드
  word_guidelines.md             — Word 문서 생성 가이드
  common_mistakes.md             — 자주 발생하는 실수
  response_rules.md              — 응답 규칙 + result.json 형식
modules/
  notion_parser.py               — Notion 비공식 API 파싱
  workspace_launcher.py          — 워크스페이스 생성, Claude Code 실행, 검증
  url_validator.py               — URL 검증
templates/
  dashboard.html                 — 대시보드 (탭: 진행중/완료/잠금, 검증 배지)
  detail.html                    — 상세 페이지 (학생정보, 과제정보, 분석, 작성, 검증)
workspaces/                      — 학생별 워크스페이스 디렉토리
```
