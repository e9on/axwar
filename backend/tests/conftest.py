import shutil

import pytest

from app import config
from app.data import loader


@pytest.fixture
def data_copy(tmp_path, monkeypatch):
    """원본을 임시 폴더에 복사하고 AXWAR_DATA_ROOT가 가리키게 한다(로더 캐시는 앞뒤로 비움)."""
    dst = tmp_path / "data"
    shutil.copytree(config.data_root(), dst)
    monkeypatch.setenv("AXWAR_DATA_ROOT", str(dst))
    loader._read.cache_clear()
    yield dst
    monkeypatch.undo()
    loader._read.cache_clear()


@pytest.fixture(autouse=True)
def _clear_policy_overrides():
    """설정 화면 덮어쓰기는 전역 상태라 시험 사이에 새지 않게 비운다."""
    from app import policy
    yield
    policy.clear_overrides()


@pytest.fixture
def legacy_scenes(tmp_path, monkeypatch):
    """이슈 #42 전에 쓰던 장면 1(PLAN-019, 재고 부족 → SCM 회신)과 상신 변형(PLAN-019 복사, 9월)을 시연 폴더 복사본에 되돌려 놓는다.
    재고 부족·SCM 길·상신 같은 엔진 동작은 그 데이터로 계속 시험하고, 지금 시연 장면은 test_task34.py가 본다."""
    from pathlib import Path
    dst = tmp_path / "demo_legacy"
    shutil.copytree(config.demo_dir(), dst)
    for f in (Path(__file__).parent / "legacy_demo").glob("*.json"):
        shutil.copy(f, dst / f.name)
    monkeypatch.setenv("AXWAR_DEMO_DIR", str(dst))
    yield dst


@pytest.fixture(autouse=True)
def _scm_wait_off_unless_set(monkeypatch):
    """정책 approval.wait_for_scm(기본 '예': SCM 회신 전 승인 막기)은 2026-11-14에 더했다. 그 전부터 있던 시험은 '먼저 승인 → SCM 회신 →
    재승인' 흐름(정책 '아니오'일 때의 동작)을 시험하므로, 이 항목을 따로 정하지 않은 시험에서는 '아니오'로 본다.
    '예' 동작은 그 값을 직접 정한 시험(test_task34)이 본다."""
    from app import policy

    key, original = "approval.wait_for_scm", policy.get

    def get(k):
        if k == key and not policy.is_overridden(key):
            return "아니오"
        return original(k)

    monkeypatch.setattr(policy, "get", get)


@pytest.fixture(autouse=True)
def _phase2_replies_accept(monkeypatch):
    """2차 물류·SCM 회신(사용자 결정으로 나중에 더한 요청)의 해석은 '수용'으로 돌려준다. 그 전부터 있던 시험은 가짜 AI 응답을
    순서대로 정해 두었으므로, 새 요청이 그 순서를 어긋나게 하지 않도록 이 해석은 정해 둔 응답을 쓰지 않는다.
    2차 회신을 따로 보는 시험(test_task34)은 대본의 ai 필드로 해석을 정한다."""
    import json
    from app.ai import providers

    markers = ("출고할 수 있는지, 처리할 수 있는 수량", "입고분으로 확보할 수 있는지")
    original = providers.FakeProvider.complete

    def complete(self, system, user):
        if self.model == "fake" and any(m in user for m in markers):  # 대본이 정한 해석(fake(대본))은 그대로
            body = {"stance": "수용", "qty_limit": None, "next_date": None, "needs_human": False, "confidence": 0.9}
            return providers.Completion(json.dumps(body, ensure_ascii=False), 0, 0, self.model)
        return original(self, system, user)

    monkeypatch.setattr(providers.FakeProvider, "complete", complete)
