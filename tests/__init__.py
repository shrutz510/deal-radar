"""Test setup: make src/ importable and point the app at a throwaway database before anything imports it."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["DEAL_RADAR_DB"] = str(Path(tempfile.mkdtemp(prefix="dealradar-test-")) / "test.db")
