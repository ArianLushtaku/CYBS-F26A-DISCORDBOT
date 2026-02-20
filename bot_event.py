import asyncio
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands
from utils import *
from calendar_func import sync_calendar_loop
from helper_functions import ensure_verification_channel, search_students_by_name
from verification import create_ttl_index, send_verification, send_verification_email, verify_member
from utils import EXCLUDED_GUILD_IDS, verification_codes
import datetime
import re

_synced = False

async def add_support_ticket(guild: discord.Guild, member: discord.Member):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        )
    }

    channel = await guild.create_text_channel(
        name=f"ticket-{member.name}",
        overwrites=overwrites,
        reason=f"Opretter verifikation for {member.name}"
    )

    try:
        await send_verification(member, channel)
        # Store ticket channel in DB
        await user_verification.update_one(
            {"discord_id": str(member.id)},
            {"$set": {"ticket_channel_id": channel.id}},
            upsert=True
        )
    except Exception as e:
        print(f"Ticket setup failed for {member}: {e}")
        await channel.delete(reason="Verification setup failed")
        return None

    return channel


import discord

async def handle_verification_message(message: discord.Message):
    if message.author.bot:
        return

    record = await user_verification.find_one(
        {"discord_id": str(message.author.id)}
    )
    if not record:
        return

    ticket_channel_id = record.get("ticket_channel_id")
    if not ticket_channel_id or message.channel.id != ticket_channel_id:
        return

    name_input = message.content.strip()
    if not name_input:
        return

    state = record.get("verification_state", "awaiting_name")

    # STATE: Awaiting name input
    if state == "awaiting_name":
        students = await search_students_by_name(name_input)

        if not students:
            await message.channel.send(
                f"{message.author.mention} Ingen studerende fundet. Prøv igen."
            )
            return

        # Single match
        if len(students) == 1:
            student = students[0]
            await message.channel.send(
                f"{message.author.mention} Fundet: **{student['name']}**.\n"
                "Bekræft med `ja` hvis det er korrekt."
            )

            await user_verification.update_one(
                {"discord_id": str(message.author.id)},
                {"$set": {
                    "pending_student": student["_id"],
                    "verification_state": "awaiting_confirmation"
                }}
            )
            return

        # Multiple matches
        await user_verification.update_one(
            {"discord_id": str(message.author.id)},
            {"$set": {
                "verification_state": "awaiting_selection",
                "search_results": [str(s["_id"]) for s in students[:10]],
                "student_names": [s["name"] for s in students[:10]]  # optional for display
            }}
        )

        response = f"{message.author.mention} Flere matches fundet:\n"
        for i, student in enumerate(students[:10], start=1):
            response += f"{i}. {student['name']}\n"
        response += "\nSkriv nummeret på den rigtige."

        await message.channel.send(response)
        return

    # STATE: Awaiting selection (user types a number)
    elif state == "awaiting_selection":
        search_results = record.get("search_results", [])
        student_names = record.get("student_names", [])
        try:
            idx = int(name_input) - 1
            if idx < 0 or idx >= len(search_results):
                await message.channel.send("Ugyldigt nummer. Prøv igen.")
                return
        except ValueError:
            await message.channel.send("Skriv et nummer fra listen.")
            return

        student_id = search_results[idx]
        student_name = student_names[idx]

        await message.channel.send(
            f"{message.author.mention} Du har valgt: **{student_name}**. Bekræft med `ja` hvis korrekt."
        )

        await user_verification.update_one(
            {"discord_id": str(message.author.id)},
            {"$set": {
                "pending_student": student_id,
                "verification_state": "awaiting_confirmation"
            }}
        )
        return

   # STATE: Awaiting confirmation (user types 'ja')
    elif state == "awaiting_confirmation":
        if name_input.lower() in ["ja", "yes"]:
            pending_student_id = record.get("pending_student")
            student_doc = await studDb.find_one({"_id": pending_student_id})
            if not student_doc:
                await message.channel.send(f"{message.author.mention} Fejl: Studenten kunne ikke findes i databasen.")
                return

            # Call verify_member to generate and store code
            success, result_message = await verify_member(message.author, student_doc["name"])
            if not success:
                await message.channel.send(f"{message.author.mention} {result_message}")
                return

            await message.channel.send(
                f"{message.author.mention} En verifikationskode er sendt til den valgte students email. "
                "Indtast koden her for at fuldføre verification."
            )

            await user_verification.update_one(
                {"discord_id": str(message.author.id)},
                {"$set": {"verification_state": "awaiting_code"}}
            )

        else:
            await user_verification.update_one(
                {"discord_id": str(message.author.id)},
                {"$set": {"verification_state": "awaiting_name"}}
            )
            await message.channel.send(
                f"{message.author.mention} Bekræftelsen blev ikke accepteret. Skriv venligst dit navn igen."
            )
        return

    # STATE: Awaiting code input
    elif state == "awaiting_code":
        code_record = await verification_codes.find_one({"member": message.author.name})
        expected_code = code_record.get("code") if code_record else None
        if not expected_code:
            await message.channel.send(f"{message.author.mention} Fejl: Ingen kode fundet. Kontakt en admin.")
            return

        if name_input.strip() == expected_code:
            await message.channel.send(f"{message.author.mention} Koden er korrekt. Verifikation fuldført!")

            # Call the update function
            await update_discord_user_after_verification(message.author, record.get("pending_student"))


            record = await user_verification.find_one(
                {"discord_id": str(message.author.id)}
            )

            student_name = code_record.get("student")
            student_id = record.get("pending_student")

            await update_discord_user_after_verification(
                message.author,
                student_id
            )

            # Transfer needed fields into user_verification
            await user_verification.update_one(
                {"discord_id": str(message.author.id)},
                {"$set": {
                    "verification_state": "completed",
                    "verified": True,
                    "member": message.author.name,
                    "student": student_name,
                    "ticket_channel_id": None,
                }}
            )

            await verification_codes.delete_one(
                {"_id": code_record["_id"]}
            )

            # Delete the verification channel after 10 seconds
            await message.channel.send("Denne kanal bliver slettet om 10 sekunder.")
            await asyncio.sleep(10)
            try:
                await message.channel.delete()
            except discord.Forbidden:
                print(f"Could not delete channel {message.channel.name}, permissions missing.")

        else:
            await message.channel.send(f"{message.author.mention} Forkert kode. Prøv igen.")
        return
    
async def update_discord_user_after_verification(member: discord.Member, student_id):
    """
    Update the Discord user after verification:
    - Change nickname to 'First N. N.' format
    - Assign role based on hold ('Hold_A' or 'Hold_B')
    - Handle admins above bot for nickname gracefully
    """
    student = await studDb.find_one({"_id": student_id})
    if not student:
        print(f"Student {student_id} not found in database.")
        return False

    guild = member.guild

    # Format nickname: First + initials
    name_parts = student["name"].split()
    if len(name_parts) >= 2:
        nickname = name_parts[0]  # First name
        for part in name_parts[1:]:
            nickname += f" {part[0]}."
    else:
        nickname = student["name"]

    # Assign role based on 'hold'
    hold = student.get("hold", "")
    role_name = None
    if hold == "Hold_A":
        role_name = "Hold_A"
    elif hold == "Hold_B":
        role_name = "Hold_B"

    success = True
    try:
        # Try to set nickname
        await member.edit(nick=nickname)
    except discord.Forbidden:
        # Bot cannot change nickname (admin or higher role)
        success = True  # Roles and verification can still succeed
        await member.send(
            f"Hej {member.name}, jeg kunne ikke ændre dit nickname pga. dine rolleindstillinger. "
            f"Venligst ændr manuelt til {nickname}."
        )

    try:
        unverified = discord.utils.get(guild.roles, name="Unverified")
        if unverified is None:
            return

        if unverified in member.roles:
            await member.remove_roles(unverified, reason="Auto-remove Unverified role")
    except Exception as e:
        print(e)


    # Assign role if exists
    if role_name:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            try:
                await member.add_roles(role, reason="Student verified")
            except discord.Forbidden:
                print(f"Cannot assign role {role_name} to {member.name}, permissions missing.")
        else:
            print(f"Role {role_name} not found in guild.")
    else:
        print(f'No roles')
    return success


async def reset_user_verification(guild, member):
    # 1. Delete existing ticket channels for this user
    ticket_channel_name = f"ticket-{member.name}".lower()

    for channel in guild.channels:
        if channel.name.lower() == ticket_channel_name:
            try:
                await channel.delete(reason="Resetting duplicate verification ticket")
            except Exception as e:
                print(f"Failed to delete channel {channel.name}: {e}")

    # 2. Remove verification codes
    await db.verification_codes.delete_many({
        "discord_id": str(member.id)
    })

    # 3. Remove user_verification ONLY if not verified
    record = await db.user_verification.find_one({
        "discord_id": str(member.id)
    })

    if record and not record.get("verified", False):
        await db.user_verification.delete_one({
            "discord_id": str(member.id)
        })


@bot.event
async def on_member_join(member):
    """Handle new member joining the server."""
    # Check if member has the required role
    has_hold_role = any(role.name in ["Hold A", "Hold B"] for role in member.roles)
    
    if not has_hold_role:
        # Send verification DM
        await add_support_ticket(member.guild, member)
    

    try:
        unverified_role = discord.utils.get(member.guild.roles, name="Unverified")
        if not unverified_role:
            # Create the role if it doesn't exist
            unverified_role = await member.guild.create_role(
                name="Unverified",
                permissions=discord.Permissions.none(),  # No permissions
                reason="Auto-created Unverified role"
            )
            
            # Move the role to the bottom of the role list (lowest priority)
            try:
                await unverified_role.edit(position=0)
            except:
                pass  # Might not have permissions to edit roles
            
            # Update channel permissions to restrict access
            for channel in member.guild.channels:
                try:
                    await channel.set_permissions(
                        unverified_role,
                        read_messages=False,
                        send_messages=False,
                        view_channel=False
                    )
                except:
                    continue  # Skip if we can't update channel permissions
        
        # Assign the unverified role
        await member.add_roles(unverified_role)
        
    except Exception as e:
        print(f"Error handling new member {member}: {e}")

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
    

    try:
        await handle_verification_message(message)
    except Exception as e:
        print(f'Error: {e}')


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # Ignore bot reactions
    if payload.user_id == bot.user.id:
        return

    # Fetch the guild and its verification channel from DB
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    guild_state = await db.guild_state.find_one({"guild_id": guild.id})
    if not guild_state or "verify_channel_id" not in guild_state:
        print('No verification channel')
        return

    verify_channel_id = guild_state["verify_channel_id"]

    # Only handle reactions in the verification channel
    if payload.channel_id != verify_channel_id:
        return

    # Fetch the member
    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return

    # Remove the reaction immediately
    channel = guild.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)
    await message.remove_reaction(payload.emoji, member)

    # Start verification for this member only
    try:
        await reset_user_verification(guild, member)

        result = await add_support_ticket(guild, member)
        global verified_count, failed_count
        await asyncio.sleep(1)  # Rate limiting
    except Exception as e:
        print(f"Failed to verify {member}: {e}")
        failed_count += 1

@bot.event
async def on_ready():
    global _synced
    print(f"Logged in as {bot.user}")
    await create_ttl_index()
    for guild in bot.guilds:
        if str(guild.id) not in EXCLUDED_GUILD_IDS:
            await ensure_verification_channel(guild)

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


