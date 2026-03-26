# 수행평가 대시보드

Notion에서 수행평가 과업을 파싱하고 Claude API 작업 지시서를 검토하는 웹 대시보드입니다.

---

## 설치 (Mac Mini M4 기준)

### 1. Python 패키지 설치
```bash
pip3 install fastapi uvicorn jinja2 python-multipart pillow requests httpx python-dotenv anthropic
```

### 2. 환경변수 설정
```bash
cp .env.example .env
```
`.env` 파일을 열어 Anthropic API 키 입력:
```
ANTHROPIC_API_KEY=sk-ant-여기에_실제_키_입력
NOTION_PAGE_ID=32946991-dbbd-81ed-9f81-dbed9ba2296d
```

### 3. 서버 실행
```bash
cd 프로젝트_폴더
python3 main.py
```

브라우저에서 `http://localhost:8000` 접속

---

## 외부 접속 (ngrok, 선택)

외부에서 접속하고 싶을 때만 사용:
```bash
# ngrok 설치 (최초 1회)
brew install ngrok

# 터널 열기
ngrok http 8000
```
출력된 `https://xxxx.ngrok.io` 주소로 외부 접속 가능

---

## Mac Mini 상시 실행 (launchd)

터미널 꺼도 계속 실행되게 하려면:

```bash
# ~/Library/LaunchAgents/com.pe.dashboard.plist 생성
cat > ~/Library/LaunchAgents/com.pe.dashboard.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.pe.dashboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/여기에유저명/pe/main.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>/Users/여기에유저명/pe</string>
</dict>
</plist>
EOF

# 등록
launchctl load ~/Library/LaunchAgents/com.pe.dashboard.plist
```

---

## 화면 구성

| 경로 | 설명 |
|------|------|
| `/` | 전체 수행평가 목록 (상태별 카드) |
| `/task/{id}` | 과업 상세 + 첨부 이미지 분석 + 메모 입력 |
| `POST /api/build-prompt` | Claude API 전송용 프롬프트 조립 |

---

## 다음 단계 (개발 예정)

- [ ] Claude API 실제 전송 및 초안 수신
- [ ] 웹검색 tool_use 연동
- [ ] URL 검증기 통합
- [ ] Notion 결과 자동 기입
