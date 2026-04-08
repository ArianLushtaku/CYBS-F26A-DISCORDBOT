from typing import Optional
from calendar_func import parse_calendar
from pinned_message import _build_week_embed, _build_year_embeds, _update_pinned_calendar_messages
from utils import *
from helper_functions import _format_danish_date, admin_only, set_guild_state
from discord import app_commands
import discord
from datetime import datetime, timezone


@bot.tree.command(name="setup", description="Vælg hvilken kanal kalenderen postes i")
@admin_only()
@app_commands.describe(channel="Tekstkanalen hvor ugekalenderen skal opdateres")
async def setup(interaction: discord.Interaction, channel: discord.TextChannel):

    if interaction.guild and str(interaction.guild.id) in EXCLUDED_GUILD_IDS:
        await interaction.response.send_message(
            "Denne server er midlertidigt udelukket fra test.",
            ephemeral=True,
        )
        return

    if interaction.guild is None:
        await interaction.response.send_message("Denne kommando kan kun bruges i en server.", ephemeral=True)
        return

    perms = channel.permissions_for(interaction.guild.me)
    if not perms.send_messages:
        await interaction.response.send_message("Jeg har ikke rettighed til at sende beskeder i den kanal.", ephemeral=True)
        return

    await set_guild_state(
        interaction.guild.id,
        {
            "calendar_channel_id": channel.id,
            "weekly_message_id": None,
            "daily_message_id": None,
        },
    )

    merged_events = parse_calendar(max_days_ahead=800)
    await _update_pinned_calendar_messages(interaction.guild, channel, merged_events)

    await interaction.response.send_message(f"Kalenderkanal sat til {channel.mention}.", ephemeral=True)
    print('Setup ran')


@bot.tree.command(name="uge", description="Vis ugekalenderen (mandag–søndag)")
@app_commands.describe(uge="Ugenummer (1-53)", år="År (Standard er indeværende år)")
async def uge(interaction: discord.Interaction, uge: Optional[int] = None, år: Optional[int] = None):
    merged_events = parse_calendar(max_days_ahead=800)
    if uge is not None and (uge < 1 or uge > 53):
        await interaction.response.send_message("Ugenummer skal være mellem 1 og 53.", ephemeral=True)
        return
    if år is not None and (år < 2025 or år > 2030):
        await interaction.response.send_message("År skal være format ex. 2026", ephemeral=True)
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