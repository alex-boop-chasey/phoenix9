"""The built web app must use relative asset paths so it works under /proxy/<port>/."""
import re
from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def test_dist_assets_relative():
    """Every src/href in web/dist/index.html starts with ./ (skipped when not built)."""
    index = DIST / "index.html"
    if not index.exists():
        pytest.skip("web/dist not built")
    urls = re.findall(r'(?:src|href)="([^"]+)"', index.read_text())
    assets = [u for u in urls if "assets/" in u]
    assert assets
    assert all(u.startswith("./assets/") for u in assets), assets
