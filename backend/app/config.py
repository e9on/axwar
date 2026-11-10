import os
from pathlib import Path

# backend/app/config.py -> 저장소 루트는 parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_ROOT: Path = Path(
    os.environ.get("AXWAR_DATA_ROOT", REPO_ROOT / "01_참가자_배포용" / "04_원본데이터")
)

# 기한 전 조기경고 시작 일수. 가정(원본에 없음): 기한 5일 전부터 미승인이면 조기경고.
EARLY_WARNING_DAYS = 5

# 2차 집행 전 1차 반품 관찰 기간(일).
RETURN_OBSERVE_DAYS = 28
# 자동 보류 기준의 z 값(한쪽 95%).
STOP_Z = 1.645
