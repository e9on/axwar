"""성능평가 실행기 테스트.

실행: uv run --no-project --python 3.11 --with pytest python -m pytest eval/test_run.py -q
"""
import importlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def load_run(monkeypatch, tmp_path):
    monkeypatch.setenv("AXWAR_KEYS", str(tmp_path / "없는파일.env"))
    sys.modules.pop("run", None)
    return importlib.import_module("run")


def test_키_파일이_없어도_모듈을_불러온다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    assert hasattr(run, "main")


def test_결과는_한_건마다_바로_파일에_추가된다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    out = tmp_path / "r.jsonl"
    run.append_row(out, {"task": "reviews", "model": "m", "rep": 0, "id": "R01", "err": None})
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1
    run.append_row(out, {"task": "reviews", "model": "m", "rep": 0, "id": "R02", "err": None})
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["id"] == "R02"


def test_성공한_건만_완료로_본다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    out = tmp_path / "r.jsonl"
    run.append_row(out, {"task": "reviews", "model": "m", "rep": 0, "id": "R01", "err": None})
    run.append_row(out, {"task": "reviews", "model": "m", "rep": 0, "id": "R02", "err": "429"})
    done = run.load_done(out)
    assert ("reviews", "m", 0, "R01") in done
    assert ("reviews", "m", 0, "R02") not in done


def test_이어하기는_완료된_건을_건너뛴다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    jobs = [("reviews", "m", 0, "R01"), ("reviews", "m", 0, "R02"), ("reviews", "m", 1, "R01")]
    done = {("reviews", "m", 0, "R01")}
    left = run.filter_jobs(jobs, done, key=lambda j: j)
    assert left == [("reviews", "m", 0, "R02"), ("reviews", "m", 1, "R01")]


def test_이어하기는_오류난_줄을_요약에서_새_결과로_대체한다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    out = tmp_path / "r.jsonl"
    run.append_row(out, {"task": "reviews", "model": "m", "rep": 0, "id": "R02", "err": "429"})
    run.append_row(out, {"task": "reviews", "model": "m", "rep": 0, "id": "R02", "err": None})
    rows = run.load_rows(out)
    assert len(rows) == 1
    assert rows[0]["err"] is None


def test_없는_결과_파일은_빈_완료로_본다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    assert run.load_done(tmp_path / "없음.jsonl") == set()


# ---- 보완 작업: Anthropic 요청 본문, 오류 기록, 예산, 잘림 ----

# call_model의 요청 본문·재시도·키 읽기는 backend/tests/test_providers.py에서 시험한다.
def test_call_model은_앱_제공자를_부르고_평가용_결과로_바꾼다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "가짜")
    seen = {}

    def fake_post(url, headers, body):
        seen["body"] = body
        usage = {"input_tokens": 10, "output_tokens": 20, "output_tokens_details": {"thinking_tokens": 5}}
        return {"content": [{"type": "text", "text": '{"a":1}'}], "stop_reason": "end_turn", "usage": usage}

    monkeypatch.setattr(run.providers, "post", fake_post)
    r = run.call_model("claude-sonnet-5-5", "sys", "usr")
    assert r == run.CallResult('{"a":1}', 10, 20, "end_turn", 5)
    assert seen["body"]["max_tokens"] == run.policy.get("ai.max_tokens")



def test_예산에_도달하면_새_호출을_멈춘다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    budget = run.Budget(1.0)
    called = []

    def work(job):
        called.append(job)
        budget.add(0.6)

    skipped = run.run_pool(list(range(5)), work, budget, workers=1)
    assert called == [0, 1] and skipped == 3 and budget.reached


def test_예산이_없으면_끝까지_돈다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    budget = run.Budget(None)
    assert run.run_pool([1, 2, 3], lambda j: budget.add(100), budget, workers=2) == 0


def test_잘리거나_오류난_건은_완료가_아니다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    out = tmp_path / "r.jsonl"
    base = {"task": "replies", "model": "m", "rep": 0, "err": None}
    run.append_row(out, {**base, "id": "P01", "out": {"stance": "수용"}, "stop_reason": "end_turn"})
    run.append_row(out, {**base, "id": "P02", "out": None, "stop_reason": "end_turn"})
    run.append_row(out, {**base, "id": "P03", "out": {"stance": "수용"}, "stop_reason": "max_tokens"})
    done = run.load_done(out)
    assert ("replies", "m", 0, "P01") in done
    assert ("replies", "m", 0, "P02") not in done
    assert ("replies", "m", 0, "P03") not in done


def test_예상_비용은_모델_단가로_계산한다(monkeypatch, tmp_path):
    run = load_run(monkeypatch, tmp_path)
    assert run.estimate_cost("claude-sonnet-5-5", 1_000_000, 1_000_000) == 12.0
