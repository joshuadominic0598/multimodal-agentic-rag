"""Source-checkout and installed-wheel resource locations."""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ROOT = next(
    (
        parent
        for parent in PACKAGE_ROOT.parents
        if (parent / "pyproject.toml").is_file() and (parent / "frontend").is_dir()
    ),
    Path.cwd(),
)
SHARED_DIR = Path(sys.prefix) / "share/agentic-rag"
FRONTEND_DIR = ROOT / "frontend" if (ROOT / "frontend").is_dir() else SHARED_DIR / "frontend"
EXAMPLES_DIR = (
    ROOT / "docs/examples" if (ROOT / "docs/examples").is_dir() else SHARED_DIR / "examples"
)
