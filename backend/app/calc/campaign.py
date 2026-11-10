"""캠페인·인플루언서 실질 ROAS와 반품률. 원본 CSV만 읽는다.

가정: 주문 1건 = 1개, 원가·배송비는 주문당 1회, 반품 시 원가 회수 없음,
반품 물류비는 반품 1건당 1회, 쿠폰은 GMV에 이미 반영(다시 빼지 않음),
마케팅비 = ad_cost_krw 전액. 귀속은 주문의 campaign_id(NONE 제외).
"""
from collections import defaultdict
from dataclasses import dataclass

from app.data.loader import read_table

_MKT = "02_masil/marketing/"


@dataclass(frozen=True)
class InfluencerPerf:
    influencer_id: str
    real_roas: float
    nominal_roas: float
    rank: int
    spend_share: float  # 전체 광고비 대비 %


def _campaign_influencer() -> dict[str, str]:
    return {r["campaign_id"]: r["influencer_id"] for r in read_table("02_masil/master/m_campaign_ms.csv")}


def _returns_by_order() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in read_table(_MKT + "mkt_returns_ms.csv"):
        out[r["order_id"]].append(r)
    return out


def _campaign_stats() -> dict[str, dict[str, float]]:
    costs = {(r["sku_id"], r["channel_id"]): r for r in read_table(_MKT + "mkt_cost_master_ms.csv")}
    returns = _returns_by_order()
    stats: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for o in read_table(_MKT + "mkt_orders_ms.csv"):
        cid = o["campaign_id"]
        if cid is None:
            continue
        c = costs[(o["sku_id"], o["channel_id"])]
        rets = returns.get(o["order_id"], [])
        s = stats[cid]
        s["gmv"] += o["gmv_krw"]
        s["refund"] += sum(r["refund_amount_krw"] for r in rets)
        s["cogs"] += c["product_cost_krw"]
        s["chfee"] += o["gmv_krw"] * c["channel_fee_pct"] / 100
        s["ship"] += c["shipping_cost_krw"]
        s["retlog"] += len(rets) * c["return_logistics_cost_krw"]
    for r in read_table(_MKT + "mkt_ad_spend_ms.csv"):
        stats[r["campaign_id"]]["spend"] += r["ad_cost_krw"]
    for s in stats.values():
        s["cp"] = s["gmv"] - s["refund"] - s["cogs"] - s["chfee"] - s["ship"] - s["retlog"] - s["spend"]
    return stats


def campaign_real_roas(campaign_id: str) -> float | None:
    s = _campaign_stats().get(campaign_id)
    if not s or s["spend"] == 0:
        return None
    return s["cp"] / s["spend"]


def influencer_ranking() -> list[InfluencerPerf]:
    owner = _campaign_influencer()
    agg: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for cid, s in _campaign_stats().items():
        a = agg[owner[cid]]
        for k in ("gmv", "cp", "spend"):
            a[k] += s[k]
    total_spend = sum(a["spend"] for a in agg.values())
    ordered = sorted(agg.items(), key=lambda kv: kv[1]["cp"] / kv[1]["spend"] if kv[1]["spend"] else float("-inf"), reverse=True)
    return [
        InfluencerPerf(
            influencer_id=inf,
            real_roas=a["cp"] / a["spend"],
            nominal_roas=a["gmv"] / a["spend"],
            rank=i,
            spend_share=100 * a["spend"] / total_spend,
        )
        for i, (inf, a) in enumerate(ordered, start=1)
        if a["spend"]
    ]


def return_rate(influencer_id: str | None, reason: str | None = None, exclude: str | None = None) -> float:
    """금액 기준 반품률 = 해당 반품 환불액 / 해당 주문 GMV.

    influencer_id가 있으면 그 인플루언서 캠페인 주문, None이면 전체(exclude 제외).
    reason을 주면 분자는 그 사유 반품만.
    """
    owner = _campaign_influencer()

    def included(cid: str | None) -> bool:
        if cid is None:
            return False
        inf = owner[cid]
        if influencer_id is not None:
            return inf == influencer_id
        return inf != exclude

    orders = {o["order_id"]: o for o in read_table(_MKT + "mkt_orders_ms.csv") if included(o["campaign_id"])}
    gmv = sum(o["gmv_krw"] for o in orders.values())
    refund = sum(
        r["refund_amount_krw"]
        for r in read_table(_MKT + "mkt_returns_ms.csv")
        if r["order_id"] in orders and (reason is None or r["reason"] == reason)
    )
    return refund / gmv if gmv else 0.0
