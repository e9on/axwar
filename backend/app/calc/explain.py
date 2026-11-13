"""근거 줄을 쉬운 한국어 한두 문장으로 풀어 쓴다(이슈 #41). 규칙 템플릿이라 AI가 아니고 같은 입력이면 같은 문장이다.

문장 모양: "무엇이 어떻다(실제 값) + 비교 대상은 어떻다 + 그래서 좋아요/나빠요/주의가 필요해요/잴 수 없어요".
결론은 줄의 level과 반드시 같다(red 나빠요, yellow 주의가 필요해요, green 좋아요, unmeasurable 잴 수 없어요).
값은 계산에 이미 있는 값(신호 값·비교 값·detail.inputs)만 쓰고 새 기준을 만들지 않는다.
읽는 말: 비율은 "100건 중 약 N건" 또는 "N%", 금액은 "약 2억 4,900만 원"(세 자리까지), 배수는 "평균의 약 N배".
"""
# hardcode-allow: 100_000_000 10_000 (억·만 단위 표기 변환, 정책 값 아님)
import re
from datetime import date

from app import policy
from app.calc import cash
from app.rules.josa import josa

WORD = {"red": "나빠요", "yellow": "주의가 필요해요", "green": "좋아요", "unmeasurable": "잴 수 없어요"}
ROAS = "실질 ROAS(광고비 1원당 남긴 이익)"  # 처음 한 번 풀어 쓰는 말
FORECAST_NOTE = "이 값은 예상치라 결정에는 쓰지 않아요."
NO_NAME = "이 인플루언서"
_EOK, _MAN, _SIG = 100_000_000, 10_000, 3  # 억·만 단위와 보여 줄 유효 숫자 자리


# ---------------------------------------------------------------- 낱말 도우미

def _round(x: float) -> int:
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def won(n: float) -> str:
    """금액을 억·만 단위로, 유효 숫자 세 자리까지(반올림하면 '약'을 붙임). 부호는 떼고 읽는다(적자·이익은 쓰는 쪽이 말함)."""
    v = abs(_round(n))
    if v == 0:
        return "0원"
    digits = len(str(v))
    unit = 10 ** (digits - _SIG) if digits > _SIG else 1
    r = (v + unit // 2) // unit * unit
    eok, rest = divmod(r, _EOK)
    man, low = divmod(rest, _MAN)
    parts = []
    if eok:
        parts.append(f"{eok:,}억")
    if man:
        parts.append(f"{man:,}만")
    if low:
        parts.append(f"{low:,}")
    return ("" if r == v else "약 ") + " ".join(parts) + (" 원" if eok or man else "원")


def per100(ratio: float, unit: str = "건") -> str:
    """0~1 비율을 '100건 중 약 N건'으로. 0은 0건, 1 미만은 '1건 미만'."""
    if ratio <= 0:
        return f"100{unit} 중 0{unit}"
    n = _round(ratio * 100)
    return f"100{unit} 중 약 {n}{unit}" if n else f"100{unit} 중 1{unit} 미만"


def pct(ratio: float) -> str:
    return f"{ratio * 100:.1f}%"


def pct0(percent_value: float) -> str:
    """이미 퍼센트인 값(40.6)을 정수 퍼센트로."""
    return f"{_round(percent_value)}%"


def day_ko(iso: str) -> str:
    d = date.fromisoformat(str(iso))
    return f"{d.month}월 {d.day}일"


def _md(iso: str) -> str:
    d = date.fromisoformat(str(iso))
    return f"{d.month}/{d.day}"


def _num(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.1f}"


def flow(n: float) -> str:
    """금액의 방향을 말로: 양수는 '약 X 이익', 음수는 '약 X 손해'."""
    return f"{won(n)} 이익" if n >= 0 else f"{won(n)} 손해"


def _ins(detail: dict | None) -> dict:
    return {i["label"]: i["value"] for i in (detail or {}).get("inputs", [])}


def plain(text: str) -> str:
    """풀이를 만들 수 없는 옛 줄: 원래 문장에서 내부 용어·기호만 걷어 낸다."""
    t = re.sub(r"[🔴🟡🟢]", "", text)
    t = t.replace("covenant 규정", "현금 하회 구간 규정").replace("covenant", "현금 하회 구간 규정")
    t = t.replace("HHI", "광고비가 한쪽에 몰린 정도").replace("DSO", "업계 평균 회수 기간")
    t = re.sub(r"(, )?(두 비율 )?z\s*=\s*-?[\d.]+,?\s*", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _end(level: str) -> str:
    return WORD[level]


# ---------------------------------------------------------------- 지표 신호

def signal(s: dict, name: str) -> str:
    """신호 줄(기안 7개·계약 2개·본전) 하나의 풀이. s는 evidence.signal_line이 만든 줄."""
    fn = _SIGNALS.get(s["key"])
    if fn is None:
        return plain(s.get("detail", {}).get("formula") or s["label"]) + f" {_end(s['level'])}."
    text = fn(s, _ins(s.get("detail")), name)
    if s.get("judgment") == "참고":
        text += " " + FORECAST_NOTE
    return text


def _forecast_gap(s, i, name):
    r, top = i["예상 ROAS"], i["명목 ROAS 최대"]
    head = (f"이 기안은 요청 예산 1원당 약 {r:.1f}원어치 매출을 예상해요. "
            f"지금까지 가장 잘 번 인플루언서는 광고비 1원당 약 {top:.1f}원어치 매출을 냈어요.")
    if s["level"] == "red":
        return head + f" 예상이 그보다 약 {r / top:.1f}배 높아서 나빠요."
    return head + " 예상이 그 안이라 좋아요."


def _coupon(s, i, name):
    k1, n1, k2, n2 = i["이 인플루언서 중복 적용 주문"], i["이 인플루언서 주문"], i["나머지 중복 적용 주문"], i["나머지 주문"]
    p1, p2 = k1 / n1, k2 / n2
    head = f"{name} 캠페인 주문 {per100(p1)}에 쿠폰이 겹쳐 쓰였어요. 다른 인플루언서는 {per100(p2)} 꼴이라"
    if s["level"] == "red":
        return head + " 훨씬 많아서 나빠요."
    if p1 <= p2:
        return head + " 더 적어서 좋아요."
    return head + " 조금 많지만 눈에 띄는 차이는 아니라서 좋아요."


def _slow(s, i, name):
    share = i["지연 채널 GMV"] / i["이 인플루언서 GMV"] if i["이 인플루언서 GMV"] else 0.0
    days = _num(i["업계 DSO(일)"])
    if share <= 0:
        return f"{name} 매출은 업계 평균 회수 기간 {days}일보다 대금을 늦게 받는 채널에서 나오지 않아서 좋아요."
    head = f"{name} 매출 중 약 {pct0(share * 100)}가 업계 평균 회수 기간 {days}일보다 대금을 늦게 받는 채널에서 나와요."
    if s["level"] == "red":
        return head + " 게다가 현금이 모자라지는 기간도 있어서 나빠요."
    return head + " 지금은 현금이 모자라지는 기간이 없지만 주의가 필요해요."


def _spend(s, i, name):
    share, top = i["이 인플루언서 광고비 비중(%)"], i["광고비 1위"]
    over = i["HHI"] > policy.get("signals.hhi_limit")
    if s["level"] == "red":
        return (f"전체 광고비의 약 {pct0(share)}가 {name}에게 쓰였고, 광고비가 한쪽에 몰린 정도가 기준을 넘었어요. "
                "광고비 1위라서 나빠요.")
    if over and not top:
        return (f"광고비 전체로는 한쪽에 몰린 정도가 기준을 넘지만, {name}에게 쓴 건 약 {pct0(share)}로 1위가 아니라서 좋아요.")
    return f"광고비가 한쪽에 몰린 정도가 기준 안이라 {name}에게 쓴 약 {pct0(share)}는 걱정 없어서 좋아요."


def _channel(s, i, name):
    m = re.match(r"(.+?) 기준 ", s["compare"] or "")
    ch = f"{m[1]} 채널" if m else "같은 유형 채널"
    mine, bench, mult = i["반품률(%)"] / 100, i["기준선(%)"] / 100, i["배수"]
    head = f"{ch} 평균 반품률이 {pct(bench)}인데 "
    if s["level"] == "red":
        return head + f"{josa(name, '은는')} {pct(mine)}로 평균의 약 {mult:.1f}배라 나빠요."
    if s["level"] == "yellow":
        return head + f"{josa(name, '은는')} {pct(mine)}로 평균보다 높아서 주의가 필요해요."
    if pct(mine) == pct(bench):
        return head + f"{name}도 {pct(mine)}라 평균 수준이어서 좋아요."
    return head + f"{josa(name, '은는')} {pct(mine)}로 평균보다 낮아서 좋아요."


def _trend(s, i, name):
    roas = list(i.values())
    if len(roas) < 2:
        return "비교할 캠페인이 하나뿐이라 추세는 알 수 없지만 나쁜 신호는 없어서 좋아요."
    diff = roas[-1] - roas[0]
    d = f"{abs(diff):.2f}"
    if s["level"] == "yellow":
        if d == "0.00":
            return f"첫 캠페인과 마지막 캠페인의 {ROAS}가 거의 같아서 개선되지 않고 있어요. 주의가 필요해요."
        return f"첫 캠페인보다 마지막 캠페인의 {ROAS}가 {d} 낮아져서 개선되지 않고 있어요. 주의가 필요해요."
    return f"첫 캠페인보다 마지막 캠페인의 {ROAS}가 {d} 높아졌어요. 개선되고 있어서 좋아요."


def _cannibal(s, i, name):
    return "표본의 고객이 인플루언서별로 완전히 나뉘어 있어서 다른 채널 구매를 빼앗았는지 비교할 수 없어요. 그래서 잴 수 없어요."


def _repurchase(s, i, name):
    n, k = i["첫 주문 귀속 고객"], i["90일 안 재구매 고객"]
    rate, bench = i["재구매율"], i["업계 기준 재구매율"]
    head = (f"{name} 캠페인으로 처음 산 고객 중 90일 안에 다시 산 사람은 {per100(rate, '명')}이에요. "
            f"업계 평균은 {per100(bench, '명')}이에요.")
    if s["level"] == "red":
        return head + " 평균보다 뚜렷하게 낮아서 나빠요."
    if s["level"] == "yellow":
        return head + " 평균보다 조금 낮아서 주의가 필요해요."
    return head + " 평균 이상이라 좋아요."


def _post(s, i, name):
    post, final = i["첫 구매 이후 주문 공헌"], i["최종 공헌"]
    head = f"{name} 캠페인으로 처음 산 고객이 이후 다시 사서 남긴 몫은 {flow(post)}이에요."
    if final < 0:
        return head + f" 그래도 광고비까지 뺀 최종 결과는 {won(final)} 적자라 재구매를 더해도 나빠요."
    return head + f" 광고비까지 뺀 최종 결과도 {won(final)} 남아서 좋아요."


def _breakeven(s, i, name):
    final = i["최종 공헌"]
    if s["level"] == "red":
        return "광고비를 쓰기 전부터 적자라 기록 밖에서 더 팔아도 본전이 되지 않아서 나빠요."
    if final >= 0:
        return f"광고비까지 뺀 최종 결과가 {won(final)} 남아 이미 본전 이상이라 좋아요."
    need = i["필요 비율"]
    return (f"지금 기록으로는 최종 결과가 {won(final)} 모자라요. 본전이 되려면 기록된 매출의 약 {pct0(need * 100)}만큼을 "
            "기록 밖에서 더 팔았어야 해요. 그 판매는 확인할 수 없어서 주의가 필요해요.")


_SIGNALS = {"forecast_gap": _forecast_gap, "coupon_stacking": _coupon, "slow_payment_channel": _slow,
            "spend_concentration": _spend, "channel_return_vs_benchmark": _channel, "trend": _trend,
            "cannibalization": _cannibal, "repurchase_rate": _repurchase, "post_contribution": _post,
            "breakeven_hidden_sales": _breakeven}


# ---------------------------------------------------------------- 핵심 지표

def real_roas(name: str, value: float, rank: int, n: int, bad: bool) -> str:
    gain = (f"광고비 1원당 {abs(value):.2f}원을 남겨요" if value >= 0 else f"광고비 1원당 {abs(value):.2f}원씩 손해예요")
    return f"{name}의 {ROAS}는 {gain}. {n}명 중 {rank}위라 {_end('red' if bad else 'green')}."


def spend_share(name: str, share: float, rank: int, n: int, top: bool, roas_bad: bool) -> str:
    head = f"전체 광고비의 약 {pct0(share)}가 {name}에게 쓰였고 {n}명 중 {rank}위예요."
    if top and roas_bad:
        return head + " 돈은 많이 쓰는데 성과는 낮아서 나빠요."
    if top:
        return head + " 많이 쓴 만큼 성과도 좋아서 좋아요."
    return head + " 광고비 비중이 크지 않아서 좋아요."


def request_share(name: str, share: float, rank: int | None, n: int, inverted: bool) -> str:
    if rank is None:
        return f"{name}의 기안이 원본 기안 파일에 없어서 요청 비중 순위를 알 수 없어요. 그래서 잴 수 없어요."
    head = f"이번 기안 문서 전체 요청액의 약 {pct0(share)}가 {name} 몫이고 {n}명 중 {rank}위예요."
    if inverted:
        return head + " 요청은 많은데 성과는 낮은 쪽이라 나빠요."
    return head + " 요청 규모와 성과가 크게 어긋나지 않아서 좋아요."


def allocation_inversion(inverted: bool, req_rank: int | None, req_n: int, roas_rank: int, n: int) -> str:
    if req_rank is None:
        return "기안 요청 비중 순위를 알 수 없어서 요청과 성과가 어긋나는지 잴 수 없어요."
    if inverted:
        return (f"기안 요청액은 {req_n}명 중 {req_rank}위로 많은데, 성과(광고비 1원당 남긴 이익)는 {n}명 중 {roas_rank}위로 낮아요. "
                "요청은 많은데 성과는 낮은 어긋남이라 나빠요.")
    return (f"기안 요청액은 {req_n}명 중 {req_rank}위, 성과(광고비 1원당 남긴 이익)는 {n}명 중 {roas_rank}위예요. "
            "요청은 많은데 성과가 낮은 어긋남은 아니라서 좋아요.")


def simple_change(name: str, mine: float, rest: float) -> str:
    head = f"매출 중 단순변심으로 환불된 몫이 {josa(name, '은는')} {pct(mine)}, 다른 인플루언서는 {pct(rest)}예요."
    red_mult = policy.get("signals.return_ratio_red")
    if mine > 0 and mine >= rest * red_mult:
        times = f"평균의 약 {mine / rest:.1f}배로 훨씬 높아서" if rest > 0 else "다른 인플루언서에는 거의 없어서"
        return head + f" {times} 나빠요."
    if mine > rest:
        return head + " 평균보다 조금 높아서 주의가 필요해요."
    return head + " 평균보다 낮거나 비슷해서 좋아요."


# ---------------------------------------------------------------- 비용 분해

def cost_row(key: str, name: str, b) -> str:
    """b = signals.CostBreakdown. 각 단계는 앞 단계와 이어서 읽는다."""
    if key == "gmv":
        return f"{name} 캠페인으로 팔린 매출은 {won(b.gmv)}이에요."
    if key == "pre_marketing":
        text = f"매출 {won(b.gmv)}에서 반품·원가·수수료·배송비를 빼면 "
        if b.pre_marketing >= 0:
            return text + f"{won(b.pre_marketing)}이 남아요."
        return text + f"{won(b.pre_marketing)} 모자라요. 광고비를 쓰기 전부터 적자라 나빠요."
    if key == "influencer_fee":
        text = f"그중 인플루언서에게 준 값은 {won(b.influencer_fee)}이에요."
        if b.pre_marketing > 0:
            text += f" 위에서 남은 {won(b.pre_marketing)}의 약 {pct0(100 * b.influencer_fee / b.pre_marketing)}예요."
        return text
    if key == "other_media":
        return f"인플루언서 말고 다른 매체에 쓴 광고비는 {won(b.other_media)}이에요."
    if key == "after_fee":
        text = f"{won(b.pre_marketing)}에서 인플루언서 값 {won(b.influencer_fee)}을 빼면 "
        if b.after_fee >= 0:
            return text + f"{won(b.after_fee)}이 남아요."
        return text + f"{won(b.after_fee)} 모자라요. 이미 적자라 나빠요."
    # final
    text = f"여기서 다른 매체 광고비 {won(b.other_media)}을 더 빼면 최종적으로 "
    if b.final >= 0:
        return text + f"{won(b.final)}이 남아서 좋아요."
    return text + f"{won(b.final)} 모자라 적자여서 나빠요."


# ---------------------------------------------------------------- 결재선 이유

def approver_hit(h: dict, ins: dict, delegate: str | None = None) -> str:
    """결재선 이유 줄(상신 포함). h = {rule_id, text, ...}, ins = 풀린 detail의 입력값."""
    rid, ceo, head = h["rule_id"], policy.get("roles.ceo"), policy.get("roles.head")
    labels = list(ins)
    try:
        if rid == "covenant_window":
            what, start, end = labels[0], ins["하회 구간 시작"], ins["하회 구간 끝"]
            return (f"{what} {day_ko(ins[what])}이 현금이 {won(cash.covenant_min_krw())} 아래로 떨어지는 기간"
                    f"({_md(start)}~{_md(end)}) 안이라 {josa(ceo, '와과')} 이사회가 결재해요.")
        if rid == "plan_item_over_limit":
            return (f"이 건의 요청액은 {won(ins['건별 요청액'])}으로 건별 한도 {won(ins['건별 한도'])}을 넘어서 "
                    f"{josa(head, '이가')} 결재하고 그룹에 보고해요.")
        if rid == "plan_total_over_limit":
            return (f"같은 기안 문서의 요청액 합계 {won(ins['기안 총액'])}이 총액 한도 {won(ins['총액 한도'])}을 넘어서 "
                    f"{josa(head, '이가')} 결재하고 그룹에 보고해요.")
        if rid == "plan_within_delegation":
            who = delegate or "담당 부서"
            return (f"건별 요청액 {won(ins['건별 요청액'])}이 한도 {won(ins['건별 한도'])} 이하이고 기안 총액 "
                    f"{won(ins['기안 총액'])}도 한도 {won(ins['총액 한도'])} 이하라 {josa(who, '이가')} 직접 결재해요.")
        if rid == "contract_over_limit":
            return (f"전속계약 연 금액 {won(ins['연 전속 금액'])}이 계약 한도 {won(ins['계약 한도'])}을 넘어서 "
                    f"{josa(ceo, '와과')} 이사회가 결재해요.")
        if rid == "contract_within_limit":
            return (f"전속계약 연 금액 {won(ins['연 전속 금액'])}이 계약 한도 {won(ins['계약 한도'])} 이하라 "
                    f"{josa(head, '이가')} 결재해요.")
        if rid == "escalation":
            frm, to = ins["올린 역할"], ins["받는 역할"]
            return (f"{josa(frm, '이가')} 판단하기 어렵다며 {to}에게 올렸어요. 이제 {josa(to, '이가')} 결재해요. "
                    f"올린 이유는 \"{ins['이유']}\"예요.")
    except (KeyError, IndexError, ValueError):
        return plain(h["text"])  # 옛 저장 행: 입력값이 없으면 원래 문장에서 용어만 걷어 냄
    if rid == "indicator_opposite":
        m = re.match(r"(.+?)라 (.+) 추가$", h["text"])
        if m:
            return f"{m[1]}이라 {josa(m[2], '을를')} 더해서 결재해요."
    return plain(h["text"])


def indicator_hit(h: dict) -> str:
    """지표 근거 줄 중 신호가 아닌 것(지표 좋음·근거 없음)."""
    if h["rule_id"] == "indicators_good":
        return "판정에 쓰는 위험 신호 중 나쁜 것이 하나도 없어서 좋아요."
    if h["rule_id"] == "no_signals":
        return "원본에 근거가 없어 지표를 판단할 수 없어요. 그래서 안전하게 나쁜 쪽으로 보고 있어요. 잴 수 없어요."
    return plain(h["text"])


# ---------------------------------------------------------------- 2차 반품 기준

def returns_item(label: str, baseline: float, qty: int, limit: float | None, count: int, rate: float | None, over: bool) -> str:
    if rate is None or limit is None:
        return f"{label} 반품 건수가 아직 없거나 1차로 내보낸 수량이 없어서 반품률을 잴 수 없어요."
    head = (f"1차로 {qty:,}개를 내보냈고 {label} 반품이 {count:,}건이라 {pct(rate)}예요. 평소 반품률은 {pct(baseline)}이고, "
            f"우연으로 볼 수 있는 한계는 {pct(limit)}예요.")
    return head + (" 한계를 넘어서 나빠요." if over else " 한계 안이라 좋아요.")
