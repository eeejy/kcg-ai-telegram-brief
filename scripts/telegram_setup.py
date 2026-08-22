from __future__ import annotations

import getpass
import sys

import requests


def main() -> int:
    print("Telegram 봇 설정 확인")
    print("토큰은 입력 중 표시되지 않으며 파일에 저장되지 않습니다.\n")
    token = getpass.getpass("BotFather가 발급한 봇 토큰: ").strip()
    if not token:
        print("토큰이 입력되지 않았습니다.", file=sys.stderr)
        return 2

    base_url = f"https://api.telegram.org/bot{token}"
    try:
        identity = requests.get(f"{base_url}/getMe", timeout=20)
        identity.raise_for_status()
        identity_payload = identity.json()
        if not identity_payload.get("ok"):
            raise RuntimeError(identity_payload)
        username = identity_payload["result"].get("username", "알 수 없음")
        print(f"\n봇 인증 성공: @{username}")

        updates = requests.get(f"{base_url}/getUpdates", timeout=20)
        updates.raise_for_status()
        updates_payload = updates.json()
        if not updates_payload.get("ok"):
            raise RuntimeError(updates_payload)
    except (requests.RequestException, RuntimeError) as error:
        print(f"Telegram 연결 실패: {error}", file=sys.stderr)
        return 1

    chats: dict[str, str] = {}
    for update in updates_payload.get("result", []):
        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
        )
        if not message or "chat" not in message:
            continue
        chat = message["chat"]
        chat_id = str(chat["id"])
        label = (
            chat.get("title")
            or " ".join(part for part in [chat.get("first_name"), chat.get("last_name")] if part)
            or chat.get("username")
            or "이름 없음"
        )
        chats[chat_id] = label

    if not chats:
        print("\n아직 채팅을 찾지 못했습니다.")
        print(f"Telegram에서 @{username}에게 /start를 보낸 뒤 다시 실행하세요.")
        return 3

    print("\n발견된 채팅:")
    for chat_id, label in chats.items():
        print(f"- {label}: {chat_id}")
    print("\n개인 대화 항목의 숫자를 GitHub Secret TELEGRAM_CHAT_ID에 저장하세요.")
    print("봇 토큰은 GitHub Secret TELEGRAM_BOT_TOKEN에 저장하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

