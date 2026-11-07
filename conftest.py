"""Project-level pytest bootstrap.

The project uses a flat ``src/`` and ``analysis/`` layout (no installed package),
so this file makes the project root importable no matter which directory pytest
is invoked from.  It contains no fixtures and no test logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))