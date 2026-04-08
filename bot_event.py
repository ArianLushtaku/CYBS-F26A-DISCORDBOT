import discord
from discord import app_commands
from utils import *
from calendar_func import sync_calendar_loop

_synced = False


@bot.event
async def on_message(message):
    # Ignore messages from bots
    if message.author.bot:
        return

    if message.type == discord.MessageType.pins_add:
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        return

    if not isinstance(message.channel, discord.DMChannel):
        await bot.process_commands(message)


@bot.event
async def on_ready():
    global _synced
    print(f"Logged in as {bot.user}")

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


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"App command error: {type(error).__name__}: {error}")
