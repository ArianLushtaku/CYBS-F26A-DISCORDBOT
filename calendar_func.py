

from collections import defaultdict
from typing import Optional
from icalendar import Calendar
import requests
from helper_functions import _format_danish_date, admin_only, get_guild_state
from pinned_message import _update_pinned_calendar_messages
from utils import CALENDAR_URL, EXCLUDED_GUILD_IDS
from bot_event import bot
import discord
from datetime import timedelta, timezone, datetime
import re
from discord import app_commands
from discord.ext import tasks


async def poll_calendar(max_days_ahead: int = 21):
    for guild in bot.guilds:
        if guild.id in EXCLUDED_GUILD_IDS:
            continue
        print(f"Updating calendar for guild: {guild.name} ({guild.id})")

        merged_events = parse_calendar(max_days_ahead=max_days_ahead)

        def _event_start(e: discord.ScheduledEvent):
            return getattr(e, "scheduled_start_time", None) or getattr(e, "start_time", None)

        def _event_end(e: discord.ScheduledEvent):
            return getattr(e, "scheduled_end_time", None) or getattr(e, "end_time", None)

        def _event_location(e: discord.ScheduledEvent) -> str:
            loc = getattr(e, "location", None)
            if isinstance(loc, str) and loc:
                return loc
            meta = getattr(e, "entity_metadata", None)
            if meta is not None:
                meta_loc = getattr(meta, "location", None)
                if isinstance(meta_loc, str) and meta_loc:
                    return meta_loc
            return ""

        def _norm_loc(s: str) -> str:
            return (s or "N/A").strip()

        def _norm_name(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "")).strip()

        def _norm_dt(dt: Optional[datetime]) -> Optional[datetime]:
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
            return dt.replace(second=0, microsecond=0)

        def _make_key(name: str, start_dt: datetime, location: str) -> str:
            loc = _norm_loc(location)
            # Key by date (not exact datetime) so time updates result in edit, not delete+create.
            return f"{_norm_name(name)}_{start_dt.date().isoformat()}_{loc}"

        desired = {}
        for course, date, location, start, end in merged_events:
            desired[_make_key(course, start, location)] = {
                "name": _norm_name(course),
                "start": start,
                "end": end,
                "location": location,
            }

        # Fetch existing scheduled events from Discord
        existing_events = await guild.fetch_scheduled_events()

        # Build key -> events map from Discord
        discord_by_key = defaultdict(list)
        for e in existing_events:
            print('Processing event:', e.name)
            start = _event_start(e)
            if start is None:
                continue
            loc = _event_location(e)
            key = _make_key(_norm_name(e.name), start, loc)
            discord_by_key[key].append(e)

        # Deduplicate Discord side for keys (keep oldest bot-created if possible)
        for key, events_list in list(discord_by_key.items()):
            print('Processing key:', key)
            if len(events_list) <= 1:
                continue

            events_list.sort(key=lambda ev: ev.id)
            keep = events_list[0]
            if bot.user is not None:
                for ev in events_list:
                    print('Checking event:', ev.name)
                    creator_id = getattr(ev, "creator_id", None)
                    if creator_id is not None and int(creator_id) == int(bot.user.id):
                        keep = ev
                        break

            for dup in events_list:
                print('Deleting duplicate event:', dup.name)
                if dup.id == keep.id:
                    continue
                creator_id = getattr(dup, "creator_id", None)
                if bot.user is None or creator_id is None or int(creator_id) != int(bot.user.id):
                    continue
                try:
                    await dup.delete()
                except Exception:
                    pass

            discord_by_key[key] = [keep]

        # Upsert desired events (do not create anything until after existing events are indexed)
        for key, d in desired.items():
            existing = discord_by_key.get(key)
            if existing:
                ev = existing[0]
                ev_start = _norm_dt(_event_start(ev))
                ev_end = _norm_dt(_event_end(ev))
                ev_loc = _norm_loc(_event_location(ev))
                d_start = _norm_dt(d["start"])
                d_end = _norm_dt(d["end"])
                d_loc = _norm_loc(d["location"])

                if ev.name != d["name"] or ev_start != d_start or ev_end != d_end or ev_loc != d_loc:
                    print('Updating event:', ev.name)
                    await ev.edit(
                        name=d["name"],
                        start_time=d["start"],
                        end_time=d["end"],
                        location=d["location"],
                    )
            else:
                print('Creating event:', d["name"])
                await guild.create_scheduled_event(
                    name=d["name"],
                    start_time=d["start"],
                    end_time=d["end"],
                    location=d["location"],
                    entity_type=discord.EntityType.external,
                    privacy_level=discord.PrivacyLevel.guild_only,
                )

        # Optionally delete Discord events that are no longer in the calendar.
        # Safety: only delete events created by this bot.
        for key, events_list in discord_by_key.items():
            if key in desired:
                continue
            ev = events_list[0]
            creator_id = getattr(ev, "creator_id", None)
            if bot.user is None or creator_id is None or int(creator_id) != int(bot.user.id):
                continue
            try:
                print('Deleting event:', ev.name)
                await ev.delete()
            except Exception:
                pass

        channel = await _get_calendar_channel(guild)
        if channel is None:
            print(f"Skipping guild {guild.id}: not set up yet")
            continue

        await _update_pinned_calendar_messages(guild, channel, merged_events)
        print('Updated pinned calendar messages')

def parse_calendar(max_days_ahead=21):
    """Fetch ICS, parse events, merge overlapping, and return list of merged events."""
    resp = requests.get(CALENDAR_URL)
    cal = Calendar.from_ical(resp.content)
    now = datetime.now(timezone.utc)
    max_date = now + timedelta(days=max_days_ahead)

    events_per_day = defaultdict(list)

    for component in cal.walk("VEVENT"):
        summary = str(component.get("summary"))
        uid = str(component.get("uid"))

        if "CYBS" not in summary and uid != "143983--425817795-0@timeedit.com":
            continue

        cleaned_summary = re.sub(
            r'[^A-åa-å0-9 ]',
            '',
            summary.replace("CYBS-GBG-F26A", "").replace("CYBS-GBG-F26B", "").strip()
        )
        cleaned_summary = re.sub(r"\s+", " ", cleaned_summary).strip()

        start = component.get("dtstart").dt
        end = component.get("dtend").dt
        location = str(component.get("location")).replace("GBG.", "") if component.get("location") else "N/A"

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        if end < now or start > max_date:
            continue

        key = (cleaned_summary, start.date(), location)
        events_per_day[key].append((start, end))

    # Merge overlapping/adjacent events
    merged_events = []
    for (course, date, location), slots in events_per_day.items():
        earliest_start = min(s[0] for s in slots)
        latest_end = max(s[1] for s in slots)
        merged_events.append((course, date, location, earliest_start, latest_end))

    return merged_events



async def delete_calender():
    for guild in bot.guilds:
        print(f"Processing guild: {guild.name} ({guild.id})")
        events = await guild.fetch_scheduled_events()
        print(f"Found {len(events)} events")

        for e in events:
            await e.delete()
            print(f"Deleted event: {e.name}")

    print("All events deleted.")

async def _get_calendar_channel(guild: discord.Guild) -> Optional[discord.abc.Messageable]:
    state = await get_guild_state(guild.id)
    channel_id = state.get("calendar_channel_id")

    if not channel_id:
        return None
    
    ch = guild.get_channel(int(channel_id))
    if ch is None:
        return None
    
    if not ch.permissions_for(guild.me).send_messages:
        return None

    return ch



@bot.tree.command(name="deletecalendar", description="Slet alle Discord scheduled events som botten har oprettet")
@admin_only()
async def deletecalendar(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await delete_calender()
    await interaction.followup.send("Alle events slettet.")

@bot.tree.command(name="sync", description="Tving en kalendersync nu")
@admin_only()
async def sync(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await poll_calendar()
    await interaction.followup.send("Sync færdig.")

@tasks.loop(hours=1.5)
async def sync_calendar_loop():
    print('1.5 Hour poll.')
    await poll_calendar()
