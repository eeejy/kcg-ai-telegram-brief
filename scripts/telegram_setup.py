from __future__ import annotations

import getpass
import json
import sys
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def telegram_get(url: str) -> dict:
    with urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def telegram_post(url: str, data: dict[str, str]) -> dict:
    request = Request(url, data=urlencode(data).encode("utf-8"), method="POST")
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    print("Telegram 봇 설정 확인")
    print("토큰은 입력 중 표시되지 않으며 파일에 저장되지 않습니다.\n")
    token = getpass.getpass("BotFather가 발급한 봇 토큰: ").strip()
    if not token:
        print("토큰이 입력되지 않았습니다.", file=sys.stderr)
        return 2

    base_url = f"https://api.telegram.org/bot{token}"
    try:
        identity_payload = telegram_get(f"{base_url}/getMe")
        if not identity_payload.get("ok"):
            raise RuntimeError(identity_payload)
        username = identity_payload["result"].get("username", "알 수 없음")
        print(f"\n봇 인증 성공: @{username}")

        updates_payload = telegram_get(f"{base_url}/getUpdates")
        if not updates_payload.get("ok"):
            raise RuntimeError(updates_payload)
    except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Telegram 연결 실패: {error}", file=sys.stderr)
        return 1

    chats: dict[str, tuple[str, str]] = {}
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
        chats[chat_id] = (label, chat.get("type", "알 수 없음"))

        # A post forwarded from a private channel to the bot contains the
        # original channel in forward_origin.chat. This is often the easiest
        # way to discover a private channel ID.
        origin = message.get("forward_origin", {})
        origin_chat = origin.get("chat") if origin.get("type") == "channel" else None
        if origin_chat:
            origin_id = str(origin_chat["id"])
            origin_label = origin_chat.get("title") or origin_chat.get("username") or "이름 없음"
            chats[origin_id] = (origin_label, origin_chat.get("type", "channel"))

    if not chats:
        print("\n아직 채팅을 찾지 못했습니다.")
        print("채널의 글을 봇과의 개인 대화방으로 전달한 뒤 다시 실행하세요.")
        return 3

    print("\n발견된 채팅:")
    for chat_id, (label, chat_type) in chats.items():
        kind = "채널" if chat_type == "channel" else "개인/그룹"
        print(f"- [{kind}] {label}: {chat_id}")

    channel_ids = [chat_id for chat_id, (_, chat_type) in chats.items() if chat_type == "channel"]
    if len(channel_ids) == 1:
        channel_id = channel_ids[0]
        answer = input(f"\n이 채널({channel_id})에 연결 확인 메시지를 보낼까요? [y/N]: ").strip().lower()
        if answer in {"y", "yes"}:
            try:
                payload = telegram_post(
                    f"{base_url}/sendMessage",
                    {
                        "chat_id": channel_id,
                        "text": "✅ 오늘의 해양경찰 AI 동향 봇 연결이 완료되었습니다.",
                    },
                )
                if not payload.get("ok"):
                    raise RuntimeError(payload)
                print("테스트 메시지 발송 성공! Telegram 채널을 확인하세요.")
            except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as error:
                print(f"테스트 메시지 발송 실패: {error}", file=sys.stderr)
                return 1

    print("\n채널 이름 옆의 -100으로 시작하는 숫자가 TELEGRAM_CHAT_ID입니다.")
    print("봇 토큰은 GitHub Secret TELEGRAM_BOT_TOKEN에 저장하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
