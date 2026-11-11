"""핵심 지표 판정(설계 4.4) — 결정이 지표와 반대인지(4.1의 4번) 판단할 근거. 원본 CSV만 읽는다.

지표가 좋다 = 실질 ROAS(공헌이익 ÷ 마케팅비)가 0 이상이고, 단순변심 반품률(금액 기준)이 나머지
인플루언서보다 높지 않다. 둘 다 표본 계열이라 부호·비교 방향만 쓴다.
실적이 없는 인플루언서(화면에서 새로 등록 등)는 판단 근거가 없으므로 나쁨으로 본다(손실 먼저 경계, 설계 3장 2번).
"""
from dataclasses import dataclass

from app.calc.campaign import influencer_ranking, return_rate
from app.rules.models import RuleHit

CHANGE_OF_MIND = "단순변심"  # 원본 반품 사유 값
_SOURCE = "calculation_definitions 1.4·1.7"


@dataclass(frozen=True)
class KeyIndicators:
    influencer_id: str
    good: bool
    real_roas: float | None
    rank: int | None
    total: int
    change_of_mind_rate: float
    others_change_of_mind_rate: float
    hits: tuple[RuleHit, ...]


def key_indicators(influencer_id: str) -> KeyIndicators:
    ranking = influencer_ranking()
    me = next((r for r in ranking if r.influencer_id == influencer_id), None)
    mine = return_rate(influencer_id, CHANGE_OF_MIND)
    others = return_rate(None, CHANGE_OF_MIND, exclude=influencer_id)
    if me is None:
        hit = RuleHit("no_performance", f"{influencer_id}의 캠페인 실적이 원본에 없어 지표를 판단할 수 없음(나쁨으로 봄)",
                      _SOURCE, "계산")
        return KeyIndicators(influencer_id, False, None, None, len(ranking), mine, others, (hit,))
    hits: list[RuleHit] = []
    if me.real_roas < 0:
        hits.append(RuleHit("real_roas_negative",
                            f"실질 ROAS {me.real_roas:.3f}(인플루언서 {len(ranking)}명 중 {me.rank}위)로 음수",
                            _SOURCE, "계산"))
    if mine > others:
        hits.append(RuleHit("change_of_mind_high",
                            f"단순변심 반품률 {mine:.2%}가 나머지 인플루언서 {others:.2%}보다 높음",
                            _SOURCE, "계산"))
    if not hits:
        hits.append(RuleHit("indicators_good",
                            f"실질 ROAS {me.real_roas:.3f}(인플루언서 {len(ranking)}명 중 {me.rank}위), "
                            f"단순변심 반품률 {mine:.2%}(나머지 {others:.2%})로 지표 양호",
                            _SOURCE, "계산"))
    good = me.real_roas >= 0 and mine <= others
    return KeyIndicators(influencer_id, good, me.real_roas, me.rank, len(ranking), mine, others, tuple(hits))
