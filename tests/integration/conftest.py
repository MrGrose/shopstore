import os
import uuid
from pathlib import Path

import pytest

MEDIA_DIR = Path(__file__).resolve().parents[2] / "media" / "products"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MEDIA_ROOT", str(MEDIA_DIR))


@pytest.fixture
def merge_unique_suffix() -> int:
    return int(uuid.uuid4().hex[:7], 16) % 10_000_000
