import unittest
from datetime import datetime, timezone

from src.main import (
    Article,
    clean_link,
    choose_category,
    contains_keyword,
    fingerprint,
    format_messages,
    select_fresh,
    similar_title,
)


class BriefTests(unittest.TestCase):
    def test_clean_link_removes_tracking(self) -> None:
        self.assertEqual(
            clean_link("https://Example.com/a?utm_source=x&id=3#top"),
            "https://example.com/a?id=3",
        )

    def test_fingerprint_is_stable_for_source_suffix(self) -> None:
        left = fingerprint("AI 정책 발표 - 언론사", "https://example.com/a?utm_source=x")
        right = fingerprint("AI 정책 발표", "https://example.com/a")
        self.assertEqual(left, right)

    def test_choose_category_uses_most_matches(self) -> None:
        categories = {"정책": ["AI", "정책"], "기술": ["기술"]}
        self.assertEqual(choose_category("공공 AI 정책 발표", categories), "정책")

    def test_ai_keyword_does_not_match_kai(self) -> None:
        self.assertFalse(contains_keyword("KAI 신형 항공기 공개", "AI"))
        self.assertTrue(contains_keyword("공공 AI 서비스 공개", "AI"))

    def test_similar_event_titles_are_duplicates(self) -> None:
        left = "소방청, AI로 전기차 화재 조기 감지 안전연소 기술 개발"
        right = "전기차 화재, AI로 조기 감지하고 안전하게 연소 통제한다"
        self.assertTrue(similar_title(left, right))
        self.assertFalse(similar_title(left, "공공기관 생성형 AI 가이드라인 공개"))

    def test_format_messages_contains_only_metadata(self) -> None:
        article = Article(
            title="해양경찰 AI 시험 기사",
            link="https://example.com/news",
            source="시험 언론사",
            published=datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc),
            category="해양치안 AI",
            fingerprint="abc",
        )
        message = format_messages(
            [article], datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)
        )[0]
        self.assertIn("오늘의 해양경찰 AI 동향", message)
        self.assertIn("해양경찰 AI 시험 기사", message)
        self.assertIn("시험 언론사", message)
        self.assertIn("https://example.com/news", message)

    def test_monday_message_contains_learning_term(self) -> None:
        monday = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
        config = {
            "brief_title": "오늘의 해양경찰 AI 동향",
            "categories": {},
            "learning": {"enabled": True, "weekday": 0, "path": "learning.yml"},
        }
        message = "\n".join(format_messages([], monday, config))
        self.assertIn("이번 주 AI 용어", message)
        self.assertIn("해양경찰 관점", message)

    def test_select_fresh_respects_global_and_category_limits(self) -> None:
        now = datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc)
        articles = [
            Article(f"해양 AI {index}", f"https://e/{index}", "언론사", now, "해양치안 AI", str(index))
            for index in range(4)
        ] + [
            Article(f"정책 AI {index}", f"https://p/{index}", "언론사", now, "AI 정책·제도", f"p{index}")
            for index in range(4)
        ]
        config = {
            "max_items": 4,
            "category_order": ["해양치안 AI", "AI 정책·제도"],
            "category_limits": {"해양치안 AI": 2, "AI 정책·제도": 2},
        }
        selected = select_fresh(articles, {}, config)
        self.assertEqual(len(selected), 4)
        self.assertEqual(sum(item.category == "해양치안 AI" for item in selected), 2)
        self.assertEqual(sum(item.category == "AI 정책·제도" for item in selected), 2)


if __name__ == "__main__":
    unittest.main()
