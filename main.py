import discord
from discord.ext import tasks
from icalendar import Calendar
from dotenv import load_dotenv
import os
import requests
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from discord.ext import tasks
from fastapi import FastAPI


load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CALENDAR_URL = os.getenv("CALENDER_URL")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

event_mapping = {}


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

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

async def poll_calendar():
    for guild in client.guilds:
        print(f"Updating calendar for guild: {guild.name} ({guild.id})")
        merged_events = parse_calendar()

        for course, date, location, start, end in merged_events:
            merged_uid = f"{course}_{date}_{location}"
            key = f"{guild.id}_{merged_uid}"
            discord_event_id = event_mapping.get(key)

            if discord_event_id:
                event = discord.utils.get(await guild.fetch_scheduled_events(), id=discord_event_id)
                if event and (event.name != course or event.start != start or event.end != end or event.location != location):
                    await event.edit(name=course, start=start, end=end, location=location)
            else:
                event = await guild.create_scheduled_event(
                    name=course,
                    start_time=start,
                    end_time=end,
                    location=location,
                    entity_type=discord.EntityType.external,
                    privacy_level=discord.PrivacyLevel.guild_only
                )
                event_mapping[key] = event.id

async def delete_calender():
    for guild in client.guilds:
        print(f"Processing guild: {guild.name} ({guild.id})")
        events = await guild.fetch_scheduled_events()
        print(f"Found {len(events)} events")

        for e in events:
            await e.delete()
            print(f"Deleted event: {e.name}")

    print("All events deleted. Exiting.")
    await client.close()

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.lower() == "hej":
        await message.channel.send("HEJSA :) Glad for at høre et hej fra dig!")

    if message.content.startswith("!sync"):
        await message.channel.send("Syncing calendar...")
        await poll_calendar()
    
    if message.content.startswith("!syncTest"):
        await message.channel.send("Syncing calendar test...")
        await poll_calendar(2)

    if message.content.startswith("!deleteCalender"):
        await message.channel.send("Deleting calender...")
        await delete_calender()

    if message.content.startswith("!skema"):
        merged_events = parse_calendar()
        today = datetime.now(timezone.utc).date()

        # Filter today or next available date
        events_today = [e for e in merged_events if e[1] == today]

        if not events_today:
            future_events = [e for e in merged_events if e[1] > today]
            if not future_events:
                await message.channel.send("Ingen skemalagte planer fundet!")
                return

            next_date = min(e[1] for e in future_events)
            events_today = [e for e in future_events if e[1] == next_date]
            embed_title = f"📅 Næste planlagte modul ({next_date})"
            embed_color = discord.Color.orange()
        else:
            embed_title = f"📅 Skema idag({today})"
            embed_color = discord.Color.blue()

        embed = discord.Embed(title=embed_title, color=embed_color)
        for course, date, location, start, end in events_today:
            embed.add_field(
                name=f"**{course}**",
                value=f"```Tid: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}\nLokale: {location}```",
                inline=False
            )

        await message.channel.send(embed=embed)

@tasks.loop(hours=1.5)
async def sync_calendar_loop():
    print('1.5 Hour poll.')
    await poll_calendar()

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok"}

@app.head("/")
def head():
    return "", 200

client.run(DISCORD_TOKEN)
