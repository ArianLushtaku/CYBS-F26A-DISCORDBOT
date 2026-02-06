import discord
from discord import app_commands
from discord.ext import commands, tasks
from icalendar import Calendar
from dotenv import load_dotenv
import os
import requests
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from fastapi import FastAPI
import json
from pathlib import Path
from typing import Optional


app = FastAPI()


load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CALENDAR_URL = os.getenv("CALENDER_URL")

STATE_FILE = Path("state.json")

intents = discord.Intents.default()
intents.message_content = False
bot = commands.Bot(command_prefix="!", intents=intents)

event_mapping = {}

_synced = False

DANISH_WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
DANISH_MONTHS = [
    "januar",
    "februar",
    "marts",
    "april",
    "maj",
    "juni",
    "juli",
    "august",
    "september",
    "oktober",
    "november",
    "december",
]


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _prune_state(state: dict) -> dict:
    allowed = {
        "calendar_channel_ids",
        "weekly_message_ids",
        "daily_message_ids",
    }
    return {k: v for k, v in state.items() if k in allowed}


def _parse_channel_id(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _format_danish_date(d: datetime.date) -> str:
    weekday = DANISH_WEEKDAYS[d.weekday()]
    month = DANISH_MONTHS[d.month - 1]
    return f"{weekday}, {d.day}. {month} {d.year}"


def _build_range_embed(merged_events, start_date, days: int, title: str, description: str) -> discord.Embed:
    end_date = start_date + timedelta(days=days - 1)

    events_in_range = [e for e in merged_events if start_date <= e[1] <= end_date]
    events_by_date = defaultdict(list)
    for course, date, location, start, end in events_in_range:
        events_by_date[date].append((course, location, start, end))

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blue(),
    )

    if not events_in_range:
        embed.add_field(name="Ingen events", value="Der er ingen planlagte events i perioden.", inline=False)
        return embed

    separator = "-------------------------------------------"
    sections = []
    for i in range(days):
        day = start_date + timedelta(days=i)
        day_events = events_by_date.get(day, [])
        if not day_events:
            continue

        day_events.sort(key=lambda x: x[2])
        lines = [f"__**{_format_danish_date(day)}**__"]
        for idx, (course, location, start, end) in enumerate(day_events):
            start_str = start.strftime("%H:%M")
            end_str = end.strftime("%H:%M")
            if start.date() != end.date() or (start_str == "00:00" and end_str == "00:00"):
                time_part = "Hele dagen"
            else:
                time_part = f"{start_str} - {end_str}"

            loc_value = location if location else "N/A"
            if idx != 0:
                lines.append("")
            lines.append(f"**{course}**")
            lines.append(f"Tid: {time_part}")
            lines.append(f"Lokale: {loc_value}")

        sections.append("\n".join(lines))

    embed.description = f"\n{separator}\n".join(sections)
    return embed


def _build_week_embed(merged_events, week: Optional[int] = None, year: Optional[int] = None) -> discord.Embed:
    today = datetime.now(timezone.utc).date()

    if week is not None:
        y = year if year is not None else today.isocalendar().year
        try:
            start_of_week = datetime.fromisocalendar(y, int(week), 1).date()
        except Exception:
            start_of_week = today - timedelta(days=today.weekday())
    else:
        start_of_week = today - timedelta(days=today.weekday())

        # If current week has no events, jump to the next week that has events.
        this_week_has_events = any(start_of_week <= e[1] <= (start_of_week + timedelta(days=6)) for e in merged_events)
        if not this_week_has_events:
            future_dates = [e[1] for e in merged_events if e[1] >= today]
            if future_dates:
                next_date = min(future_dates)
                start_of_week = next_date - timedelta(days=next_date.weekday())

    iso = start_of_week.isocalendar()
    week_num = iso.week
    week_year = iso.year
    title = f"📅 Discord Kalender, Uge: {week_num}"
    description = f"Uge {week_num} ({week_year}) (mandag–søndag)"
    return _build_range_embed(merged_events, start_of_week, 7, title, description)


def _build_year_embeds(merged_events, year: int) -> list[discord.Embed]:
    year_events = [e for e in merged_events if e[1].year == year]
    embeds: list[discord.Embed] = []

    if not year_events:
        embeds.append(
            discord.Embed(
                title="📅 Discord Kalender",
                description=f"Ingen events fundet for {year}.",
                color=discord.Color.blue(),
            )
        )
        return embeds

    # Group by ISO week
    by_week = defaultdict(list)
    for course, date, location, start, end in year_events:
        iso = date.isocalendar()
        by_week[(iso.year, iso.week)].append((course, location, start, end, date))

    week_keys = sorted(by_week.keys())
    per_embed = 10
    for i in range(0, len(week_keys), per_embed):
        chunk = week_keys[i : i + per_embed]
        embed = discord.Embed(
            title="📅 Discord Kalender",
            description=f"Skema for {year} (oversigt pr. uge)",
            color=discord.Color.blue(),
        )

        for (iso_year, iso_week) in chunk:
            items = by_week[(iso_year, iso_week)]
            items.sort(key=lambda x: x[2])
            # week range (Mon-Sun)
            start_of_week = datetime.fromisocalendar(iso_year, iso_week, 1).date()
            end_of_week = start_of_week + timedelta(days=6)
            header = f"Uge {iso_week} ({_format_danish_date(start_of_week)} - {_format_danish_date(end_of_week)})"

            lines = []
            for course, location, start, end, date in items:
                start_str = start.strftime("%H:%M")
                end_str = end.strftime("%H:%M")
                time_part = (
                    "Hele dagen"
                    if (start.date() != end.date() or (start_str == "00:00" and end_str == "00:00"))
                    else f"{start_str}-{end_str}"
                )
                loc_value = location if location else "N/A"
                lines.append(f"{date.strftime('%d/%m')}: {course} ({time_part}, {loc_value})")

            value = "\n".join(lines)
            if len(value) > 1024:
                value = value[:1021] + "..."
            embed.add_field(name=header, value=value, inline=False)

        embeds.append(embed)

    return embeds


def _build_daily_embed(merged_events) -> discord.Embed:
    today = datetime.now(timezone.utc).date()
    events_today = [e for e in merged_events if e[1] == today]

    if events_today:
        embed_title = f"📅 Skema idag ({_format_danish_date(today)})"
        embed_color = discord.Color.blue()
        events = events_today
    else:
        future_events = [e for e in merged_events if e[1] >= today]
        if not future_events:
            return discord.Embed(
                title="📅 Skema",
                description="Ingen skemalagte planer fundet!",
                color=discord.Color.orange(),
            )
        next_date = min(e[1] for e in future_events)
        events = [e for e in future_events if e[1] == next_date]
        embed_title = f"📅 Næste planlagte modul ({_format_danish_date(next_date)})"
        embed_color = discord.Color.orange()

    embed = discord.Embed(title=embed_title, color=embed_color)
    parts = []
    for course, date, location, start, end in events:
        parts.append(
            "\n".join(
                [
                    f"**{course}**",
                    f"Tid: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}",
                    f"Lokale: {location if location else 'N/A'}",
                ]
            )
        )
    embed.description = "\n\n--------\n\n".join(parts)
    return embed


async def _ensure_pinned_message(channel: discord.abc.Messageable, message_id: Optional[int], embed: discord.Embed):
    msg = None
    if message_id:
        try:
            msg = await channel.fetch_message(int(message_id))
        except discord.NotFound:
            msg = None

    if msg is None:
        msg = await channel.send(embed=embed)
    else:
        await msg.edit(embed=embed)

    try:
        if not msg.pinned:
            await msg.pin(reason="Kalenderbesked")
    except Exception:
        pass

    return msg.id


async def _update_pinned_calendar_messages(guild: discord.Guild, channel: discord.abc.Messageable, merged_events):
    state = _prune_state(_load_state())
    weekly_ids = state.get("weekly_message_ids", {})
    daily_ids = state.get("daily_message_ids", {})
    guild_key = str(guild.id)

    weekly_embed = _build_week_embed(merged_events)
    daily_embed = _build_daily_embed(merged_events)

    weekly_id = weekly_ids.get(guild_key)
    daily_id = daily_ids.get(guild_key)

    weekly_ids[guild_key] = await _ensure_pinned_message(channel, weekly_id, weekly_embed)
    daily_ids[guild_key] = await _ensure_pinned_message(channel, daily_id, daily_embed)

    state["weekly_message_ids"] = weekly_ids
    state["daily_message_ids"] = daily_ids
    _save_state(_prune_state(state))

    return None


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

@bot.event
async def on_ready():
    global _synced
    print(f"Logged in as {bot.user}")

    _save_state(_prune_state(_load_state()))
    if not _synced:
        await bot.tree.sync()
        print("Synced commands globally")
        _synced = True

    try:
        cmds = [c.qualified_name for c in bot.tree.get_commands()]
        print(f"Registered app commands: {cmds}")
    except Exception:
        pass
    if not sync_calendar_loop.is_running():
        sync_calendar_loop.start()
        
@bot.event
async def on_message(message: discord.Message):
    # Check if the message is a system message about pinning
    if message.type == discord.MessageType.pins_add and message.author == message.guild.me:
        # Get the calendar channel for this guild
        channel = await _get_calendar_channel(message.guild)
        if channel and message.channel.id == channel.id:
            try:
                await message.delete()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print(f"Missing permissions to delete messages in {channel.name}")
            except Exception as e:
                print(f"Error deleting pin notification: {e}")
    
    # Don't forget to process commands if you have any message commands
    await bot.process_commands(message)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"App command error: {type(error).__name__}: {error}")


async def _get_calendar_channel(guild: discord.Guild) -> Optional[discord.abc.Messageable]:
    state = _load_state()
    per_guild = state.get("calendar_channel_ids", {})
    saved_id = per_guild.get(str(guild.id))
    if saved_id is not None:
        ch = guild.get_channel(int(saved_id))
        if ch is not None:
            return ch

    channel_id = _parse_channel_id(CALENDAR_CHANNEL_ID)
    if channel_id is not None:
        ch = guild.get_channel(channel_id)
        if ch is not None:
            return ch
    if guild.system_channel is not None:
        return guild.system_channel
    for ch in guild.text_channels:
        perms = ch.permissions_for(guild.me)
        if perms.send_messages:
            return ch
    return None

async def poll_calendar(max_days_ahead: int = 21):
    for guild in bot.guilds:
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
            continue

        await _update_pinned_calendar_messages(guild, channel, merged_events)
        print('Updated pinned calendar messages')

async def delete_calender():
    for guild in bot.guilds:
        print(f"Processing guild: {guild.name} ({guild.id})")
        events = await guild.fetch_scheduled_events()
        print(f"Found {len(events)} events")

        for e in events:
            await e.delete()
            print(f"Deleted event: {e.name}")

    print("All events deleted.")


@bot.tree.command(name="setup", description="Vælg hvilken kanal kalenderen postes i")
@app_commands.describe(channel="Tekstkanalen hvor ugekalenderen skal opdateres")
async def setup(interaction: discord.Interaction, channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Denne kommando kan kun bruges i en server.", ephemeral=True)
        return

    perms = channel.permissions_for(interaction.guild.me)
    if not perms.send_messages:
        await interaction.response.send_message("Jeg har ikke rettighed til at sende beskeder i den kanal.", ephemeral=True)
        return

    state = _prune_state(_load_state())
    per_guild = state.get("calendar_channel_ids", {})
    per_guild[str(interaction.guild.id)] = channel.id
    state["calendar_channel_ids"] = per_guild

    # Reset message ids when changing channel so new pinned messages are created in the correct place.
    guild_key = str(interaction.guild.id)
    weekly = state.get("weekly_message_ids", {})
    daily = state.get("daily_message_ids", {})
    weekly.pop(guild_key, None)
    daily.pop(guild_key, None)
    state["weekly_message_ids"] = weekly
    state["daily_message_ids"] = daily

    _save_state(_prune_state(state))

    merged_events = parse_calendar(max_days_ahead=800)
    await _update_pinned_calendar_messages(interaction.guild, channel, merged_events)

    await interaction.response.send_message(f"Kalenderkanal sat til {channel.mention}.", ephemeral=True)


@bot.tree.command(name="uge", description="Vis ugekalenderen (mandag–søndag)")
@app_commands.describe(uge="ISO-ugenummer (1-53)", år="År (valgfrit, standard er indeværende ISO-år)")
async def uge(interaction: discord.Interaction, uge: Optional[int] = None, år: Optional[int] = None):
    merged_events = parse_calendar(max_days_ahead=800)
    if uge is not None and (uge < 1 or uge > 53):
        await interaction.response.send_message("Ugenummer skal være mellem 1 og 53.", ephemeral=True)
        return
    if år is not None and (år < 2000 or år > 2100):
        await interaction.response.send_message("År skal være mellem 2000 og 2100.", ephemeral=True)
        return

    if uge is None and år is not None:
        embeds = _build_year_embeds(merged_events, year=år)
        await interaction.response.send_message(embed=embeds[0], ephemeral=True)
        for e in embeds[1:]:
            await interaction.followup.send(embed=e, ephemeral=True)
        return

    embed = _build_week_embed(merged_events, week=uge, year=år)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="skema", description="Vis dagens skema eller næste planlagte modul")
@app_commands.choices(
    vis=[
        app_commands.Choice(name="I dag", value="today"),
        app_commands.Choice(name="Næste", value="next"),
    ]
)
async def skema(
    interaction: discord.Interaction,
    vis: Optional[app_commands.Choice[str]] = None,
):
    merged_events = parse_calendar()
    today = datetime.now(timezone.utc).date()

    mode = (vis.value if vis is not None else "today")
    events_today = [e for e in merged_events if e[1] == today]

    if mode == "next" or not events_today:
        future_events = [e for e in merged_events if e[1] >= today]
        if not future_events:
            await interaction.response.send_message("Ingen skemalagte planer fundet!")
            return

        next_date = min(e[1] for e in future_events)
        events_today = [e for e in future_events if e[1] == next_date]
        embed_title = f"📅 Næste planlagte modul ({_format_danish_date(next_date)})"
        embed_color = discord.Color.orange()
    else:
        embed_title = f"📅 Skema idag ({_format_danish_date(today)})"
        embed_color = discord.Color.blue()

    embed = discord.Embed(title=embed_title, color=embed_color)
    parts = []
    for course, date, location, start, end in events_today:
        parts.append(
            "\n".join(
                [
                    f"**{course}**",
                    f"Tid: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}",
                    f"Lokale: {location if location else 'N/A'}",
                ]
            )
        )

    embed.description = "\n\n--------\n\n".join(parts)
    await interaction.response.send_message(embed=embed, ephemeral=True)


broadcast_group = app_commands.Group(name="broadcast", description="Send kalenderbeskeder offentligt i kanalen")


@broadcast_group.command(name="uge", description="Broadcast en ugekalender til serveren")
@app_commands.describe(uge="ISO-ugenummer (1-53)", år="År (valgfrit)", everyone="Nævn @everyone")
async def broadcast_uge(
    interaction: discord.Interaction,
    uge: Optional[int] = None,
    år: Optional[int] = None,
    everyone: Optional[bool] = False,
):
    if interaction.guild is None:
        await interaction.response.send_message("Denne kommando kan kun bruges i en server.", ephemeral=True)
        return

    if uge is not None and (uge < 1 or uge > 53):
        await interaction.response.send_message("Ugenummer skal være mellem 1 og 53.", ephemeral=True)
        return
    if år is not None and (år < 2000 or år > 2100):
        await interaction.response.send_message("År skal være mellem 2000 og 2100.", ephemeral=True)
        return

    channel = await _get_calendar_channel(interaction.guild)
    if channel is None:
        await interaction.response.send_message("Kunne ikke finde en kanal at sende i. Kør /setup først.", ephemeral=True)
        return

    merged_events = parse_calendar(max_days_ahead=800)
    content = "@everyone" if everyone else None

    # If only year is provided, broadcast the year overview.
    if uge is None and år is not None:
        embeds = _build_year_embeds(merged_events, year=år)
        await interaction.response.send_message("Broadcast sender...", ephemeral=True)
        first = True
        for e in embeds:
            if first:
                await channel.send(content=content, embed=e)
                first = False
            else:
                await channel.send(embed=e)
        return

    embed = _build_week_embed(merged_events, week=uge, year=år)
    await channel.send(content=content, embed=embed)
    await interaction.response.send_message("Broadcast sendt.", ephemeral=True)


@broadcast_group.command(name="skema", description="Broadcast dagens/næste skema til serveren")
@app_commands.choices(
    vis=[
        app_commands.Choice(name="I dag", value="today"),
        app_commands.Choice(name="Næste", value="next"),
    ]
)
@app_commands.describe(everyone="Nævn @everyone")
async def broadcast_skema(
    interaction: discord.Interaction,
    vis: Optional[app_commands.Choice[str]] = None,
    everyone: Optional[bool] = False,
):
    if interaction.guild is None:
        await interaction.response.send_message("Denne kommando kan kun bruges i en server.", ephemeral=True)
        return

    channel = await _get_calendar_channel(interaction.guild)
    if channel is None:
        await interaction.response.send_message("Kunne ikke finde en kanal at sende i. Kør /setup først.", ephemeral=True)
        return

    merged_events = parse_calendar(max_days_ahead=800)
    today = datetime.now(timezone.utc).date()
    mode = (vis.value if vis is not None else "today")
    events_today = [e for e in merged_events if e[1] == today]

    if mode == "next" or not events_today:
        future_events = [e for e in merged_events if e[1] >= today]
        if not future_events:
            await interaction.response.send_message("Ingen skemalagte planer fundet!", ephemeral=True)
            return

        next_date = min(e[1] for e in future_events)
        events_today = [e for e in future_events if e[1] == next_date]
        embed_title = f"📅 Næste planlagte modul ({_format_danish_date(next_date)})"
        embed_color = discord.Color.orange()
    else:
        embed_title = f"📅 Skema idag ({_format_danish_date(today)})"
        embed_color = discord.Color.blue()

    embed = discord.Embed(title=embed_title, color=embed_color)
    parts = []
    for course, date, location, start, end in events_today:
        parts.append(
            "\n".join(
                [
                    f"**{course}**",
                    f"Tid: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}",
                    f"Lokale: {location if location else 'N/A'}",
                ]
            )
        )
    embed.description = "\n\n--------\n\n".join(parts)

    content = "@everyone" if everyone else None
    await channel.send(content=content, embed=embed)
    await interaction.response.send_message("Broadcast sendt.", ephemeral=True)


@bot.tree.command(name="sync", description="Tving en kalendersync nu")
async def sync(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await poll_calendar()
    await interaction.followup.send("Sync færdig.")


@bot.tree.command(name="deletecalendar", description="Slet alle Discord scheduled events som botten har oprettet")
async def deletecalendar(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await delete_calender()
    await interaction.followup.send("Alle events slettet.")


bot.tree.add_command(broadcast_group)

@tasks.loop(hours=1.5)
async def sync_calendar_loop():
    print('1.5 Hour poll.')
    await poll_calendar()

@app.get("/")
async def root():
    return {"status": "ok"}

@app.head("/")
def head():
    return "", 200

# At the bottom of your main.py, replace the current code with:
if __name__ == "__main__":
    import uvicorn
    import threading

    # Start FastAPI in a separate thread
    def run_fastapi():
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

    fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
    fastapi_thread.start()

    # Start the Discord bot in the main thread
    bot.run(DISCORD_TOKEN)
