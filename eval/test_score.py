"""채점 모듈 테스트.

실행: uv run --no-project --python 3.11 --with pytest python -m pytest eval -q -p no:cacheprovider
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from score import score_row, summarize  # noqa: E402

LAB = {"stance": "조건부수용", "qty_limit": 2500, "next_date": "2026-07-28", "needs_human": False}


def out(**kw):
    base = {"stance": "조건부수용", "qty_limit": 2500, "next_date": "2026-07-28", "needs_human": False}
    base.update(kw)
    return base


def test_전부_맞으면_all_ok():
    s = score_row("replies", out(), LAB)
    assert s["all_ok"] and not s["truncated"] and not s["danger"] and not s["safe"]


def test_복수_정답은_포함이면_정답():
    lab = {**LAB, "qty_limit": [4000, None]}
    assert score_row("replies", out(qty_limit=4000), lab)["field_ok"]["qty_limit"]
    assert score_row("replies", out(qty_limit=None), lab)["field_ok"]["qty_limit"]
    assert not score_row("replies", out(qty_limit=2500), lab)["field_ok"]["qty_limit"]


def test_숫자는_문자열이어도_같게_본다():
    assert score_row("replies", out(qty_limit="2,500"), LAB)["field_ok"]["qty_limit"]


def test_위험_오답은_정답_true인데_false():
    lab = {**LAB, "needs_human": True}
    s = score_row("replies", out(needs_human=False), lab)
    assert s["danger"] and not s["safe"] and not s["field_ok"]["needs_human"]


def test_안전_오답은_정답_false인데_true():
    s = score_row("replies", out(needs_human=True), LAB)
    assert s["safe"] and not s["danger"]


def test_허용값_밖이면_invalid():
    s = score_row("replies", out(stance="애매함"), LAB)
    assert "stance" in s["invalid"] and not s["all_ok"]
    r = score_row("reviews", {"reason": "기분탓", "sentiment": "긍정", "content_gap": False},
                  {"reason": "만족", "sentiment": "긍정", "content_gap": False})
    assert r["invalid"] == ["reason"]
    r = score_row("reviews", {"reason": "만족", "sentiment": "좋음", "content_gap": False},
                  {"reason": "만족", "sentiment": "긍정", "content_gap": False})
    assert r["invalid"] == ["sentiment"]


def test_거절인데_needs_human_false면_true로_강제하고_forced():
    lab = {"stance": "거절", "qty_limit": 0, "next_date": None, "needs_human": True}
    s = score_row("replies", out(stance="거절", qty_limit=0, next_date=None, needs_human=False), lab)
    assert s["forced"] and s["field_ok"]["needs_human"] and s["all_ok"] and not s["danger"]


def test_정보부족도_강제():
    lab = {"stance": "정보부족", "qty_limit": None, "next_date": None, "needs_human": True}
    s = score_row("replies", out(stance="정보부족", qty_limit=None, next_date=None, needs_human=None), lab)
    assert s["forced"] and s["all_ok"]


def test_강제가_필요없으면_forced_아님():
    assert not score_row("replies", out(), LAB)["forced"]


def test_응답_없음은_잘림이지_오답이_아님():
    s = score_row("replies", None, LAB)
    assert s["truncated"] and not s["all_ok"] and not s["danger"] and not s["safe"]


def test_stop_reason_max_tokens도_잘림():
    s = score_row("replies", out(), LAB, stop_reason="max_tokens")
    assert s["truncated"]


def test_리뷰는_sentiment_뺀_정답도_표시():
    lab = {"reason": "만족", "sentiment": "긍정", "content_gap": False}
    s = score_row("reviews", {"reason": "만족", "sentiment": "중립", "content_gap": False}, lab)
    assert not s["all_ok"] and s["all_ok_no_sentiment"]


def _row(model, rid, rep, o, label, task="replies", stop=None, ms=100):
    s = score_row(task, o, label, stop_reason=stop)
    return {"task": task, "model": model, "rep": rep, "id": rid, "ms": ms, "in_tok": 1000, "out_tok": 100,
            "out": o, "label": label, "stop_reason": stop, **s}


def test_요약은_잘림을_분모에서_빼고_센다():
    rows = [_row("m", "P01", 0, out(), LAB), _row("m", "P02", 0, None, LAB),
            _row("m", "P01", 1, out(), LAB), _row("m", "P02", 1, out(qty_limit=1), LAB)]
    text = summarize(rows, ["replies"], ["m"], {"m": ("anthropic", 1, 1)})
    line = [l for l in text.splitlines() if l.startswith("m ")][0]
    cells = [c.strip() for c in line.split("|")]
    assert cells[1] == "67%"   # 3건 중 2건 정답(잘림 1건 제외)
    assert cells[2] == "1"     # 잘림 수


def test_rescore는_새_라벨로_다시_채점하고_모델_제외와_task_선택을_지원한다(tmp_path, monkeypatch):
    import json
    import importlib
    monkeypatch.setenv("AXWAR_KEYS", str(tmp_path / "없음.env"))
    sys.modules.pop("run", None)
    rescore = importlib.import_module("rescore")
    lab_new = {**LAB, "qty_limit": [2500, None]}
    base = {"task": "replies", "model": "claude-haiku-5-5", "rep": 0, "ms": 5, "in_tok": 1, "out_tok": 1,
            "err": None, "label": {**LAB, "qty_limit": 1}, "out": out()}
    rows = [{**base, "id": "P01"}, {**base, "id": "P02", "model": "gemini-3.8-flash"},
            {**base, "id": "P03", "task": "reviews", "out": None}]
    f = tmp_path / "r.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    labels = {("replies", "P01"): lab_new, ("replies", "P02"): lab_new, ("reviews", "P03"): LAB}
    text = rescore.rescore([f], labels, exclude=["gemini-3.8-flash"], only="replies")
    assert "claude-haiku-5-5" in text and "gemini-3.8-flash" not in text and "## reviews" not in text
    line = [l for l in text.splitlines() if l.startswith("claude-haiku-5-5")][0]
    assert line.split("|")[1].strip() == "100%"   # 옛 라벨이면 오답이었던 건이 새 라벨로 정답
