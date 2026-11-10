"""AI 판정 모델 성능평가.

사용법: py -3.11 eval/run.py [--models a,b] [--limit N] [--reps N] [--task reviews|replies] [--budget USD]
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
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from prompts import REPLY_SYSTEM, REVIEW_SYSTEM, reply_user, review_user  # noqa: E402
from score import norm, score_row, summarize  # noqa: E402,F401

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
    """제대로 끝난 건의 키 집합. 오류·응답 없음·잘림(max_tokens)은 이어하기에서 다시 돌린다."""
    def complete(r: dict) -> bool:
        if r.get("err") is not None or r.get("stop_reason") == "max_tokens":
            return False
        return not ("out" in r and r["out"] is None)
    return {job_key(r) for r in load_rows(path) if complete(r)}


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
            last = f"{e.code} {e.read().decode('utf-8', 'replace')[:300]}"
            if e.code == 429 or e.code >= 500:
                continue
            raise RuntimeError(last) from None
    raise RuntimeError(f"재시도 한도 초과 (마지막: {last})")


CallResult = namedtuple("CallResult", "text in_tok out_tok stop_reason thinking_tokens")


def call_model(model: str, system: str, user: str) -> CallResult:
    provider = MODELS[model][0]
    if provider == "anthropic":
        # thinking·temperature는 보내지 않는다(Sonnet 5.5는 thinking disabled가 400). 생각 깊이는 effort로만 낮춘다.
        b = post("https://api.anthropic.com/v1/messages",
                 {"x-api-key": key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
                 {"model": model, "max_tokens": 2048, "output_config": {"effort": "low"}, "system": system,
                  "messages": [{"role": "user", "content": user}]})
        text = "".join(c.get("text", "") for c in b["content"] if c["type"] == "text")
        details = b["usage"].get("output_tokens_details") or {}
        return CallResult(text, b["usage"]["input_tokens"], b["usage"]["output_tokens"],
                          b.get("stop_reason"), details.get("thinking_tokens"))
    if provider == "gemini":
        b = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                 {"x-goog-api-key": key("GEMINI_API_KEY")},
                 {"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": user}]}],
                  "generationConfig": {"responseMimeType": "application/json"}})
        u = b.get("usageMetadata", {})
        parts = (b.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        fin = (b.get("candidates") or [{}])[0].get("finishReason")
        return CallResult(text, u.get("promptTokenCount", 0),
                          u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0),
                          "max_tokens" if fin == "MAX_TOKENS" else fin, u.get("thoughtsTokenCount"))
    b = post("https://api.upstage.ai/v1/chat/completions",
             {"Authorization": "Bearer " + key("UPSTAGE_API_KEY")},
             {"model": model, "max_tokens": 300,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    u = b.get("usage", {})
    fin = b["choices"][0].get("finish_reason")
    return CallResult(b["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0),
                      u.get("completion_tokens", 0), "max_tokens" if fin == "length" else fin, None)


def estimate_cost(model: str, in_tok: float, out_tok: float) -> float:
    _, pi, po = MODELS[model]
    return (in_tok * pi + out_tok * po) / 1e6


class Budget:
    """누적 비용이 한도(USD)에 닿으면 새 호출을 멈추게 하는 스위치. 한도가 None이면 제한 없음."""

    def __init__(self, limit: float | None):
        self.limit, self.spent, self.reached = limit, 0.0, False
        self._lock = threading.Lock()

    def add(self, cost: float) -> None:
        with self._lock:
            self.spent += cost
            if self.limit is not None and self.spent >= self.limit:
                self.reached = True


def run_pool(jobs: list, work, budget: Budget, workers: int) -> int:
    """jobs를 work로 처리한다. 예산에 닿으면 남은 건은 호출하지 않고 건너뛴 수를 돌려준다."""
    skipped = 0
    lock = threading.Lock()

    def guarded(job):
        nonlocal skipped
        if budget.reached:
            with lock:
                skipped += 1
            return
        work(job)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(guarded, jobs))
    return skipped


def parse(text: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--task", choices=list(TASKS))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--budget", type=float, help="누적 비용 상한(USD). 넘으면 새 호출을 멈춘다")
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
    # 예상 비용: 한글 약 1.5자=1토큰, 출력은 Anthropic 150·그 외 80토큰으로 어림한다(실제와 다를 수 있음).
    est = sum(estimate_cost(j[4], len(j[1] + j[2](j[6])) / 1.5, 150 if MODELS[j[4]][0] == "anthropic" else 80)
              for v in jobs.values() for j in v)
    budget = Budget(a.budget)
    print(f"예상 비용 약 ${est:.2f} ({total}건)" + (f", 예산 ${a.budget:.2f}" if a.budget else ""),
          file=sys.stderr, flush=True)

    def run(job):
        t, system, user_fn, fields, model, rep, it = job
        t0 = time.time()
        text, in_tok, out_tok, err, stop, think = "", 0, 0, None, None, None
        try:
            text, in_tok, out_tok, stop, think = call_model(model, system, user_fn(it))
        except Exception as e:  # noqa: BLE001 - 실패도 결과로 기록한다
            err = str(e)
        budget.add(estimate_cost(model, in_tok, out_tok))
        out = parse(text)
        conf = out.get("confidence") if out else None
        row = {"task": t, "model": model, "rep": rep, "id": it["id"], "ms": int((time.time() - t0) * 1000),
               "err": err, "raw": text, "out": out, "label": it["label"],
               "conf": conf if isinstance(conf, (int, float)) else None,
               "in_tok": in_tok, "out_tok": out_tok, "stop_reason": stop, "thinking_tokens": think,
               **score_row(t, out, it["label"], stop)}
        nonlocal finished
        with lock:
            append_row(out_path, row)
            finished += 1
            if finished % 20 == 0:
                print(f"진행 {finished}/{total}", file=sys.stderr, flush=True)

    stopped = 0

    def run_provider(p):
        nonlocal stopped
        n = run_pool(jobs[p], run, budget, CONCURRENCY[p])
        with lock:
            stopped += n

    if jobs:
        with ThreadPoolExecutor(len(jobs)) as ex:
            list(ex.map(run_provider, jobs))
    if budget.reached:
        print(f"예산 도달: 누적 ${budget.spent:.2f}, 호출하지 않고 멈춘 건 {stopped}건 "
              "(--resume으로 이어서 돌릴 수 있음)", file=sys.stderr, flush=True)

    rows = [r for r in load_rows(out_path) if r["task"] in tasks and r["model"] in models]
    print(f"\n결과 파일: {out_path}\n")
    print(summarize(rows, tasks, models, MODELS))


if __name__ == "__main__":
    main()
