"""AI 판정 모델 성능평가.

사용법: py -3.11 eval/run.py [--models a,b] [--limit N] [--reps N] [--task reviews|replies]
키는 프로젝트 밖 C:/Users/e9on9/.axwar/keys.env 에서 읽는다(환경변수 AXWAR_KEYS로 바꿀 수 있음).
표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from prompts import REPLY_SYSTEM, REVIEW_SYSTEM, reply_user, review_user  # noqa: E402

DIR = Path(__file__).parent


def load_keys(path: str) -> dict[str, str]:
    keys = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip()
    return keys


_KEYS: dict[str, str] = {}


def key(name: str) -> str:
    """키는 처음 쓸 때 읽는다. 키 파일이 없어도 모듈은 불러올 수 있어야 테스트가 돈다."""
    if not _KEYS:
        _KEYS.update(load_keys(os.environ.get("AXWAR_KEYS", "C:/Users/e9on9/.axwar/keys.env")))
    return _KEYS[name]


def job_key(row: dict) -> tuple:
    return (row["task"], row["model"], row["rep"], row["id"])


def append_row(path: Path, row: dict) -> None:
    """한 건이 끝날 때마다 결과 파일에 한 줄 추가한다(중간에 멈춰도 남도록)."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def load_rows(path: Path) -> list[dict]:
    """결과 파일을 읽는다. 같은 건이 여러 번 있으면 마지막 줄(이어하기로 다시 돌린 결과)을 쓴다."""
    if not Path(path).exists():
        return []
    latest: dict[tuple, dict] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            latest[job_key(row)] = row
    return list(latest.values())


def load_done(path: Path) -> set[tuple]:
    """오류 없이 끝난 건의 키 집합. 오류 난 건은 이어하기에서 다시 돌린다."""
    return {job_key(r) for r in load_rows(path) if r.get("err") is None}


def filter_jobs(jobs: list, done: set, key) -> list:
    return [j for j in jobs if key(j) not in done]

# 100만 토큰당 USD (입력, 출력). Gemini는 무료 등급으로 돌리지만 유료 전환 시 비용 비교용으로 적는다.
MODELS = {
    "claude-haiku-5-5": ("anthropic", 0.10, 0.50),
    "claude-sonnet-5-5": ("anthropic", 2, 10),
    "claude-opus-5-5": ("anthropic", 4, 20),
    "gemini-3.1-flash-lite": ("gemini", 0.25, 1.50),
    "gemini-3.5-flash-lite": ("gemini", 0.30, 2.50),
    "gemini-3.8-flash": ("gemini", 0.75, 3.75),
    "solar-mini4": ("upstage", 0.10, 0.40),
    "solar-pro4": ("upstage", 0.30, 1.20),
}
CONCURRENCY = {"anthropic": 4, "upstage": 4, "gemini": 1}

TASKS = {
    "reviews": ("reviews.jsonl", REVIEW_SYSTEM, review_user, ["reason", "sentiment", "content_gap"]),
    "replies": ("replies.jsonl", REPLY_SYSTEM, reply_user, ["stance", "qty_limit", "next_date", "needs_human"]),
}


def post(url: str, headers: dict, body: dict) -> dict:
    data = json.dumps(body).encode()
    for attempt in range(6):
        req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                ra = float(e.headers.get("retry-after") or 0)
                time.sleep(max(ra, 2 * 2**attempt))
                continue
            raise RuntimeError(f"{e.code} {e.read()[:200]!r}") from None
    raise RuntimeError("재시도 한도 초과")


def call_model(model: str, system: str, user: str) -> tuple[str, int, int]:
    provider = MODELS[model][0]
    if provider == "anthropic":
        b = post("https://api.anthropic.com/v1/messages",
                 {"x-api-key": key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
                 {"model": model, "max_tokens": 300, "system": system, "messages": [{"role": "user", "content": user}]})
        text = "".join(c.get("text", "") for c in b["content"] if c["type"] == "text")
        return text, b["usage"]["input_tokens"], b["usage"]["output_tokens"]
    if provider == "gemini":
        b = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                 {"x-goog-api-key": key("GEMINI_API_KEY")},
                 {"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": user}]}],
                  "generationConfig": {"responseMimeType": "application/json"}})
        u = b.get("usageMetadata", {})
        parts = (b.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
    b = post("https://api.upstage.ai/v1/chat/completions",
             {"Authorization": "Bearer " + key("UPSTAGE_API_KEY")},
             {"model": model, "max_tokens": 300,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    u = b.get("usage", {})
    return b["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def parse(text: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def norm(field: str, v):
    if v is None or v in ("null", ""):
        return None
    if field == "qty_limit":
        try:
            return int(float(str(v).replace(",", "")))
        except ValueError:
            return str(v)
    if field in ("content_gap", "needs_human"):
        return v is True or v == "true"
    return str(v).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--task", choices=list(TASKS))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--resume", help="이어서 돌릴 결과 파일 경로. 오류 없이 끝난 건은 건너뛴다")
    a = ap.parse_args()
    models = a.models.split(",")
    tasks = [a.task] if a.task else list(TASKS)

    if a.resume:
        out_path = Path(a.resume)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        out_path = DIR / "results" / f"{stamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(out_path)

    jobs: dict[str, list] = {}
    for t in tasks:
        fname, system, user_fn, fields = TASKS[t]
        items = [json.loads(l) for l in (DIR / "data" / fname).read_text(encoding="utf-8").splitlines() if l.strip()]
        if a.limit:
            items = items[: a.limit]
        for model in models:
            for rep in range(a.reps):
                for it in items:
                    jobs.setdefault(MODELS[model][0], []).append((t, system, user_fn, fields, model, rep, it))

    skipped = 0
    for p in list(jobs):
        before = len(jobs[p])
        jobs[p] = filter_jobs(jobs[p], done, key=lambda j: (j[0], j[4], j[5], j[6]["id"]))
        skipped += before - len(jobs[p])
        if not jobs[p]:
            del jobs[p]
    if skipped:
        print(f"이어하기: 이미 끝난 {skipped}건 건너뜀", file=sys.stderr, flush=True)

    lock = threading.Lock()
    finished = 0
    total = sum(len(v) for v in jobs.values())

    def run(job):
        t, system, user_fn, fields, model, rep, it = job
        t0 = time.time()
        text, in_tok, out_tok, err = "", 0, 0, None
        try:
            text, in_tok, out_tok = call_model(model, system, user_fn(it))
        except Exception as e:  # noqa: BLE001 - 실패도 결과로 기록한다
            err = str(e)
        out = parse(text)
        field_ok = {f: out is not None and norm(f, out.get(f)) == norm(f, it["label"][f]) for f in fields}
        conf = out.get("confidence") if out else None
        row = {"task": t, "model": model, "rep": rep, "id": it["id"], "ms": int((time.time() - t0) * 1000),
               "err": err, "raw": text, "out": out, "label": it["label"], "field_ok": field_ok,
               "all_ok": all(field_ok.values()), "conf": conf if isinstance(conf, (int, float)) else None,
               "in_tok": in_tok, "out_tok": out_tok}
        nonlocal finished
        with lock:
            append_row(out_path, row)
            finished += 1
            if finished % 20 == 0:
                print(f"진행 {finished}/{total}", file=sys.stderr, flush=True)

    def run_provider(p):
        with ThreadPoolExecutor(CONCURRENCY[p]) as ex:
            list(ex.map(run, jobs[p]))

    if jobs:
        with ThreadPoolExecutor(len(jobs)) as ex:
            list(ex.map(run_provider, jobs))

    rows = [r for r in load_rows(out_path) if r["task"] in tasks and r["model"] in models]
    pct = lambda n, d: f"{100 * n / d:.0f}%" if d else "-"  # noqa: E731
    avg = lambda xs: f"{sum(xs) / len(xs):.2f}" if xs else "-"  # noqa: E731
    print(f"\n결과 파일: {out_path}\n")
    for t in tasks:
        fields = TASKS[t][3]
        print(f"## {t}")
        print(" | ".join(["모델", "전부 정답", *fields, "응답불가", "평균ms", "1천건당$", "정답 확신도", "오답 확신도"]))
        for model in models:
            rs = [r for r in rows if r["task"] == t and r["model"] == model]
            if not rs:
                continue
            _, pi, po = MODELS[model]
            cost = sum((r["in_tok"] * pi + r["out_tok"] * po) / 1e6 for r in rs)
            ok = [r for r in rs if r["all_ok"]]
            bad = [r for r in rs if not r["all_ok"] and r["out"]]
            print(" | ".join([model, pct(len(ok), len(rs)),
                              *[pct(sum(r["field_ok"][f] for r in rs), len(rs)) for f in fields],
                              str(sum(1 for r in rs if not r["out"])),
                              str(round(sum(r["ms"] for r in rs) / len(rs))),
                              f"{cost / len(rs) * 1000:.3f}",
                              avg([r["conf"] for r in ok if r["conf"] is not None]),
                              avg([r["conf"] for r in bad if r["conf"] is not None])]))
        print()


if __name__ == "__main__":
    main()
