"""비용 분해, 미래 가치, 위험 신호 지표. 원본 CSV만 읽고 표준 라이브러리만 쓴다.

통계 비교는 한쪽 95% 비율 검정(임계 z는 정책 split.stop_z). 반품 배수·HHI 기준은 정책 설정에 있고 원본에 없는 차용 기준이라 badge='가정'.
공헌(마케팅 전, 주문별) = gmv - 환불 - 원가 - 채널수수료 - 배송비 - 반품건수 x 반품물류비.
"""
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.calc.campaign import (
    _campaign_influencer,
    _campaign_stats,
    _returns_by_order,
    campaign_real_roas,
    influencer_ranking,
)
from app import policy
from app.calc.cash import breach_windows, forecast_window, simulate_cash
from app.data.loader import payment_term_notices, read_raw_text, read_table

_MKT = "02_masil/marketing/"
Level = Literal["red", "yellow", "green", "unmeasurable"]


@dataclass(frozen=True)
class CostBreakdown:
    influencer_id: str
    gmv: int
    pre_marketing: int
    influencer_fee: int
    other_media: int
    after_fee: int
    final: int


@dataclass(frozen=True)
class Signal:
    key: str
    label: str
    value: float | None
    compare: str
    level: Level
    basis: str
    badge: Literal["계산", "가정"]


def _campaigns() -> dict[str, dict]:
    return {r["campaign_id"]: r for r in read_table("02_masil/master/m_campaign_ms.csv")}


def _benchmark(metric: str) -> float:
    return next(r["value"] for r in read_table("05_external/benchmark/ext_industry_benchmark.csv") if r["metric"] == metric)


def _order_contributions() -> dict[str, float]:
    costs = {(r["sku_id"], r["channel_id"]): r for r in read_table(_MKT + "mkt_cost_master_ms.csv")}
    returns = _returns_by_order()
    out: dict[str, float] = {}
    for o in read_table(_MKT + "mkt_orders_ms.csv"):
        c = costs[(o["sku_id"], o["channel_id"])]
        rets = returns.get(o["order_id"], [])
        out[o["order_id"]] = (
            o["gmv_krw"]
            - sum(r["refund_amount_krw"] for r in rets)
            - c["product_cost_krw"]
            - o["gmv_krw"] * c["channel_fee_pct"] / 100
            - c["shipping_cost_krw"]
            - len(rets) * c["return_logistics_cost_krw"]
        )
    return out


def cost_breakdown(influencer_id: str) -> CostBreakdown:
    owner = _campaign_influencer()
    stats = _campaign_stats()
    mine = [cid for cid, inf in owner.items() if inf == influencer_id and cid in stats]
    gmv = sum(stats[c]["gmv"] for c in mine)
    pre = sum(
        stats[c]["gmv"] - stats[c]["refund"] - stats[c]["cogs"] - stats[c]["chfee"] - stats[c]["ship"] - stats[c]["retlog"]
        for c in mine
    )
    fee = other = 0
    for r in read_table(_MKT + "mkt_ad_spend_ms.csv"):
        if owner[r["campaign_id"]] != influencer_id:
            continue
        if r["media"] == "인플루언서":
            fee += r["ad_cost_krw"]
        else:
            other += r["ad_cost_krw"]
    pre_i = round(pre)
    return CostBreakdown(influencer_id, round(gmv), pre_i, fee, other, pre_i - fee, pre_i - fee - other)


def _first_buyers(influencer_id: str) -> tuple[set[str], dict[str, date]]:
    """첫 주문이 이 인플루언서 캠페인인 고객 집합과 고객별 첫 주문일."""
    owner = _campaign_influencer()
    first: dict[str, dict] = {}
    for o in read_table(_MKT + "mkt_orders_ms.csv"):
        cur = first.get(o["customer_ref"])
        if cur is None or (o["order_date"], o["order_id"]) < (cur["order_date"], cur["order_id"]):
            first[o["customer_ref"]] = o
    mine = {
        c
        for c, o in first.items()
        if o["campaign_id"] is not None and owner[o["campaign_id"]] == influencer_id
    }
    return mine, {c: first[c]["order_date"] for c in mine}


def future_value_signals(influencer_id: str) -> list[Signal]:
    customers, first_date = _first_buyers(influencer_id)
    flags = {r["customer_ref"]: r["reorder_within_90d"] for r in read_table(_MKT + "mkt_repurchase_ms.csv")}
    n = len(customers)
    k = sum(1 for c in customers if flags.get(c))
    rate = k / n if n else 0.0
    bench = _benchmark("repurchase_rate_pct") / 100
    z = (rate - bench) / math.sqrt(bench * (1 - bench) / n) if n else 0.0
    z_crit = policy.get("split.stop_z")
    level: Level = "red" if z < -z_crit else ("yellow" if rate < bench else "green")
    repurchase = Signal(
        "repurchase_rate", "90일 재구매율", rate, f"업계 {bench:.0%}", level,
        f"첫 주문 귀속 고객 {n}명 중 {k}명 재구매, z={z:.2f}, 한쪽 95% 검정(z<-{z_crit}면 유의하게 낮음)", "계산",
    )

    contrib = _order_contributions()
    post = sum(
        contrib[o["order_id"]]
        for o in read_table(_MKT + "mkt_orders_ms.csv")
        if o["customer_ref"] in customers and o["order_date"] > first_date[o["customer_ref"]]
    )
    final = cost_breakdown(influencer_id).final
    post_sig = Signal(
        "post_contribution", "첫 구매 이후 주문 공헌", post, f"최종 공헌 {final:,}원",
        "red" if final < 0 else "green",
        "이 인플루언서로 첫 구매한 고객의 첫 주문 이후 주문 공헌 합(마케팅 전). 최종 공헌에 이미 포함되어 있어 "
        "재구매를 더해도 최종 공헌이 음수면 위험 신호", "계산",
    )
    return [repurchase, post_sig]


def _payment_terms() -> dict[str, int]:
    """채널 마스터 결제조건. 통보문 발신 파트너의 채널은 통보문의 변경 일수로 덮어쓴다(통보가 마스터보다 최신)."""
    notices = payment_term_notices()
    terms = {r["channel_id"]: r for r in read_table("02_masil/master/m_channel_ms.csv")}
    return {
        cid: (notices[r["partner_code"]].new_days if r["partner_code"] in notices else r["payment_terms_days"])
        for cid, r in terms.items()
    }


def _z_greater(k1: int, n1: int, k2: int, n2: int) -> float:
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return (k1 / n1 - k2 / n2) / se if se else 0.0


def risk_signals(plan_id: str) -> list[Signal]:
    plan = next(p for p in read_table(_MKT + "mkt_budget_plan_ms.csv") if p["plan_id"] == plan_id)
    camps = _campaigns()
    camp = camps[plan["campaign_id"]]
    inf = camp["influencer_id"]
    owner = _campaign_influencer()
    orders = read_table(_MKT + "mkt_orders_ms.csv")
    mine = [o for o in orders if o["campaign_id"] is not None and owner[o["campaign_id"]] == inf]
    others = [o for o in orders if o["campaign_id"] is not None and owner[o["campaign_id"]] != inf]
    ranking = influencer_ranking()
    z_crit = policy.get("split.stop_z")
    hhi_limit = policy.get("signals.hhi_limit")
    ratio_red = policy.get("signals.return_ratio_red")
    signals: list[Signal] = []

    # 1) 예상 실적 괴리
    ratio = plan["expected_gmv_krw"] / plan["requested_budget_krw"]
    top_nominal = max(r.nominal_roas for r in ranking)
    signals.append(Signal(
        "forecast_gap", "예상 ROAS 괴리", ratio, f"인플루언서 명목 ROAS 최대 {top_nominal:.2f}",
        "red" if ratio > top_nominal else "green",
        "기안 예상 GMV ÷ 요청 예산이 표본 인플루언서별 명목 ROAS(GMV÷광고비) 최대값보다 크면 과대 예상", "계산",
    ))

    # 2) 쿠폰 중복
    stacked = {r["order_id"] for r in read_table(_MKT + "mkt_coupons_ms.csv") if r["stacked_flag"]}
    k1 = sum(1 for o in mine if o["order_id"] in stacked)
    k2 = sum(1 for o in others if o["order_id"] in stacked)
    p1, p2 = k1 / len(mine), k2 / len(others)
    z = _z_greater(k1, len(mine), k2, len(others))
    signals.append(Signal(
        "coupon_stacking", "쿠폰 중복 비중", p1, f"나머지 인플루언서 {p2:.3f}",
        "red" if z > z_crit else "green",
        f"중복 적용 주문 {k1}/{len(mine)} vs {k2}/{len(others)}, 두 비율 z={z:.2f}, 한쪽 95%(쿠폰 행 없는 주문은 비중복)", "계산",
    ))

    # 3) 결제 지연 채널
    dso = _benchmark("DSO_days")
    terms = _payment_terms()
    total = sum(o["gmv_krw"] for o in mine)
    slow = sum(o["gmv_krw"] for o in mine if terms[o["channel_id"]] > dso)
    share = slow / total if total else 0.0
    win = forecast_window()
    breaches = breach_windows(simulate_cash(win.start, win.end))
    notices = payment_term_notices()
    if share > 0 and breaches:
        lvl: Level = "red"
    elif share > 0:
        lvl = "yellow"
    else:
        lvl = "green"
    signals.append(Signal(
        "slow_payment_channel", "결제 지연 채널 매출 비중", share, f"업계 DSO {dso:g}일 초과",
        lvl,
        "결제조건이 업계 DSO보다 긴 채널의 GMV 비중. 통보문 적용: "
        + ", ".join(f"파트너 {n.partner_code} {n.new_days}일" for n in notices.values()) + ". "
        f"현금 하회 구간 {len(breaches)}개", "계산",
    ))

    # 4) 광고비 쏠림
    spend: dict[str, float] = defaultdict(float)
    for r in read_table(_MKT + "mkt_ad_spend_ms.csv"):
        spend[owner[r["campaign_id"]]] += r["ad_cost_krw"]
    tot = sum(spend.values())
    shares = {i: 100 * v / tot for i, v in spend.items()}
    hhi = sum(s * s for s in shares.values())
    is_top = shares.get(inf, 0) == max(shares.values())
    signals.append(Signal(
        "spend_concentration", "광고비 쏠림(HHI)", hhi, f"기준 {hhi_limit} 초과이고 광고비 1위면 위험",
        "red" if hhi > hhi_limit and is_top else "green",
        f"인플루언서별 광고비 비중 제곱합. 이 인플루언서 비중 {shares.get(inf, 0):.1f}%. {hhi_limit} 기준은 차용한 가정", "가정",
    ))

    # 5) 채널 반품 vs 기준선
    camp_orders = {o["order_id"]: o for o in orders if o["campaign_id"] == camp["campaign_id"]}
    gmv = sum(o["gmv_krw"] for o in camp_orders.values())
    refund = sum(r["refund_amount_krw"] for r in read_table(_MKT + "mkt_returns_ms.csv") if r["order_id"] in camp_orders)
    rate = refund / gmv if gmv else 0.0
    raw = read_raw_text("05_external/benchmark/ext_channel_benchmark.csv", "channel_type", camp["sales_channel"], "return_rate_pct")
    digits = len(raw.partition(".")[2])  # 기준선 원문의 소수 자릿수
    bench = float(raw) / 100
    # 기준선 표기 정밀도에 맞춰 실제 반품률도 같은 자릿수로 반올림해 비교한다
    rr = round(rate * 100, digits) / (bench * 100)
    unit = f"{10 ** -digits:g}%p"
    signals.append(Signal(
        "channel_return_vs_benchmark", "채널 반품률 / 기준선", rr, f"{camp['sales_channel']} 기준 {bench:.{digits}%}, 실제 {rate:.{digits}%}",
        "red" if rr >= ratio_red else ("yellow" if rr > 1 else "green"),
        f"기안 캠페인 주문의 금액 반품률 ÷ 같은 채널 유형 기준선. 반품률은 {unit} 반올림 후 비교. {ratio_red:g}배 이상 위험은 차용한 가정", "가정",
    ))

    # 6) 회차 추세
    seq = sorted((c for c in camps.values() if c["influencer_id"] == inf), key=lambda c: c["start_date"])
    roas = [campaign_real_roas(c["campaign_id"]) for c in seq]
    roas = [r for r in roas if r is not None]
    trend_val = roas[-1] - roas[0] if len(roas) >= 2 else None
    signals.append(Signal(
        "trend", "회차별 실질 ROAS 추세", trend_val, "마지막 ≤ 첫 번째면 개선 없음",
        "yellow" if trend_val is not None and trend_val <= 0 else "green",
        "시작일 순 실질 ROAS: " + ", ".join(f"{r:.3f}" for r in roas), "계산",
    ))

    # 7) 잠식
    signals.append(Signal(
        "cannibalization", "다른 채널 잠식", None, "측정 불가", "unmeasurable",
        "표본에서 고객이 인플루언서별로 완전히 나뉘어 측정할 수 없음", "계산",
    ))
    return signals


ATTRIBUTION_NOTE = "마지막 클릭 후 7일 기준으로 캠페인에 귀속 — 클릭 없이 나중에 산 구매는 빠지고(과소), 광고 없이도 샀을 구매는 포함됨(과대)"


def breakeven_hidden_sales(influencer_id: str) -> Signal:
    """본전이 되려면 기록된 매출의 몇 %만큼 기록 밖 판매가 더 필요한지(비율).
    (-최종 공헌) ÷ (공헌률 = 마케팅 전 공헌 ÷ GMV) ÷ GMV. 최종 공헌이 0 이상이면 0."""
    b = cost_breakdown(influencer_id)
    if b.final < 0 and (b.pre_marketing <= 0 or b.gmv == 0):
        return Signal(
            "breakeven_hidden_sales", "본전에 필요한 기록 밖 판매", None, "본전 불가",
            "red", "광고비를 빼기 전부터 적자라 기록 밖 판매가 늘어도 본전 불가. " + ATTRIBUTION_NOTE, "계산",
        )
    if b.final >= 0:
        value = 0.0
    else:
        value = (-b.final) / (b.pre_marketing / b.gmv) / b.gmv
    return Signal(
        "breakeven_hidden_sales", "본전에 필요한 기록 밖 판매", value, "0이면 이미 본전 이상",
        "yellow" if value > 0 else "green",
        f"(-최종 공헌 {b.final:,}원) ÷ (마케팅 전 공헌률 {b.pre_marketing:,}÷{b.gmv:,}) ÷ 기록 GMV. "
        f"본전이 되려면 기록된 매출의 {value:.1%}만큼 기록 밖 판매가 더 필요. {ATTRIBUTION_NOTE}",
        "계산",
    )
