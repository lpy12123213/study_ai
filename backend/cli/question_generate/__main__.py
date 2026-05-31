"""Module entry point so ``python -m backend.cli.question_generate`` works.

Mirrors the original ``if __name__ == "__main__": main()`` block from the
pre-split monolithic module.
"""

from __future__ import annotations

from .app import main

if __name__ == "__main__":
    main()
