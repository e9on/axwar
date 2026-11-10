import os
from pathlib import Path

# backend/app/config.py -> 저장소 루트는 parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_ROOT: Path = Path(
    os.environ.get("AXWAR_DATA_ROOT", REPO_ROOT / "01_참가자_배포용" / "04_원본데이터")
)
