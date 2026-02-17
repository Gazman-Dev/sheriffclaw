import sys
from pathlib import Path

# Add the repository root to sys.path so we can import 'services' and 'shared'
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))