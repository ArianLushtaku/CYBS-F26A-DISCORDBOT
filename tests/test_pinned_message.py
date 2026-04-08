"""Tests for pinned_message embed builders.

We mock utils and helper_functions before importing pinned_message to avoid
MongoDB connections and Discord bot instantiation.
"""
import sys
import types
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock


def _install_mocks():
    # --- utils mock ---
    utils_mock = types.ModuleType("utils")
    utils_mock.bot = MagicMock()
    utils_mock.app = MagicMock()
    utils_mock.db = MagicMock()
    utils_mock.guild_state_col = MagicMock()
    utils_mock.EXCLUDED_GUILD_IDS = ""
    utils_mock.DISCORD_TOKEN = None
    utils_mock.CALENDAR_URL = None
    utils_mock.MONGODB_URI = None
    utils_mock.mongo = MagicMock()
    sys.modules.setdefault("utils", utils_mock)

    # --- helper_functions mock ---
    hf_mock = types.ModuleType("helper_functions")

    DANISH_WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
    DANISH_MONTHS = [
        "januar", "februar", "marts", "april", "maj", "juni",
        "juli", "august", "september", "oktober", "november", "december",
    ]

    def _format_danish_date(d):
        weekday = DANISH_WEEKDAYS[d.weekday()]
        month = DANISH_MONTHS[d.month - 1]
        return f"{weekday}, {d.day}. {month} {d.year}"

    hf_mock._format_danish_date = _format_danish_date
    hf_mock.get_guild_state = MagicMock()
    hf_mock.set_guild_state = MagicMock()
    hf_mock.admin_only = MagicMock()
    sys.modules.setdefault("helper_functions", hf_mock)


_install_mocks()

# Force-evict any previously mocked pinned_message so we import the real module.
sys.modules.pop("pinned_message", None)

import discord  # noqa: E402 – discord is a real dep, doesn't need a connection
from pinned_message import _build_week_embed, _build_daily_embed  # noqa: E402


def _make_events(days_from_today=0):
    """Return a synthetic merged_events list with one event."""
    from datetime import date as _date, timedelta
    target = _date(2026, 4, 8)  # fixed future date (a Wednesday)
    start_dt = datetime(2026, 4, 8, 8, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    return [("Netværkssikkerhed", target, "Rum101", start_dt, end_dt)]


class TestBuildWeekEmbed(unittest.TestCase):

    def test_returns_embed_instance(self):
        events = _make_events()
        embed = _build_week_embed(events)
        self.assertIsInstance(embed, discord.Embed)

    def test_embed_has_title_attribute(self):
        events = _make_events()
        embed = _build_week_embed(events)
        self.assertTrue(hasattr(embed, "title"))

    def test_title_contains_uge(self):
        events = _make_events()
        embed = _build_week_embed(events)
        self.assertIn("Uge", embed.title)


class TestBuildDailyEmbed(unittest.TestCase):

    def test_no_events_today_returns_naeste_in_title(self):
        # Pass an event in the far future so "today" has nothing
        start_dt = datetime(2030, 1, 6, 8, 0, tzinfo=timezone.utc)
        end_dt = datetime(2030, 1, 6, 12, 0, tzinfo=timezone.utc)
        events = [("Fremtidsfag", date(2030, 1, 6), "Rum999", start_dt, end_dt)]
        embed = _build_daily_embed(events)
        self.assertIsInstance(embed, discord.Embed)
        self.assertIn("Næste", embed.title)

    def test_empty_events_returns_embed(self):
        embed = _build_daily_embed([])
        self.assertIsInstance(embed, discord.Embed)


if __name__ == "__main__":
    unittest.main()
