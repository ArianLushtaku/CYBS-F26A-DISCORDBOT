from collections import defaultdict
from datetime import timedelta, timezone, datetime
import discord
from helper_functions import _format_danish_date, get_guild_state, set_guild_state
from typing import Optional
from utils import EXCLUDED_GUILD_IDS

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


async def _update_pinned_calendar_messages(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    merged_events,
) -> None:
    # Load per-guild state from MongoDB
    state = await get_guild_state(guild.id)
    if guild.id in EXCLUDED_GUILD_IDS:
        return

    weekly_message_id = state.get("weekly_message_id")
    daily_message_id = state.get("daily_message_id")

    # Build embeds
    weekly_embed = _build_week_embed(merged_events)
    daily_embed = _build_daily_embed(merged_events)

    # Ensure pinned messages exist / are updated
    weekly_message_id = await _ensure_pinned_message(
        channel,
        weekly_message_id,
        weekly_embed,
    )

    daily_message_id = await _ensure_pinned_message(
        channel,
        daily_message_id,
        daily_embed,
    )

    # Persist updated message IDs
    await set_guild_state(
        guild.id,
        {
            "weekly_message_id": weekly_message_id,
            "daily_message_id": daily_message_id,
        },
    )


