from __future__ import annotations

import unittest

from backend.database.engine import sqlite_pragmas


class TestSqlitePragmas(unittest.TestCase):
    def test_sqlite_pragmas_include_wal_write_optimizations(self) -> None:
        pragmas = set(sqlite_pragmas())

        self.assertIn("PRAGMA journal_mode=WAL;", pragmas)
        self.assertIn("PRAGMA foreign_keys=ON;", pragmas)
        self.assertIn("PRAGMA synchronous=NORMAL;", pragmas)
        self.assertIn("PRAGMA temp_store=MEMORY;", pragmas)
        self.assertIn("PRAGMA cache_size=-32000;", pragmas)
        self.assertIn("PRAGMA mmap_size=268435456;", pragmas)
        self.assertTrue(any(item.startswith("PRAGMA busy_timeout=") for item in pragmas))

