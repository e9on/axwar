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


def frontend_dist() -> Path:
    """화면 빌드 폴더: AXWAR_FRONTEND_DIST 환경변수, 없으면 저장소 루트의 frontend/dist. 없는 폴더면 API만 연다."""
    env = os.environ.get("AXWAR_FRONTEND_DIST")
    return Path(env) if env else REPO_ROOT / "frontend" / "dist"


def default_mode() -> str | None:
    """처음 DB를 만들 때의 실행 모드: AXWAR_MODE 환경변수("운영" 또는 "시연"), 없으면 None(저장소 기본 = 시연).
    배포(운영)에서는 이 변수를 "운영"으로 지정한다. 이미 저장된 모드가 있으면 쓰지 않는다."""
    return os.environ.get("AXWAR_MODE") or None
