"""Tests for helper_functions._format_danish_date.

We must mock out utils (which connects to MongoDB) before importing helper_functions.
"""
import sys
import types
import unittest
from datetime import date
from unittest.mock import MagicMock


def _build_utils_mock():
    """Return a minimal mock of the utils module."""
    mock = types.ModuleType("utils")
    mock.bot = MagicMock()
    mock.app = MagicMock()
    mock.db = MagicMock()
    mock.guild_state_col = MagicMock()
    mock.EXCLUDED_GUILD_IDS = ""
    mock.DISCORD_TOKEN = None
    mock.CALENDAR_URL = None
    mock.MONGODB_URI = None
    mock.mongo = MagicMock()
    return mock


# Patch utils into sys.modules before importing helper_functions.
# We overwrite unconditionally so that even if a prior test installed a mock
# utils, we get one that exposes the right attributes.
sys.modules["utils"] = _build_utils_mock()

# Evict a previously cached (possibly mocked) helper_functions so we load the
# real module from disk.
sys.modules.pop("helper_functions", None)

import helper_functions  # noqa: E402 – must come after sys.modules patch
from helper_functions import _format_danish_date  # noqa: E402


class TestFormatDanishDate(unittest.TestCase):

    def test_monday_5_january_2026(self):
        d = date(2026, 1, 5)
        result = _format_danish_date(d)
        self.assertEqual(result, "mandag, 5. januar 2026")

    def test_sunday_28_december_2025(self):
        d = date(2025, 12, 28)
        result = _format_danish_date(d)
        self.assertEqual(result, "søndag, 28. december 2025")

    def test_wednesday_1_april_2026(self):
        d = date(2026, 4, 1)
        result = _format_danish_date(d)
        self.assertEqual(result, "onsdag, 1. april 2026")


if __name__ == "__main__":
    unittest.main()
