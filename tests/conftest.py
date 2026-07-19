import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def tmp_workdir():
    d = tempfile.mkdtemp(prefix="continuum-test-")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)
