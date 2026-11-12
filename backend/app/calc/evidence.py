"""건 근거 상세(설계 6.3·4.4): 화면이 근거 줄을 눌렀을 때 펼쳐 보일 계산식·입력값·원본 파일·정책 값을 만든다.

읽기 전용이고 AI를 부르지 않는다. 숫자는 꾸미지 않고 그대로 두며(형식은 화면이 정함), 정책은 호출 시점의 값을 읽는다.
"""
from app import policy
from app.calc.campaign import _campaign_influencer, influencer_ranking, return_rate
from app.calc.signals import (
    ATTRIBUTION_NOTE,
    STATS_SOURCES,
    Signal,
    breakeven_hidden_sales,
    cost_breakdown,
    future_value_signals,
    risk_signals,
)
from app.data import loader
from app.rules.models import make_detail

_MKT = "02_masil/marketing/"
_AD = _MKT + "mkt_ad_spend_ms.csv"
_ORD = _MKT + "mkt_orders_ms.csv"
_CAMP = "02_masil/master/m_campaign_ms.csv"
NO_PLAN_BASIS = "원본 기안 파일에 없는 기안이라 지표 근거 없음"
NO_CONTRACT_BASIS = "캠페인 실적이 원본에 없는 인플루언서라 지표 근거 없음"
COST_NOTE = "표본 금액이라 실제 계약액과 곱하지 않음"
_RET_SRC = (_ORD, _MKT + "mkt_returns_ms.csv", _CAMP)


def resolve_detail(detail: dict | None, fallback_formula: str = "") -> dict:
    """저장된 detail(정책은 키만)을 화면용으로 바꾼다: 정책 키 -> {key, value, source, description}. 없으면(옛 저장 행) 빈 틀."""
    d = detail or {}
    policies = []
    for key in d.get("policy_keys", []):
        value, source, description = policy.entry(key)
        policies.append({"key": key, "value": value, "source": source, "description": description})
    return {"formula": d.get("formula") or fallback_formula, "inputs": list(d.get("inputs", [])),
            "sources": list(d.get("sources", [])), "policies": policies}


def signal_line(s: Signal) -> dict:
    return {"key": s.key, "label": s.label, "value": s.value, "compare": s.compare, "level": s.level,
            "badge": s.badge, "judgment": s.judgment, "exclude_reason": s.exclude_reason,
            "detail": resolve_detail(s.detail, s.basis)}


def influencer_of_plan(plan_id: str) -> str | None:
    """원본 기안 -> 캠페인 -> 인플루언서. 원본 기안 파일에 없으면 None."""
    row = next((r for r in loader.plan_rows() if r["plan_id"] == plan_id), None)
    if row is None:
        return None
    return _campaign_influencer()[row["campaign_id"]]


def has_performance(influencer_id: str) -> bool:
    return influencer_id in {r.influencer_id for r in influencer_ranking()}


def key_indicators(influencer_id: str) -> list[dict]:
    """설계 4.4 핵심 지표: 실질 ROAS와 순위, 광고비 비중과 순위, 배분 역전, 단순변심 반품률(그 인플루언서 vs 그 외)."""
    ranking = influencer_ranking()
    me = next(r for r in ranking if r.influencer_id == influencer_id)
    n = len(ranking)
    spend_rank = 1 + sum(1 for r in ranking if r.spend_share > me.spend_share)
    inverted = spend_rank <= n / 2 < me.rank
    mine = return_rate(influencer_id, "단순변심")
    rest = return_rate(None, "단순변심", exclude=influencer_id)

    def line(key, label, value, detail, rank=None, compare_label=None, compare_value=None):
        return {"key": key, "label": label, "value": value, "rank": rank, "of": n if rank is not None else None,
                "compare_label": compare_label, "compare_value": compare_value, "badge": "계산",
                "detail": resolve_detail(detail)}

    return [
        line("real_roas", "실질 ROAS", me.real_roas, make_detail(
            "실질 ROAS = 마케팅 후 공헌(GMV − 환불 − 원가 − 채널 수수료 − 배송비 − 반품 물류비 − 광고비) ÷ 광고비. 높은 순위가 1위",
            (("실질 ROAS", me.real_roas), ("순위", me.rank), ("전체 인플루언서 수", n)), STATS_SOURCES), rank=me.rank),
        line("spend_share", "광고비 비중(%)", me.spend_share, make_detail(
            "광고비 비중 = 이 인플루언서 광고비 ÷ 전체 광고비. 큰 순위가 1위",
            (("광고비 비중(%)", me.spend_share), ("순위", spend_rank), ("전체 인플루언서 수", n)),
            (_AD, _CAMP)), rank=spend_rank),
        line("allocation_inversion", "배분 역전", inverted, make_detail(
            "광고비 비중 순위가 상위 절반인데 실질 ROAS 순위가 하위 절반이면 돈을 많이 쓴 곳일수록 성과가 낮은 역전",
            (("광고비 순위", spend_rank), ("실질 ROAS 순위", me.rank), ("전체 인플루언서 수", n)), STATS_SOURCES)),
        line("simple_change_return", "단순변심 반품률", mine, make_detail(
            "단순변심 반품률 = 사유가 단순변심인 환불액 ÷ 해당 주문 GMV. 이 인플루언서와 그 외 인플루언서 전체를 비교",
            (("이 인플루언서", mine), ("그 외", rest)), _RET_SRC),
             compare_label="그 외 인플루언서", compare_value=rest),
    ]


def cost_rows(influencer_id: str) -> dict:
    """비용 분해 단계(매출 -> 마케팅 전 공헌 -> 인플루언서 피 -> 다른 매체 -> 피 뒤 -> 최종)."""
    b = cost_breakdown(influencer_id)

    def row(key, label, amount, detail):
        return {"key": key, "label": label, "amount": amount, "badge": "계산", "detail": resolve_detail(detail)}

    return {"note": COST_NOTE, "rows": [
        row("gmv", "매출(GMV)", b.gmv, make_detail(
            "이 인플루언서 캠페인에 귀속된 주문의 GMV 합(마지막 클릭 7일 귀속, 캠페인 없는 주문 제외)",
            (("매출", b.gmv),), (_ORD, _CAMP))),
        row("pre_marketing", "마케팅 전 공헌", b.pre_marketing, make_detail(
            "마케팅 전 공헌 = GMV − 환불 − 원가 − 채널 수수료 − 배송비 − 반품 건수 × 반품 물류비",
            (("매출", b.gmv), ("마케팅 전 공헌", b.pre_marketing)), STATS_SOURCES[:4])),
        row("influencer_fee", "인플루언서 피", b.influencer_fee, make_detail(
            "광고비 중 매체가 '인플루언서'인 금액의 합", (("인플루언서 피", b.influencer_fee),), (_AD, _CAMP))),
        row("other_media", "다른 매체 광고비", b.other_media, make_detail(
            "광고비 중 매체가 '인플루언서'가 아닌 금액의 합", (("다른 매체", b.other_media),), (_AD, _CAMP))),
        row("after_fee", "피 뒤 공헌", b.after_fee, make_detail(
            "피 뒤 공헌 = 마케팅 전 공헌 − 인플루언서 피",
            (("마케팅 전 공헌", b.pre_marketing), ("인플루언서 피", b.influencer_fee)), STATS_SOURCES)),
        row("final", "최종 공헌", b.final, make_detail(
            "최종 공헌 = 피 뒤 공헌 − 다른 매체 광고비",
            (("피 뒤 공헌", b.after_fee), ("다른 매체", b.other_media)), STATS_SOURCES)),
    ]}


def evidence(subject_kind: str, ref_id: str, source_plan_id: str | None) -> dict:
    """한 건의 지표 근거 묶음(결재선 이유 rule은 엔진이 더한다). subject_kind: 'plan' | 'contract'."""
    empty = {"available": False, "reason": None, "influencer_id": None, "signals": [], "key_indicators": [],
             "cost_breakdown": None, "breakeven": None, "attribution_note": None}
    if subject_kind == "plan":
        plan_id = source_plan_id or ref_id
        inf = influencer_of_plan(plan_id)
        if inf is None or not has_performance(inf):
            return {**empty, "reason": NO_PLAN_BASIS}
        sigs = risk_signals(plan_id)
    else:
        inf = ref_id
        if not has_performance(inf):
            return {**empty, "reason": NO_CONTRACT_BASIS}
        sigs = future_value_signals(inf)
    be = breakeven_hidden_sales(inf)
    return {"available": True, "reason": None, "influencer_id": inf,
            "signals": [signal_line(s) for s in sigs], "key_indicators": key_indicators(inf),
            "cost_breakdown": cost_rows(inf), "breakeven": signal_line(be), "attribution_note": ATTRIBUTION_NOTE}
