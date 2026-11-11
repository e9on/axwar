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
