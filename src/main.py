from __future__ import annotations

import argparse
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

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
LOG = logging.getLogger("dapa-brief")


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


def fingerprint(title: str, link: str) -> str:
    material = f"{clean_title(title).casefold()}|{clean_link(link)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def title_key(title: str) -> str:
    normalized = re.sub(r"[^0-9a-z가-힣]", "", clean_title(title).casefold())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def entry_datetime(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def choose_category(title: str, categories: dict[str, list[str]]) -> str:
    folded = title.casefold()
    best_name = "기타"
    best_score = 0
    for name, keywords in categories.items():
        score = sum(1 for keyword in keywords if keyword.casefold() in folded)
        if score > best_score:
            best_name, best_score = name, score
    return best_name


def collect(config: dict[str, Any], now: datetime) -> list[Article]:
    cutoff = now - timedelta(hours=int(config["lookback_hours"]))
    include = [word.casefold() for word in config["include_any"]]
    exclude = [word.casefold() for word in config.get("exclude_any", [])]
    collected: list[Article] = []

    for feed in config["feeds"]:
        parsed = feedparser.parse(feed["url"], agent="DAPA-Morning-Brief/1.0")
        if getattr(parsed, "bozo", False):
            LOG.warning("COLLECT feed=%s parse_warning=%s", feed["name"], parsed.bozo_exception)
        LOG.info("COLLECT feed=%s entries=%d", feed["name"], len(parsed.entries))
        for entry in parsed.entries:
            title = clean_title(entry.get("title", ""))
            link = clean_link(entry.get("link", ""))
            published = entry_datetime(entry)
            folded = title.casefold()
            if not title or not link or not published or published < cutoff:
                continue
            if not any(word in folded for word in include):
                continue
            if any(word in folded for word in exclude):
                continue
            source = entry.get("source", {}).get("title") or feed["name"]
            collected.append(
                Article(
                    title=title,
                    link=link,
                    source=source,
                    published=published,
                    category=choose_category(title, config["categories"]),
                    fingerprint=fingerprint(title, link),
                )
            )

    unique: list[Article] = []
    known_titles: set[str] = set()
    known_links: set[str] = set()
    for article in sorted(collected, key=lambda item: item.published, reverse=True):
        article_title_key = title_key(article.title)
        if article_title_key in known_titles or article.link in known_links:
            LOG.info("DEDUP title=%s", article.title)
            continue
        known_titles.add(article_title_key)
        known_links.add(article.link)
        unique.append(article)
    return unique


def format_messages(articles: list[Article], now: datetime) -> list[str]:
    header = f"<b>DAPA 아침 뉴스</b> · {now.astimezone(SEOUL).strftime('%Y-%m-%d %H:%M')}"
    if not articles:
        return [header + "\n\n지난 수집 이후 새 관련 기사가 없습니다."]

    blocks: list[str] = [header]
    categories: dict[str, list[Article]] = {}
    for article in articles:
        categories.setdefault(article.category, []).append(article)
    for category, category_articles in categories.items():
        blocks.append(f"\n<b>#{html.escape(category)}</b>")
        for article in category_articles:
            blocks.append(
                f"• <a href=\"{html.escape(article.link, quote=True)}\">{html.escape(article.title)}</a>\n"
                f"  {html.escape(article.source)} · {article.published.astimezone(SEOUL).strftime('%m-%d %H:%M')}"
            )

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
    fresh = [article for article in articles if article.fingerprint not in seen]
    fresh = fresh[: int(config["max_items"])]
    LOG.info("FILTER collected=%d fresh=%d", len(articles), len(fresh))

    if not fresh and not config.get("send_empty", True):
        save_seen(seen)
        return 0

    messages = format_messages(fresh, now)
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
