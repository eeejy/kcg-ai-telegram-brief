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

    def test_category_follows_work_relevance(self) -> None:
        """분야는 동향지와 같은 관점(우리와 얼마나 가까운가)으로 나뉜다."""
        from src.engine import category_of

        cases = [
            ({"title": "해양경찰청, AI 함정 청사진"}, "우리청·해양"),
            ({"title": "경찰청, AI 수사자료 분석 솔루션 보급"}, "유사·인접기관"),
            ({"title": "과기정통부, AI 윤리원칙 제정"}, "범정부 AI 정책"),
            ({"title": "산림청, 산불 감시 AI 도입"}, "타 기관 도입사례"),
            ({"title": "구글, 새 AI 모델 공개"}, "산업·기술 동향"),
            # 회사가 주어인 기사는 '공공기관' 이 붙어도 정책이 아니다
            ({"title": "비즈플레이, 공공기관 업무 혁신",
              "groups": ["공공전환"]}, "산업·기술 동향"),
        ]
        for row, expected in cases:
            self.assertEqual(category_of(row), expected, row["title"])

    def test_near_agency_uses_lower_bar(self) -> None:
        """우리청·유사기관 소식은 점수가 낮아도 실린다."""
        from src.engine import _NEAR_GROUPS, _is_near

        # 제목에 기관 이름이 있고 업무 관련도도 걸려야 인정한다
        self.assertTrue(_is_near(
            {"title": "경찰청, AI 수사 솔루션 보급", "groups": ["유사기관"]}))
        self.assertTrue(_is_near(
            {"title": "해양경찰청 AI 함정", "groups": ["직접", "인프라"]}))
        # 본문에만 걸린 경우는 인정하지 않는다 (제목에 기관이 없다)
        self.assertFalse(_is_near(
            {"title": "AI데이터센터 재생에너지 논란", "groups": ["현장임무"]}))
        self.assertFalse(_is_near({"title": "구글 새 모델", "groups": []}))
        self.assertIn("인접기관", _NEAR_GROUPS)

    def test_vendor_promo_dropped(self) -> None:
        """벤더 자사 홍보는 뺀다. 기관이 제목에 주체로 나올 때만 남긴다."""
        from src.engine import _worth_sending

        self.assertFalse(_worth_sending(
            {"title": "비즈플레이, 공공기관 업무 혁신 알린다", "groups": ["공공전환"]}))
        self.assertFalse(_worth_sending(
            {"title": "NC AI, 사우디서 K-AI 기술력 알린다", "groups": ["인프라"]}))
        self.assertTrue(_worth_sending(
            {"title": "과기정통부, 민간과 업무협약 체결", "groups": ["공공전환"]}))

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
