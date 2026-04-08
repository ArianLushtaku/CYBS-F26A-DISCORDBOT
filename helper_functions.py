from utils import *
import discord
from discord import app_commands
import datetime

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


def _format_danish_date(d: datetime.date) -> str:
    weekday = DANISH_WEEKDAYS[d.weekday()]
    month = DANISH_MONTHS[d.month - 1]
    return f"{weekday}, {d.day}. {month} {d.year}"

def admin_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        # Check if interaction is in a guild context
        if not interaction.guild:
            await interaction.response.send_message(
                "Denne kommando kan kun bruges i en server.", ephemeral=True
            )
            return False

        # Get member - interaction.user might be User or Member
        if isinstance(interaction.user, discord.Member):
            member = interaction.user
        else:
            # Fetch member if interaction.user is a User object
            member = interaction.guild.get_member(interaction.user.id)
            if not member:
                try:
                    member = await interaction.guild.fetch_member(interaction.user.id)
                except Exception:
                    await interaction.response.send_message(
                        "Kunne ikke finde medlem i serveren.", ephemeral=True
                    )
                    return False

        # Check administrator permission
        if member.guild_permissions.administrator:
            return True

        await interaction.response.send_message(
            "Du skal være administrator for at bruge denne kommando.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)

async def get_guild_state(guild_id: int) -> dict:
    doc = await guild_state_col.find_one({"guild_id": str(guild_id)})
    return doc or {"guild_id": str(guild_id)}

async def set_guild_state(guild_id: int, updates: dict) -> None:
    await guild_state_col.update_one(
        {"guild_id": str(guild_id)},
        {"$set": updates},
        upsert=True,
    )
