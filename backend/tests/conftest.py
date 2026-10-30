import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("FINN_DATA_DIR", tempfile.mkdtemp(prefix="finn-test-"))
os.environ["FINN_FIXTURE_MODE"] = "1"
os.environ["FINN_LLM_PROVIDER"] = "none"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
