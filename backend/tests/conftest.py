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
