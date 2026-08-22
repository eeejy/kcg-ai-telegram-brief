# DAPA Telegram Morning Brief

방위사업청·방산 관련 공개 뉴스의 제목과 링크를 모아 매일 오전 06:30(Asia/Seoul)에 Telegram으로 전송하는 최소 기능 프로젝트입니다.

## 원칙

- 기사 본문과 사진을 복제하지 않습니다.
- 제목, 출처, 게시 시각, 원문 링크만 전송합니다.
- Telegram 토큰과 채팅 ID는 코드에 저장하지 않습니다.
- LLM 및 유료 뉴스 API를 사용하지 않습니다.

## 1. Telegram 준비

1. Telegram의 `@BotFather`에게 `/newbot`을 보내 봇을 만듭니다.
2. 생성한 봇과의 대화에서 `/start`를 보냅니다.
3. 봇 토큰과 `chat_id`를 확인하되 GitHub 저장소나 채팅에 공개하지 않습니다.

`chat_id`는 아래 도구로 안전하게 확인할 수 있습니다. 토큰은 입력 중 화면에 보이지 않고 파일에도 저장되지 않습니다.

```bash
python scripts/telegram_setup.py
```

## 2. 로컬 시험

Python 3.11 이상을 권장합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main --dry-run
```

실제 Telegram 시험 발송은 토큰을 환경변수로만 전달합니다.

```bash
export TELEGRAM_BOT_TOKEN='발급받은_토큰'
export TELEGRAM_CHAT_ID='확인한_chat_id'
python -m src.main
unset TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
```

## 3. GitHub 설정

비공개 GitHub 저장소를 만든 뒤 이 폴더의 내용을 올립니다. 저장소의 `Settings → Secrets and variables → Actions`에서 다음 Repository secrets를 추가합니다.

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

그 다음 `Actions → DAPA Morning Brief → Run workflow`로 수동 시험합니다. 성공하면 매일 06:30 예약 실행이 그대로 유지됩니다.

## 4. 관심 키워드 변경

[`config.yml`](config.yml)의 `include_any`, `categories`, `exclude_any`를 수정합니다. 뉴스 검색어 자체를 바꾸려면 `feeds`의 URL에서 `q=` 뒤 검색어를 바꿉니다.

## 문제 해결

- `401 Unauthorized`: 봇 토큰 오류
- `400 chat not found`: 봇에게 `/start`를 보내지 않았거나 `chat_id` 오류
- 뉴스가 0건: RSS URL, 검색어, `lookback_hours` 확인
- 중복 발송: `data/seen.json`이 workflow 실행 후 커밋됐는지 확인
