"""동향지 엔진(gov-ai-trendletter)을 끌어다 쓰는 다리.

구글 뉴스 RSS 만 긁던 것을 기관 1차 출처까지 넓히고, 낱말 세기 대신
업무 관련도 가중치로 순위를 매긴다. 엔진은 주간 동향지와 같은 것을 쓰므로
가중치를 한 벌만 관리한다.

엔진을 못 불러오면 None 을 돌려주고, 부르는 쪽이 기존 RSS 방식으로 돌아간다.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

LOG = logging.getLogger("kcg-ai-brief.engine")

# 워크플로가 engine/ 아래에 gov-ai-trendletter 를 체크아웃한다
ENGINE_ROOT = Path(os.environ.get("TRENDLETTER_ROOT", "engine")).resolve()


def available() -> bool:
    return (ENGINE_ROOT / "config" / "sources.yaml").exists()


def _prepare() -> bool:
    if not available():
        return False
    os.environ["TRENDLETTER_ROOT"] = str(ENGINE_ROOT)
    src = str(ENGINE_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    return True


# 일간 브리핑은 하루에 몇 건만 나가므로, 애매한 것은 아예 빼는 편이 낫다.
# 아래는 AI 기사이긴 하나 우리 업무와 닿지 않는 것들이다.
_DROP_TITLE = (
    "대학", "캠퍼스", "교수", "학과", "총장", "학생",          # 대학 소식
    "채용", "모집", "공모전 개최", "챔피언십", "경품", "이벤트",  # 모집·행사
    "수강", "수료", "특강 신청",
    "주가", "목표주가", "코스닥", "상장", "투자 유치", "시리즈 A",  # 증시·투자
    "출시 기념", "할인", "무료 체험", "프로모션",                # 홍보
)
# 벤더가 자사 제품을 알리는 기사. 기관이 주체가 아니면 뺀다.
_VENDOR_HINT = (
    "구축 사업자로 선정", "공급 계약", "수주", "도입 사례로 소개",
    "알린다", "선보인다", "출사표", "맞손", "업무협약", "MOU",
    "공동 개발 추진", "사업자로 선정", "파트너십",
)


def _worth_sending(row: dict[str, Any]) -> bool:
    """하루치에 실을 값어치가 있는지 본다.

    업무 관련도가 하나라도 걸렸으면 싣는다. 하나도 안 걸렸다면 점수가
    확실히 높을 때만 싣는다. 애매한 것을 넣느니 건수가 적은 편이 낫다.
    """
    title = row.get("title") or ""
    if any(k in title for k in _DROP_TITLE):
        return False
    # 벤더가 자사 제품을 알리는 기사. 업무 관련 낱말이 본문에 있다고 해서
    # 봐줄 이유가 없다. 기관이 주체로 제목에 나올 때만 남긴다.
    if any(k in title for k in _VENDOR_HINT) and not _has_agency(title):
        return False
    if row.get("groups"):
        return True
    return float(row.get("score", 0)) >= float(row.get("solo_bar", 10.0))


# 벤더 기사와 기관 발표를 가르는 기준. 구체적인 기관 이름만 센다.
# '공공기관'·'정부' 같은 일반어는 벤더 홍보 제목에도 흔히 들어간다 —
# 실측: 「비즈플레이, 공공기관 업무 혁신」이 기관 발표로 인정됐다.
_AGENCY_NAMES = (
    "해양경찰청", "해양경찰", "해경", "해양수산부", "해수부",
    "경찰청", "소방청", "국가수사본부",
    "과기정통부", "과학기술정보통신부", "행정안전부", "행안부",
    "국무조정실", "국가AI전략위", "개인정보보호위", "감사원",
    "국방부", "관세청", "산림청", "기상청", "국토교통부", "교육부",
)


def _has_agency(title: str) -> bool:
    return any(w in title for w in _AGENCY_NAMES)


def _is_near(row: dict[str, Any]) -> bool:
    """우리청·유사기관 소식인가.

    본문에만 낱말이 있는 경우는 세지 않는다. 문턱을 낮춰 주는 대접이라
    확실할 때만 인정한다 — 제목에 기관 이름이 있어야 한다.
    """
    if not (_NEAR_GROUPS & set(row.get("groups") or [])):
        return False
    return category_of(row) in ("우리청·해양", "유사·인접기관")


# 우리와 가까운 기관의 소식. 이건 점수가 낮아도 매일 챙겨야 한다.
_NEAR_GROUPS = {"직접", "현장임무", "유사기관", "인접기관"}


def collect_ranked(hours: int, min_score: float,
                   exclude_tracks: tuple = ("dev",),
                   solo_bar: float = 10.0,
                   near_min_score: float = 5.0) -> list[dict[str, Any]] | None:
    """엔진으로 수집·통합·채점한 결과를 돌려준다.

    돌려주는 항목: title, link, source, published, score, track, groups
    """
    if not _prepare():
        LOG.warning("엔진을 찾지 못해 기존 RSS 수집으로 진행합니다: %s", ENGINE_ROOT)
        return None
    try:
        from trendletter import pipeline                     # noqa: WPS433
        from trendletter.config import load                  # noqa: WPS433
        from trendletter.scoring import diversify            # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        LOG.warning("엔진을 불러오지 못했습니다(%s). 기존 방식으로 진행합니다.", exc)
        return None

    cfg = load()
    since = datetime.now() - timedelta(hours=hours)
    articles = pipeline.collect(cfg, since=since, progress=LOG.info)
    clusters = pipeline.build_clusters(articles, cfg)
    # 목록에 제목만 주는 수집원이 제목만으로 밀리지 않게 본문을 채운다
    pipeline.enrich_bodies(clusters, progress=LOG.info)
    clusters = pipeline.build_clusters(articles, cfg)

    # 개발자 트랙(GitHub·Reddit)은 일간 브리핑에 싣지 않는다.
    # 이건 현장 직원이 읽는 물건이고, 개발자 신호는 주간 동향지에서 종합해 다룬다.
    # 우리청·유사기관 소식은 문턱을 낮춘다. 같은 잣대로 재면 큰 산업 소식에
    # 밀려 정작 우리 일이 빠진다. 지난 11개 호에서 가장 중요하게 다룬 축이다.
    def bar(c) -> float:
        near = _is_near({"title": c.lead.title, "groups": c.work_groups})
        return near_min_score if near else min_score

    ranked = [c for c in clusters
              if c.score >= bar(c) and c.lead.track not in exclude_tracks]

    # 수집기에 따라 오래된 항목이 딸려 온다(GitHub 은 저장소 갱신일 기준).
    # 하루치 브리핑에 20일 전 글이 섞이면 안 된다.
    ranked = [c for c in ranked
              if c.lead.published is None or c.lead.published >= since]
    # 같은 사건을 여러 매체가 제각각 제목으로 써도 한 번만 싣는다
    ranked = diversify(ranked, take=60)

    out = []
    for c in ranked:
        a = c.lead
        out.append(
            {
                "title": a.title,
                "link": a.url,
                "source": (a.raw.get("dept") or "").strip() or a.source_name,
                "published": a.published,
                "score": round(c.score, 1),
                "track": a.lead_track if hasattr(a, "lead_track") else a.track,
                "groups": list(c.work_groups),
                "outlets": len(c.outlets),
            }
        )
    for row in out:
        row["solo_bar"] = solo_bar
        row["near"] = _is_near(row)
    # 가까운 기관 소식을 앞에 둔다. 분야별 상한에 걸릴 때 이쪽이 먼저 들어간다.
    out.sort(key=lambda r: (not r["near"], -float(r.get("score", 0))))
    kept = [row for row in out if _worth_sending(row)]
    LOG.info("엔진 수집 %d건 → 클러스터 %d개 → %.1f점 이상 %d건 → 선별 %d건",
             len(articles), len(clusters), min_score, len(out), len(kept))
    return kept


# 분야는 동향지가 보는 관점을 그대로 쓴다.
# 동향지는 "무슨 기술이냐" 가 아니라 "우리와 얼마나 가까우냐" 로 본다.
# 우리청 → 유사·인접기관 → 범정부 정책 → 타 기관 사례 → 산업·기술 순이다.
# 이 순서가 곧 매일 챙겨야 하는 순서이기도 하다.
ORDER = [
    "우리청·해양",
    "유사·인접기관",
    "범정부 AI 정책",
    "타 기관 도입사례",
    "산업·기술 동향",
]
ICONS = {
    "우리청·해양": "\u2693",          # 닻
    "유사·인접기관": "\U0001F6A8",    # 경광등
    "범정부 AI 정책": "\U0001F3DB\uFE0F",
    "타 기관 도입사례": "\U0001F3E2",
    "산업·기술 동향": "\U0001F525",
}

# 업무 관련도 그룹 → 분야. 위에 있는 것이 이긴다.
# 그룹은 본문까지 훑어 잡히므로 기관 분야로 보내지 않는다. 기관 분야는
# 제목에 이름이 있을 때만 간다. 실측: 「AI데이터센터 재생에너지」가 본문의
# '연안' 때문에 현장임무로 걸려 우리청 소식으로 분류됐다.
_BY_GROUP = [
    ("공공전환", "범정부 AI 정책"),
    ("인재교육", "범정부 AI 정책"),
    ("타기관사례", "타 기관 도입사례"),
    ("현장기술", "산업·기술 동향"),
    ("인프라", "산업·기술 동향"),
]

# 그룹이 하나도 안 걸렸을 때 제목으로 본다. 기관 이름이 가장 확실한 단서다.
_BY_TITLE = [
    (("해양경찰", "해경", "해양수산부", "해수부", "해상", "선박", "항만", "연안"),
     "우리청·해양"),
    (("경찰청", "소방청", "119", "국가수사본부", "치안", "소방"),
     "유사·인접기관"),
    # 기관 이름만 둔다. '정부'·'공공기관'·'공무원' 같은 일반어는 회사 홍보
    # 제목에도 흔히 들어가 정책 소식으로 둔갑한다.
    (("과기정통부", "과학기술정보통신부", "행정안전부", "행안부", "국무조정실",
      "국가AI전략위", "국가인공지능전략위", "개인정보보호위", "감사원",
      "대통령실", "청와대", "국회"),
     "범정부 AI 정책"),
    (("국방부", "방위사업청", "관세청", "산림청", "기상청", "국토교통부",
      "교육부", "고용노동부", "보건복지부", "특허청", "조달청", "지자체"),
     "타 기관 도입사례"),
]


def category_of(row: dict[str, Any], keyword_map: dict[str, list[str]] | None = None) -> str:
    """분야를 정한다. 제목의 기관 이름을 먼저 보고, 없으면 업무 관련도를 본다.

    업무 관련도 그룹은 본문까지 훑어 잡히므로 분류에 먼저 쓰면 엉뚱해진다.
    실측: 「AI데이터센터 재생에너지」가 본문의 '연안' 때문에 현장임무로 걸렸다.
    """
    title = row.get("title") or ""
    for words, category in _BY_TITLE:
        if any(w in title for w in words):
            return category
    groups = set(row.get("groups") or [])
    for name, category in _BY_GROUP:
        if name in groups:
            # 정책 분야는 기관이 제목에 주체로 나올 때만 인정한다.
            # 본문에 '공공기관' 이 있다고 정책 소식은 아니다 — 실측:
            # 「비즈플레이, 공공기관 업무 혁신」은 회사 홍보 기사였다.
            if category == "범정부 AI 정책" and not _has_agency(title):
                return "산업·기술 동향"
            return category
    return "산업·기술 동향"
