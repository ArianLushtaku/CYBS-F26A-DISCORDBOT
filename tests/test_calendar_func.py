"""Tests for calendar_func.parse_calendar.

Mocks utils, helper_functions, pinned_message, and bot_event before importing
calendar_func to avoid MongoDB/Discord connections. Also patches requests.get
to serve a local ICS fixture.
"""
import sys
import types
import unittest
from datetime import date
from unittest.mock import MagicMock, patch
import os


def _install_mocks():
    # --- utils mock ---
    utils_mock = types.ModuleType("utils")
    utils_mock.bot = MagicMock()
    utils_mock.app = MagicMock()
    utils_mock.db = MagicMock()
    utils_mock.guild_state_col = MagicMock()
    utils_mock.EXCLUDED_GUILD_IDS = ""
    utils_mock.DISCORD_TOKEN = None
    utils_mock.CALENDAR_URL = "http://fake-calendar-url/calendar.ics"
    utils_mock.MONGODB_URI = None
    utils_mock.mongo = MagicMock()
    sys.modules.setdefault("utils", utils_mock)

    # --- helper_functions mock ---
    hf_mock = types.ModuleType("helper_functions")
    hf_mock._format_danish_date = MagicMock(return_value="onsdag, 8. april 2026")
    hf_mock.get_guild_state = MagicMock()
    hf_mock.set_guild_state = MagicMock()
    hf_mock.admin_only = MagicMock(return_value=lambda f: f)
    sys.modules.setdefault("helper_functions", hf_mock)

    # --- pinned_message mock ---
    pm_mock = types.ModuleType("pinned_message")
    pm_mock._update_pinned_calendar_messages = MagicMock()
    sys.modules.setdefault("pinned_message", pm_mock)

    # --- bot_event mock ---
    be_mock = types.ModuleType("bot_event")
    be_mock.bot = MagicMock()
    sys.modules.setdefault("bot_event", be_mock)


_install_mocks()

# Now we can import calendar_func safely
import calendar_func  # noqa: E402
from calendar_func import parse_calendar  # noqa: E402


# Load ICS fixture bytes once
_FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "sample.ics")
with open(_FIXTURE_PATH, "rb") as _f:
    _ICS_BYTES = _f.read()


class _FakeResponse:
    content = _ICS_BYTES


class TestParseCalendar(unittest.TestCase):

    def _parse(self):
        with patch("calendar_func.CALENDAR_URL", "http://fake/cal.ics"), \
             patch("requests.get", return_value=_FakeResponse()):
            return parse_calendar(max_days_ahead=9999)

    def test_returns_non_empty_list(self):
        events = self._parse()
        self.assertIsInstance(events, list)
        self.assertGreater(len(events), 0)

    def test_course_name_cleaned(self):
        events = self._parse()
        course = events[0][0]
        self.assertNotIn("CYBS-GBG-F26A", course)
        self.assertTrue(len(course) > 0, "Course name should not be empty after cleaning")

    def test_date_is_2027_04_08(self):
        events = self._parse()
        event_date = events[0][1]
        self.assertEqual(event_date, date(2027, 4, 8))

    def test_location_gbg_prefix_stripped(self):
        events = self._parse()
        location = events[0][2]
        self.assertNotIn("GBG.", location)
        self.assertEqual(location, "Rum101")


if __name__ == "__main__":
    unittest.main()
