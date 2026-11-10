"""API 호출 없이 기존 결과 파일을 현재 라벨(eval/data)로 다시 채점해 표를 출력한다.

사용법: py -3.11 eval/rescore.py <결과파일...> [--exclude-model m] [--only reviews|replies]
표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run  # noqa: E402  (키 파일은 불러오지 않는다: 키는 call_model에서만 읽는다)
from score import FIELDS, score_row, summarize  # noqa: E402

DATA = Path(__file__).parent / "data"
FILES = {"reviews": "reviews.jsonl", "replies": "replies.jsonl"}


def load_labels() -> dict[tuple, dict]:
    labels = {}
    for task, fname in FILES.items():
        for line in (DATA / fname).read_text(encoding="utf-8").splitlines():
            if line.strip():
                it = json.loads(line)
                labels[(task, it["id"])] = it["label"]
    return labels


def rescore(paths: list, labels: dict, exclude: list | None = None, only: str | None = None) -> str:
    rows = []
    for p in paths:
        rows += run.load_rows(Path(p))
    rows = [r for r in rows if r["model"] not in (exclude or []) and (not only or r["task"] == only)]
    for r in rows:
        r["label"] = labels[(r["task"], r["id"])]
        r.update(score_row(r["task"], r.get("out"), r["label"], r.get("stop_reason")))
    tasks = [t for t in FIELDS if any(r["task"] == t for r in rows)]
    models = list(dict.fromkeys(r["model"] for r in rows))
    return summarize(rows, tasks, models, run.MODELS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--exclude-model", action="append", default=[])
    ap.add_argument("--only", choices=list(FILES))
    a = ap.parse_args()
    print(rescore(a.files, load_labels(), a.exclude_model, a.only))


if __name__ == "__main__":
    main()
