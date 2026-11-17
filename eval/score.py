"""성능평가 채점. run.py(실행 요약)와 rescore.py(재채점)가 함께 쓴다. 허용값·정규화는 backend/app/ai/judge.py에서 가져온다."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.ai.judge import ALLOWED, norm  # noqa: E402,F401  앱과 같은 허용값·정규화 규칙

FIELDS = {
    "reviews": ["reason", "sentiment", "content_gap"],
    "replies": ["stance", "qty_limit", "next_date", "needs_human"],
}


def _match(field: str, got, want) -> bool:
    """라벨이 리스트면 복수 정답: 포함 여부로 판정한다."""
    wants = want if isinstance(want, list) else [want]
    return norm(field, got) in [norm(field, w) for w in wants]


def score_row(task: str, out: dict | None, label: dict, stop_reason: str | None = None) -> dict:
    fields = FIELDS[task]
    empty = {f: False for f in fields}
    if out is None or stop_reason == "max_tokens":
        return {"truncated": True, "field_ok": empty, "all_ok": False, "all_ok_no_sentiment": False,
                "danger": False, "safe": False, "invalid": [], "forced": False}
    invalid = [f for f in ALLOWED if f in fields and norm(f, out.get(f)) not in ALLOWED[f]]
    forced = False
    got = dict(out)
    if task == "replies" and norm("stance", out.get("stance")) in ("거절", "정보부족") \
            and norm("needs_human", out.get("needs_human")) is not True:
        got["needs_human"] = True  # 앱과 같은 규칙: 거절·정보부족은 사람 확인
        forced = True
    field_ok = {f: _match(f, got.get(f), label[f]) for f in fields}
    danger = safe = False
    if task == "replies" and not field_ok["needs_human"]:
        danger = norm("needs_human", label["needs_human"]) is True
        safe = not danger
    return {"truncated": False, "field_ok": field_ok, "all_ok": all(field_ok.values()),
            "all_ok_no_sentiment": all(v for f, v in field_ok.items() if f != "sentiment"),
            "danger": danger, "safe": safe, "invalid": invalid, "forced": forced}


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def _consistency(rs: list[dict]) -> str:
    """같은 문항을 여러 번 돌려 필드 값이 모두 같은 비율. 잘린 응답은 뺀다."""
    groups: dict[str, list] = {}
    for r in rs:
        if r["truncated"]:
            continue
        sig = tuple(str(norm(f, r["out"].get(f))) for f in FIELDS[r["task"]])
        groups.setdefault(r["id"], []).append(sig)
    multi = [g for g in groups.values() if len(g) >= 2]
    return _pct(sum(1 for g in multi if len(set(g)) == 1), len(multi))


def summarize(rows: list[dict], tasks: list[str], models: list[str], prices: dict) -> str:
    lines: list[str] = []
    for t in tasks:
        extra = ["정답(sentiment 제외)"] if t == "reviews" else []
        lines.append(f"## {t}")
        lines.append(" | ".join(["모델", "전부 정답", "잘림", *extra, "위험 오답", "안전 오답", "형식 위반",
                                 "3회 일치율", "평균ms", "1천건당$", *FIELDS[t]]))
        for model in models:
            rs = [r for r in rows if r["task"] == t and r["model"] == model]
            if not rs:
                continue
            ok_rs = [r for r in rs if not r["truncated"]]
            n = len(ok_rs)
            _, pi, po = prices[model]
            cost = sum((r["in_tok"] * pi + r["out_tok"] * po) / 1e6 for r in rs)
            cells = [model, _pct(sum(r["all_ok"] for r in ok_rs), n), str(len(rs) - n)]
            if t == "reviews":
                cells.append(_pct(sum(r["all_ok_no_sentiment"] for r in ok_rs), n))
            cells += [str(sum(r["danger"] for r in ok_rs)), str(sum(r["safe"] for r in ok_rs)),
                      str(sum(1 for r in ok_rs if r["invalid"])), _consistency(rs),
                      str(round(sum(r["ms"] for r in rs) / len(rs))), f"{cost / len(rs) * 1000:.3f}"]
            cells += [_pct(sum(r["field_ok"][f] for r in ok_rs), n) for f in FIELDS[t]]
            lines.append(" | ".join(cells))
        lines.append("")
    return "\n".join(lines)
