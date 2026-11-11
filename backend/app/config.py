import os
from pathlib import Path

# backend/app/config.py -> 저장소 루트는 parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_ROOT: Path = Path(
    os.environ.get("AXWAR_DATA_ROOT", REPO_ROOT / "01_참가자_배포용" / "04_원본데이터")
)


def data_root() -> Path:
    """원본 데이터 루트. 호출할 때마다 환경변수를 다시 읽는다."""
    env = os.environ.get("AXWAR_DATA_ROOT")
    return Path(env) if env else DATA_ROOT


def ai_mode() -> str:
    """AI 모드: "fake"(기본, 키 없이 규칙 기반 고정 응답) | "real"(실제 모델 호출). 호출할 때마다 환경변수를 다시 읽는다."""
    return os.environ.get("AXWAR_AI", "fake")


def db_path() -> Path:
    """SQLite DB 파일 위치: AXWAR_DB 환경변수, 없으면 backend/var/axwar.db. 호출할 때마다 환경변수를 다시 읽는다."""
    env = os.environ.get("AXWAR_DB")
    return Path(env) if env else Path(__file__).resolve().parents[1] / "var" / "axwar.db"


def demo_dir() -> Path:
    """시연 파일 폴더: AXWAR_DEMO_DIR 환경변수, 없으면 backend/demo. 호출할 때마다 환경변수를 다시 읽는다."""
    env = os.environ.get("AXWAR_DEMO_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[1] / "demo"


def people_path() -> Path:
    """보는 사람·역할 파일: AXWAR_PEOPLE 환경변수(운영), 없으면 시연 폴더의 people.json."""
    env = os.environ.get("AXWAR_PEOPLE")
    return Path(env) if env else demo_dir() / "people.json"
