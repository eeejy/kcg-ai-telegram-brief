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
    if any(k in title for k in _VENDOR_HINT) and not row.get("groups"):
        return False
    if row.get("groups"):
        return True
    return float(row.get("score", 0)) >= float(row.get("solo_bar", 10.0))


def collect_ranked(hours: int, min_score: float,
                   exclude_tracks: tuple = ("dev",),
                   solo_bar: float = 10.0) -> list[dict[str, Any]] | None:
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
    ranked = [c for c in clusters
              if c.score >= min_score and c.lead.track not in exclude_tracks]

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
    kept = [row for row in out if _worth_sending(row)]
    LOG.info("엔진 수집 %d건 → 클러스터 %d개 → %.1f점 이상 %d건 → 선별 %d건",
             len(articles), len(clusters), min_score, len(out), len(kept))
    return kept


# 엔진의 업무 관련도 그룹·트랙을 브리프 카테고리로 옮긴다.
# 브리프는 읽는 사람 기준으로 묶고, 엔진은 업무 기준으로 묶는다.
_GROUP_TO_CATEGORY = [
    # 해양치안 칸은 제목에 해양 낱말이 있을 때만 쓴다. 그룹으로는 보내지 않는다.
    ("유사기관", "유관기관·공공안전 AI"),
    ("인접기관", "유관기관·공공안전 AI"),
    ("공공전환", "AI 정책·제도"),
    ("타기관사례", "유관기관·공공안전 AI"),
    ("인재교육", "AI 학습·교육"),
    ("인프라", "AI 산업·핫이슈"),
    ("현장기술", "AI 산업·핫이슈"),
]
_TRACK_TO_CATEGORY = {
    "policy": "AI 정책·제도",
    "industry": "AI 산업·핫이슈",
    "dev": "AI 도구·업데이트",
}


def category_of(row: dict[str, Any], keyword_map: dict[str, list[str]]) -> str:
    """카테고리를 정한다.

    제목에 드러난 낱말을 먼저 본다. 업무 관련도 그룹은 본문까지 훑어 잡히므로
    분류에 쓰면 엉뚱한 데로 간다 — 실측: 「AI데이터센터 재생에너지」가
    현장임무 그룹에 걸려 해양치안으로 분류됐다. 그룹은 낱말이 하나도 안 걸릴
    때만 참고하고, 그때도 해양치안처럼 좁은 칸에는 넣지 않는다.
    """
    text = (row.get("title") or "").lower()
    for category, keywords in (keyword_map or {}).items():
        if any(str(k).lower() in text for k in keywords):
            return category
    groups = set(row.get("groups") or [])
    for name, category in _GROUP_TO_CATEGORY:
        if name in groups:
            return category
    return _TRACK_TO_CATEGORY.get(row.get("track"), "AI 산업·핫이슈")
