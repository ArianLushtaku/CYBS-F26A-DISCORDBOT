import asyncio
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands
from utils import *
from calendar_func import sync_calendar_loop
from helper_functions import ensure_verification_channel, get_guild_state
from verification import create_ttl_index, send_verification_dm, send_verification_email, verify_member
from utils import EXCLUDED_GUILD_IDS, verification_codes
from datetime import timezone
import datetime
import re

_synced = False

@bot.event
async def on_member_join(member):
    """Handle new member joining the server."""
    # Check if member has the required role
    has_hold_role = any(role.name in ["Hold A", "Hold B"] for role in member.roles)
    
    if not has_hold_role:
        # Send verification DM
        await send_verification_dm(member)
    
    # You might want to assign a temporary role with restricted permissions
    # until verification is complete
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
        
    # Check if this is a DM
    if isinstance(message.channel, discord.DMChannel):
        user_id = str(message.author.id)

        # Check if this user is in the middle of verification
        verification = await verification_codes.find_one({"discord_id": user_id})
        if not verification:
            # Not in verification process, ignore
            await message.channel.send("Vær venlig at deltage i serveren og bruge verifikationsprocessen der.")
            return
        
        # Check if verification has exceeded 2 minutes
        if 'verification_start' in verification:
            try:
                verification_start = verification['verification_start']
                # MongoDB may return datetime in different formats, handle both
                if isinstance(verification_start, datetime.datetime):
                    start_time = verification_start
                    # Make timezone-aware if naive
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                else:
                    # Try to convert if it's stored differently
                    start_time = verification_start
                    if isinstance(start_time, datetime) and start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                
                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                if elapsed > 120:  # 2 minutes
                    # Clear verification to allow restart
                    await verification_codes.delete_one({"discord_id": user_id})
                    await message.channel.send(
                        "Verifikationen har taget mere end 2 minutter og er blevet annulleret. "
                        "Du kan starte forfra ved at reagere på beskeden i kanalen verifikation."
                    )
                    return
            except (TypeError, ValueError, AttributeError) as e:
                # If we can't parse the datetime, continue with verification
                print(f"Error checking verification timeout: {e}")
                pass
            
        # Check if we're waiting for a selection from multiple matches
        if 'possible_matches' in verification and verification['possible_matches']:
            try:
                selection = int(message.content.strip()) - 1
                matches = verification['possible_matches']
                


                if 0 <= selection < len(matches):
                    student = matches[selection]
                    student_name = student.get('name', 'Ukendt')
                    student_email = student.get('mail', student.get('email', ''))
                    
                    # Send verification email
                    email_sent = await send_verification_email(message.author, student)
                    if email_sent:
                        await message.channel.send(
                            f"✅ **Navn bekræftet!**\n\n"
                            f"**Navn:** {student_name}\n"
                            f"**Email:** {student_email}\n\n"
                            f"📧 En bekræftelsesemail er blevet sendt til din skole-email.\n"
                            f"Tjek venligst din email og klik på bekræftelseslinket for at fuldføre verifikationen."
                        )
                        
                        # Clear the possible matches and mark name as provided
                        await verification_codes.update_one(
                            {"discord_id": user_id},
                            {
                                "$unset": {"possible_matches": ""},
                                "$set": {"name_provided": True}
                            }
                        )
                    else:
                        await message.channel.send("❌ Kunne ikke sende bekræftelsesemail. Kontakt venligst en administrator for hjælp.")
                else:
                    await message.channel.send(f"❌ Ugyldigt valg. Angiv venligst et nummer mellem 1 og {len(matches)}.")
                return
                    
            except ValueError:
                await message.channel.send("❌ Angiv venligst et gyldigt nummer fra listen (f.eks. 1, 2, 3...).")
                return
        
        # Handle name verification - keep retrying until success
        # Check if we have a code but name hasn't been successfully verified yet
        if 'code' in verification and not verification.get('name_provided', False):
            name = message.content.strip()
            if not name or len(name) < 2:
                await message.channel.send("Angiv venligst et gyldigt navn (mindst 2 tegn).")
                return
            
            # Normalize name before processing
            name = re.sub(r'\s+', ' ', name.strip())
            
            # Proceed with verification (with timeout to prevent freezing)
            try:
                success, response = await asyncio.wait_for(
                    verify_member(message.author, name),
                    timeout=30.0  # 30 second timeout
                )
                await message.channel.send(response)
                
                # Only mark name_provided as True if verification succeeded
                if success:
                    await verification_codes.update_one(
                        {"discord_id": user_id},
                        {"$set": {"name_provided": True, "name": name}}
                    )
                # If not successful, don't mark name_provided - user can try again
            except asyncio.TimeoutError:
                await message.channel.send("Verifikationen tog for lang tid. Prøv venligst igen med dit navn.")
            except Exception as e:
                print(f"Error in verification process: {e}")
                import traceback
                traceback.print_exc()
                await message.channel.send("Der opstod en fejl under verifikationen. Prøv venligst igen med dit navn.")
        
    # Process commands if this is not a DM
    if not isinstance(message.channel, discord.DMChannel):
        await bot.process_commands(message)

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
        result = await send_verification_dm(member)  # Your existing DM verification function
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
        if guild.id not in EXCLUDED_GUILD_IDS:
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


