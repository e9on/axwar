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
