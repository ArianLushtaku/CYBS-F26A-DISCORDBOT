import discord
from discord.ext import tasks
from icalendar import Calendar
from dotenv import load_dotenv
import os
import requests
import re
from datetime import datetime, timezone

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CALENDAR_URL = os.getenv("CALENDER_URL")

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# Store UID → Discord event ID mapping
event_mapping = {}

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    poll_calendar.start()  # start background task

@tasks.loop(minutes=60)  # poll every hour
async def poll_calendar():
    for guild in client.guilds:  # loop through all connected guilds
        print(f"Updating calendar for guild: {guild.name} ({guild.id})")

        # Fetch calendar
        resp = requests.get(CALENDAR_URL)
        cal = Calendar.from_ical(resp.content)

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

            # Use a composite key with guild ID to separate events per guild
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if start < datetime.now(timezone.utc):
                continue
            key = f"{guild.id}_{uid}"
            discord_event_id = event_mapping.get(key)

            if discord_event_id:
                event = discord.utils.get(await guild.fetch_scheduled_events(), id=discord_event_id)
                if event:
                    if event.name != cleaned_summary or event.start != start or event.end != end or event.location != location:
                        await event.edit(name=cleaned_summary, start=start, end=end, location=location)
            else:
                event = await guild.create_scheduled_event(
                    name=cleaned_summary,
                    start_time=start,
                    end_time=end,
                    location=location,
                    entity_type=discord.EntityType.external,
                    privacy_level=discord.PrivacyLevel.guild_only
                )
                event_mapping[key] = event.id

client.run(DISCORD_TOKEN)
