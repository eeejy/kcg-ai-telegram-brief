# 오늘의 해양경찰 AI 동향

해양경찰 AI팀이 알아야 할 공개 뉴스를 수집해 월~금 오전 08:00(Asia/Seoul)에 Telegram 채널로 전송하는 무과금 최소 기능 프로젝트입니다.

## 브리핑 구성

1. ⚓ 해양치안 AI
2. 🏛️ AI 정책·제도
3. 🚨 유관기관·공공안전 AI
4. 🔥 AI 산업·핫이슈
5. 🛠️ AI 도구·업데이트
6. 🛡️ AI 보안·윤리
7. 🎓 AI 학습·교육

직전 24시간 기사 중 최대 12건을 보내며, 제목·출처·게시 시각·원문 링크만 사용합니다. 매주 월요일에는 [`learning.yml`](learning.yml)의 AI 용어를 하나씩 순환해 해양경찰 업무 관점의 설명을 덧붙입니다.

## 원칙

- 기사 본문과 사진을 복제하지 않습니다.
- Telegram 토큰과 채널 ID를 코드에 저장하지 않습니다.
- LLM 및 유료 뉴스 API를 사용하지 않습니다.
- 동일 제목·링크의 중복 기사는 제외합니다.
- 검색식과 제외 키워드는 [`config.yml`](config.yml)에서 관리합니다.

## 1. Telegram 채널 준비

1. Telegram의 `@BotFather`에게 `/newbot`을 보내 봇을 만듭니다.
2. Telegram에서 새 채널을 만들고 봇을 채널 관리자로 추가합니다.
3. 봇에는 최소한 `메시지 게시` 권한을 허용합니다.
4. 공개 채널은 `@채널사용자명`을 `TELEGRAM_CHAT_ID`로 사용할 수 있습니다.
5. 비공개 채널은 채널 ID를 확인해야 합니다.

개인 테스트용 `chat_id`는 아래 도구로 확인할 수 있습니다. 토큰은 입력 중 화면에 보이지 않고 파일에도 저장되지 않습니다.

```bash
python scripts/telegram_setup.py
```

## 2. 로컬 시험

Python 3.11 이상을 권장합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m src.main --dry-run
```

실제 Telegram 시험 발송은 토큰을 환경변수로만 전달합니다.

```bash
export TELEGRAM_BOT_TOKEN='발급받은_토큰'
export TELEGRAM_CHAT_ID='@공개채널사용자명_또는_채널ID'
python -m src.main
unset TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
```

## 3. GitHub 설정

비공개 GitHub 저장소를 만든 뒤 이 폴더의 내용을 올립니다. `Settings → Secrets and variables → Actions`에서 다음 Repository secrets를 추가합니다.

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

그 다음 `Actions → KCG AI Morning Brief → Run workflow`로 수동 시험합니다. 성공하면 평일 오전 08:00 예약 실행이 유지됩니다.

## 4. 기사 수와 키워드 조정

[`config.yml`](config.yml)에서 다음을 변경할 수 있습니다.

- `lookback_hours`: 수집 기간
- `max_items`: 전체 최대 기사 수
- `category_limits`: 분류별 최대 기사 수
- `feeds`: 분류별 Google 뉴스 RSS 검색식
- `required_any`: 반드시 포함해야 하는 AI 신호
- `exclude_any`: 광고성·투자성·무관 기사 제외어

## 한 줄 요약과 활용팁

현재 버전은 정확성과 무과금 원칙을 위해 기사 내용을 임의로 요약하지 않습니다. 기사별 한 줄 요약이나 해양경찰 활용팁을 자동 생성하려면 기사 원문 확보와 LLM 검증 단계를 별도로 추가해야 합니다.

## 문제 해결

- `401 Unauthorized`: 봇 토큰 오류
- `400 chat not found`: 채널 ID 오류 또는 봇이 채널 관리자가 아님
- 뉴스가 0건: RSS 검색식, `required_any`, `lookback_hours` 확인
- 중복 발송: `data/seen.json`이 workflow 실행 후 커밋됐는지 확인
