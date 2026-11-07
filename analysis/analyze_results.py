"""Compatibility entry point for the completed experiment analysis layer.

The authoritative implementation is :mod:`analysis.evaluate_experiment`.
"""

from analysis.evaluate_experiment import main

__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
