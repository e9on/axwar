"""시연 파일(backend/demo) 읽기·검증과 엔진 코드의 장면값 대조. 장면 값은 시연 파일과 이 테스트에만 둔다."""
import json
import re
import shutil
from pathlib import Path

import pytest

from app import config
from app.data import loader
from app.engine import scenarios
from app.store.db import open_db

ENGINE_DIR = Path(scenarios.__file__).resolve().parent


@pytest.fixture
def store(tmp_path):
    s = open_db(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture
def demo(tmp_path):
    """임시 시연 폴더(사람 목록 복사)."""
    d = tmp_path / "demo"
    d.mkdir()
    shutil.copy(config.demo_dir() / "people.json", d / "people.json")
    return d


def _write(d: Path, name: str, body: dict) -> None:
    (d / f"{name}.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def _minimal(**over) -> dict:
    body = {"title": "t", "description": "d", "plans": [], "contracts": [], "requests": [], "script": []}
    body.update(over)
    return body


def test_시연_폴더_기본값과_환경변수(monkeypatch, tmp_path):
    monkeypatch.delenv("AXWAR_DEMO_DIR", raising=False)
    monkeypatch.delenv("AXWAR_PEOPLE", raising=False)
    assert config.demo_dir() == Path(config.__file__).resolve().parents[1] / "demo"
    assert config.people_path() == config.demo_dir() / "people.json"
    monkeypatch.setenv("AXWAR_DEMO_DIR", str(tmp_path))
    assert config.demo_dir() == tmp_path and config.people_path() == tmp_path / "people.json"
    monkeypatch.setenv("AXWAR_PEOPLE", str(tmp_path / "p.json"))
    assert config.people_path() == tmp_path / "p.json"


def test_장면1_파일을_읽는다():
    sc = scenarios.load("scenario_1")
    assert sc.name == "scenario_1" and sc.plans == ("PLAN-019",) and sc.contracts == ()
    assert [s["action"] for s in sc.script] == ["회신", "결정"]
    assert sc.script[0]["dept"] == "물류" and sc.script[1]["actor"] == "Masil 대표"


def test_사람_목록은_역할과_보고_체계를_담는다():
    people = scenarios.load_people()
    assert len(people.people) == 13
    assert people.role_of("Masil 대표") == "Masil 대표" and people.role_of("그룹 CEO") == "CEO"
    assert people.role_of("CEO") == "CEO"  # 역할 이름으로도 찾는다
    assert people.above("Masil 대표") == "CEO" and people.above("CEO") == "이사회" and people.above("이사회") == "이사회"
    with pytest.raises(PermissionError):
        people.role_of("모르는 사람")


def test_사람_목록에_모르는_역할이_있으면_오류(tmp_path):
    p = tmp_path / "people.json"
    p.write_text(json.dumps({"escalation": ["CEO"], "people": [{"name": "a", "role": "외계인"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="외계인"):
        scenarios.load_people(p)


def test_시연파일_형식_오류는_파일과_항목을_알려준다(demo):
    _write(demo, "bad1", {"title": "t"})
    with pytest.raises(ValueError, match="bad1.*plans"):
        scenarios.load("bad1", demo)
    _write(demo, "bad2", _minimal(script=[{"action": "춤추기"}]))
    with pytest.raises(ValueError, match="bad2.*춤추기"):
        scenarios.load("bad2", demo)
    _write(demo, "bad3", _minimal(script=[{"action": "결정", "plan": "X"}]))
    with pytest.raises(ValueError, match="bad3.*actor"):
        scenarios.load("bad3", demo)
    _write(demo, "bad4", _minimal(script=[{"action": "회신", "plan": "X", "dept": "물류", "text": "t",
                                            "date": "어제"}]))
    with pytest.raises(ValueError, match="bad4.*date"):
        scenarios.load("bad4", demo)
    with pytest.raises(FileNotFoundError):
        scenarios.load("없는파일", demo)
    with pytest.raises(ValueError):
        scenarios.load("../people", demo)  # 폴더 밖·경로 문자는 받지 않는다


def test_시연파일의_기안ID는_등록부나_원본에_있어야_한다(store, demo):
    _write(demo, "missing", _minimal(plans=["PLAN-999", "PLAN-019"]))
    sc = scenarios.load("missing", demo)
    with pytest.raises(ValueError, match="PLAN-999"):
        scenarios.check_refs(store, sc)
    _write(demo, "missing_c", _minimal(contracts=["INF-999"]))
    with pytest.raises(ValueError, match="INF-999"):
        scenarios.check_refs(store, scenarios.load("missing_c", demo))


def test_등록은_원본에서_값을_읽어_시연_출처로_넣는다(store):
    scenarios.register_plan(store, "PLAN-019")
    p = store.get_plan("PLAN-019")
    assert p["origin"] == "시연" and p["requested_budget_krw"] == 4807921 and p["settlement_date"] == "2026-09-14"
    assert p["influencer_id"] == "INF-002" and p["source_file"] == loader.PLAN_SOURCE
    scenarios.register_plan(store, "PLAN-019")  # 이미 있으면 그대로
    assert len(store.list_plans()) == 1


def test_등록부에_이미_있는_계약은_그대로_쓰고_없으면_통보문에서_시연_출처로(store):
    cid = scenarios.register_contract(store, "INF-001")
    c = store.get_contract(cid)
    assert c["origin"] == "시연" and c["annual_fixed_krw"] == 2800000000 and c["expiry_date"] == "2026-08-31"
    assert scenarios.register_contract(store, "INF-001") == cid


def _scene_values() -> set[str]:
    """시연 파일에 나온 ID·문장과, 그 ID가 가리키는 원본 기안의 금액·날짜(장면 값)."""
    values: set[str] = set()
    plan_rows = {r["plan_id"]: r for r in loader.plan_rows()}
    for f in config.demo_dir().glob("scenario_*.json"):
        body = json.loads(f.read_text(encoding="utf-8"))
        for pid in body.get("plans", []):
            values.add(pid)
            r = plan_rows[pid]
            values |= {r["campaign_id"], str(r["requested_budget_krw"]), f"{r['requested_budget_krw']:,}",
                       str(r["expected_gmv_krw"]), r["settlement_date"].isoformat(), r["contract_deadline"].isoformat()}
        values |= set(body.get("contracts", []))
        for step in body.get("script", []) + body.get("requests", []):
            if step.get("text"):
                values.add(step["text"])
            for v in step.values():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 100:
                    values.add(str(v))
    return values


def test_엔진코드에_장면값이_없다():
    values = _scene_values()
    assert "PLAN-019" in values and "4807921" in values  # 대조 목록이 실제로 채워졌는지
    sources = {p.name: p.read_text(encoding="utf-8") for p in ENGINE_DIR.glob("*.py")}
    assert {"flow.py", "scenarios.py"} <= set(sources)
    found = [(name, v) for name, src in sources.items() for v in values if v in src]
    assert found == []
    # 시연 파일 이름도 엔진에 박혀 있지 않다(파일 이름은 인자로만 받는다)
    for name, src in sources.items():
        assert not re.search(r"scenario_\d", src), name
