from __future__ import annotations

# When running `python -m unittest discover -s backend/tests ...`, test modules are
# imported as top-level modules (not as `backend.tests.*`). Importing the package
# here ensures our test-environment bootstrap (temp dir + sandbox workarounds)
# is applied consistently for the entire test process.
import backend.tests  # noqa: F401

