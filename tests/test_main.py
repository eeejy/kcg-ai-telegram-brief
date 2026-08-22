import unittest
from datetime import datetime, timezone

from src.main import Article, clean_link, choose_category, fingerprint, format_messages


class BriefTests(unittest.TestCase):
    def test_clean_link_removes_tracking(self) -> None:
        self.assertEqual(
            clean_link("https://Example.com/a?utm_source=x&id=3#top"),
            "https://example.com/a?id=3",
        )

    def test_fingerprint_is_stable_for_source_suffix(self) -> None:
        left = fingerprint("방산 수출 계약 - 언론사", "https://example.com/a?utm_source=x")
        right = fingerprint("방산 수출 계약", "https://example.com/a")
        self.assertEqual(left, right)

    def test_choose_category_uses_most_matches(self) -> None:
        categories = {"수출": ["수출", "계약"], "기술": ["기술"]}
        self.assertEqual(choose_category("방산 수출 계약 체결", categories), "수출")

    def test_format_messages_contains_only_metadata(self) -> None:
        article = Article(
            title="방위사업청 시험 기사",
            link="https://example.com/news",
            source="시험 언론사",
            published=datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc),
            category="방위사업청",
            fingerprint="abc",
        )
        message = format_messages(
            [article], datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)
        )[0]
        self.assertIn("방위사업청 시험 기사", message)
        self.assertIn("시험 언론사", message)
        self.assertIn("https://example.com/news", message)


if __name__ == "__main__":
    unittest.main()
