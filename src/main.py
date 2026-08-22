from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import html
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser
import requests
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yml"
SEEN_PATH = ROOT / "data" / "seen.json"
TRACKING_PARAMS = {"fbclid", "gclid", "ocid", "ref", "source"}
SEOUL = ZoneInfo("Asia/Seoul")
CATEGORY_ICONS = {
    "해양치안 AI": "⚓",
    "AI 정책·제도": "🏛️",
    "유관기관·공공안전 AI": "🚨",
    "AI 산업·핫이슈": "🔥",
    "AI 도구·업데이트": "🛠️",
    "AI 보안·윤리": "🛡️",
    "AI 학습·교육": "🎓",
}

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
LOG = logging.getLogger("kcg-ai-brief")


@dataclass(frozen=True)
class Article:
    title: str
    link: str
    source: str
    published: datetime
    category: str
    fingerprint: str


def load_yaml(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_seen(path: Path = SEEN_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("items", {})


def save_seen(items: dict[str, str], path: Path = SEEN_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": dict(sorted(items.items(), key=lambda pair: pair[1], reverse=True))}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_link(link: str) -> str:
    parts = urlsplit(link)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(query), ""))


def clean_title(title: str) -> str:
    title = html.unescape(title)
    title = re.sub(r"\s+-\s+[^-]{1,40}$", "", title)
    return re.sub(r"\s+", " ", title).strip()


def contains_keyword(text: str, keyword: str) -> bool:
    folded_text = text.casefold()
    folded_keyword = str(keyword).casefold()
    if folded_keyword.isascii() and re.fullmatch(r"[a-z0-9]+", folded_keyword):
        return re.search(
            rf"(?<![a-z0-9]){re.escape(folded_keyword)}(?![a-z0-9])", folded_text
        ) is not None
    return folded_keyword in folded_text


def fingerprint(title: str, link: str) -> str:
    material = f"{clean_title(title).casefold()}|{clean_link(link)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def title_key(title: str) -> str:
    normalized = re.sub(r"[^0-9a-z가-힣]", "", clean_title(title).casefold())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def similar_title(left: str, right: str, threshold: float = 0.55) -> bool:
    def normalize(value: str) -> str:
        return re.sub(r"[^0-9a-z가-힣]", "", clean_title(value).casefold())

    def tokens(value: str) -> set[str]:
        stopwords = {
            "ai", "인공지능", "생성형", "기반", "공개", "개최", "기술", "시장",
            "정부", "관련", "추진", "위한", "대한", "발표",
        }
        output: set[str] = set()
        for token in re.findall(r"[0-9a-z가-힣]+", clean_title(value).casefold()):
            token = re.sub(
                r"(으로|에서|하고|한다|했다|됐다|해보세요|이다|이며|로|을|를|은|는|이|가)$",
                "",
                token,
            )
            if len(token) >= 2 and token not in stopwords:
                output.add(token)
        return output

    normalized_left = normalize(left)
    normalized_right = normalize(right)
    if not normalized_left or not normalized_right:
        return False
    if SequenceMatcher(None, normalized_left, normalized_right).ratio() >= threshold:
        return True
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    shared = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return len(shared) >= 3 and bool(union) and len(shared) / len(union) >= 0.25


def entry_datetime(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def choose_category(title: str, categories: dict[str, list[str]]) -> str:
    best_name = "기타"
    best_score = 0
    for name, keywords in categories.items():
        score = sum(1 for keyword in keywords if contains_keyword(title, keyword))
        if score > best_score:
            best_name, best_score = name, score
    return best_name


def collect(config: dict[str, Any], now: datetime) -> list[Article]:
    cutoff = now - timedelta(hours=int(config["lookback_hours"]))
    required = config.get("required_any", config.get("include_any", []))
    exclude = config.get("exclude_any", [])
    collected: list[Article] = []

    for feed in config["feeds"]:
        parsed = feedparser.parse(feed["url"], agent="KCG-AI-Morning-Brief/1.0")
        if getattr(parsed, "bozo", False):
            LOG.warning("COLLECT feed=%s parse_warning=%s", feed["name"], parsed.bozo_exception)
        LOG.info("COLLECT feed=%s entries=%d", feed["name"], len(parsed.entries))
        for entry in parsed.entries:
            title = clean_title(entry.get("title", ""))
            link = clean_link(entry.get("link", ""))
            published = entry_datetime(entry)
            if not title or not link or not published or published < cutoff:
                continue
            if not any(contains_keyword(title, word) for word in required):
                continue
            feed_required = feed.get("required_any", [])
            if feed_required and not any(
                contains_keyword(title, word) for word in feed_required
            ):
                continue
            if any(contains_keyword(title, word) for word in exclude):
                continue
            source = entry.get("source", {}).get("title") or feed["name"]
            excluded_sources = {
                str(item).casefold()
                for item in config.get("exclude_sources", []) + feed.get("exclude_sources", [])
            }
            if source.casefold() in excluded_sources:
                continue
            category = feed.get("category") or choose_category(title, config["categories"])
            collected.append(
                Article(
                    title=title,
                    link=link,
                    source=source,
                    published=published,
                    category=category,
                    fingerprint=fingerprint(title, link),
                )
            )

    unique: list[Article] = []
    known_titles: set[str] = set()
    known_links: set[str] = set()
    for article in sorted(collected, key=lambda item: item.published, reverse=True):
        article_title_key = title_key(article.title)
        if (
            article_title_key in known_titles
            or article.link in known_links
            or any(similar_title(article.title, previous.title) for previous in unique)
        ):
            LOG.info("DEDUP title=%s", article.title)
            continue
        known_titles.add(article_title_key)
        known_links.add(article.link)
        unique.append(article)
    return unique


def relative_age(published: datetime, now: datetime) -> str:
    seconds = max(0, int((now - published).total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)}분 전"
    if seconds < 86400:
        return f"{seconds // 3600}시간 전"
    return f"{seconds // 86400}일 전"


def load_learning(config: dict[str, Any], now: datetime) -> dict[str, str] | None:
    learning = config.get("learning", {})
    local_now = now.astimezone(SEOUL)
    if not learning.get("enabled") or local_now.weekday() != int(learning.get("weekday", 0)):
        return None
    path = ROOT / learning.get("path", "learning.yml")
    items = load_yaml(path).get("items", [])
    if not items:
        return None
    return items[local_now.isocalendar().week % len(items)]


def trend_tags(articles: list[Article], config: dict[str, Any], limit: int = 5) -> list[str]:
    counts: dict[str, int] = {}
    keywords = [
        keyword
        for category_keywords in config.get("categories", {}).values()
        for keyword in category_keywords
    ]
    for keyword in keywords:
        count = sum(1 for article in articles if contains_keyword(article.title, keyword))
        if count:
            counts[keyword] = count
    ranked = sorted(counts, key=lambda keyword: (-counts[keyword], len(keyword), keyword))
    return ["#" + re.sub(r"\s+", "", keyword) for keyword in ranked[:limit]]


def select_fresh(
    articles: list[Article], seen: dict[str, str], config: dict[str, Any]
) -> list[Article]:
    global_limit = int(config.get("max_items", 12))
    category_limits = config.get("category_limits", {})
    order = list(config.get("category_order", []))
    groups: dict[str, list[Article]] = {category: [] for category in order}
    for article in articles:
        if article.fingerprint not in seen:
            groups.setdefault(article.category, []).append(article)
    for category in groups:
        if category not in order:
            order.append(category)

    selected: list[Article] = []
    max_category_limit = max(
        [int(value) for value in category_limits.values()] or [int(config.get("per_category_max", 3))]
    )
    for position in range(max_category_limit):
        for category in order:
            category_limit = int(
                category_limits.get(category, config.get("per_category_max", 3))
            )
            if position < category_limit and position < len(groups[category]):
                selected.append(groups[category][position])
                if len(selected) >= global_limit:
                    return selected
    return selected


def format_messages(
    articles: list[Article], now: datetime, config: dict[str, Any] | None = None
) -> list[str]:
    config = config or {"brief_title": "오늘의 해양경찰 AI 동향", "categories": {}}
    local_now = now.astimezone(SEOUL)
    weekdays = "월화수목금토일"
    header = (
        f"🌊 <b>{html.escape(config.get('brief_title', '오늘의 해양경찰 AI 동향'))}</b>\n"
        f"{local_now.strftime('%Y.%m.%d')} ({weekdays[local_now.weekday()]})"
    )
    if not articles:
        blocks = [header, "\n지난 24시간 동안 새 관련 기사가 없습니다."]
    else:
        blocks = [header]

    categories: dict[str, list[Article]] = {}
    for article in articles:
        categories.setdefault(article.category, []).append(article)
    for category, category_articles in categories.items():
        icon = CATEGORY_ICONS.get(category, "📌")
        section_lines = [
            f"\n━━━━━━━━━━━━━━━\n\n{icon} <b>{html.escape(category)}</b> ({len(category_articles)}건)"
        ]
        for index, article in enumerate(category_articles, start=1):
            section_lines.append(
                f"{index}. <a href=\"{html.escape(article.link, quote=True)}\">{html.escape(article.title)}</a> "
                f"<i>({relative_age(article.published, now)})</i>\n"
                f"   {html.escape(article.source)}"
            )
        blocks.append("\n".join(section_lines))

    learning_item = load_learning(config, now)
    if learning_item:
        blocks.append(
            "\n━━━━━━━━━━━━━━━\n\n🧠 <b>이번 주 AI 용어</b>\n"
            f"<b>{html.escape(learning_item['term'])}</b> — {html.escape(learning_item['definition'])}\n"
            f"💡 <b>해양경찰 관점:</b> {html.escape(learning_item['relevance'])}"
        )

    tags = trend_tags(articles, config)
    if tags:
        blocks.append("\n━━━━━━━━━━━━━━━\n\n📊 <b>오늘의 키워드</b>\n" + " ".join(tags))

    messages: list[str] = []
    current = ""
    for block in blocks:
        candidate = block if not current else current + "\n" + block
        if len(candidate) > 3800:
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def send_telegram(token: str, chat_id: str, messages: list[str]) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for index, message in enumerate(messages, start=1):
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram rejected message {index}: {payload}")
        LOG.info("SEND message=%d/%d ok=true", index, len(messages))


def prune_seen(seen: dict[str, str], now: datetime, days: int = 45) -> dict[str, str]:
    cutoff = now - timedelta(days=days)
    output: dict[str, str] = {}
    for key, value in seen.items():
        try:
            if datetime.fromisoformat(value) >= cutoff:
                output[key] = value
        except ValueError:
            continue
    return output


def run(dry_run: bool = False) -> int:
    config = load_yaml()
    now = datetime.now(timezone.utc)
    seen = prune_seen(load_seen(), now)
    articles = collect(config, now)
    fresh = select_fresh(articles, seen, config)
    LOG.info("FILTER collected=%d fresh=%d", len(articles), len(fresh))

    if not fresh and not config.get("send_empty", True):
        save_seen(seen)
        return 0

    messages = format_messages(fresh, now, config)
    if dry_run:
        print("\n\n--- MESSAGE ---\n\n".join(messages))
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        LOG.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
        return 2

    send_telegram(token, chat_id, messages)
    stamp = now.isoformat()
    for article in fresh:
        seen[article.fingerprint] = stamp
    save_seen(seen)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print without sending or updating state")
    args = parser.parse_args()
    raise SystemExit(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
