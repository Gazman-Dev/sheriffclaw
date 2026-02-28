import sys
import os
import tempfile
from pathlib import Path
import pytest

# Add the repository root to sys.path so we can import 'services' and 'shared'
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("SHERIFFCLAW_ROOT", str((Path(tempfile.gettempdir()) / "sheriffclaw-test-state").resolve()))


@pytest.fixture(autouse=True)
def _enable_debug_mode(monkeypatch):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
