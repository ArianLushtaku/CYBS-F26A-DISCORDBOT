from utils import *
import re
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

async def search_students_by_name(name):
    """Search for students by name with flexible matching."""
    # Normalize the name: trim whitespace and collapse multiple spaces
    name = re.sub(r'\s+', ' ', name.strip())
    
    if not name or len(name) < 2:
        return []
    
    name_parts = name.split()
    students = []
    
    print(f"[DEBUG] Searching for name: '{name}' (parts: {name_parts})")
    
    # studDb is the collection itself (studentNames collection in discord_bot database)
    collection = studDb
    
    # Try a test query to verify connection
    try:
        test_doc = await collection.find_one({})
        if test_doc:
            print(f"[DEBUG] Test query successful, sample fields: {list(test_doc.keys())}")
            print(f"[DEBUG] Sample name value: '{test_doc.get('name', 'N/A')}' (type: {type(test_doc.get('name'))})")
    except Exception as e:
        print(f"[DEBUG] Test query failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Strategy 1: Exact match (case-insensitive)
    try:
        regex_exact = f"^{re.escape(name)}$"
        students = await collection.find({"name": {"$regex": regex_exact, "$options": 'i'}}).to_list(None)
        print(f"[DEBUG] Exact match (regex), found: {len(students)} results")
        if students:
            print(f"[DEBUG] Found student: {students[0].get('name', 'N/A')}")
            return students
    except Exception as e:
        print(f"[DEBUG] Exact match error: {e}")
    
    # Strategy 2: Match all name parts sequentially (for full names)
    if len(name_parts) >= 2:
        try:
            regex_sequence = ".*".join([re.escape(part) for part in name_parts])
            students = await collection.find({"name": {"$regex": regex_sequence, "$options": 'i'}}).to_list(None)
            print(f"[DEBUG] Sequential match query: {regex_sequence}, found: {len(students)} results")
            if students:
                return students
        except Exception as e:
            print(f"[DEBUG] Sequential match error: {e}")
    
    # Strategy 3: Match first name only
    if len(name_parts) >= 1:
        try:
            first_name = name_parts[0]
            regex_first = f"^{re.escape(first_name)}(\\s|$)"
            students = await collection.find({"name": {"$regex": regex_first, "$options": 'i'}}).to_list(None)
            print(f"[DEBUG] First name match query: {regex_first}, found: {len(students)} results")
            if students:
                return students
        except Exception as e:
            print(f"[DEBUG] First name match error: {e}")
    
    # Strategy 4: Partial match - name contains the search term
    try:
        regex_partial = re.escape(name)
        students = await collection.find({"name": {"$regex": regex_partial, "$options": 'i'}}).to_list(None)
        print(f"[DEBUG] Partial match query: {regex_partial}, found: {len(students)} results")
    except Exception as e:
        print(f"[DEBUG] Partial match error: {e}")
    
    return students

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
                except:
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

async def ensure_verification_channel(guild):
    # Fetch guild_state from DB
    guild_state = await db.guild_state.find_one({"guild_id": guild.id})

    verify_channel_id = guild_state.get("verify_channel_id") if guild_state else None
    channel = guild.get_channel(verify_channel_id) if verify_channel_id else None

    # Check if channel exists
    if not channel:
        # Create a new text channel named "verifikation"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(send_messages=False, read_messages=True)
        }
        channel = await guild.create_text_channel(
            "verifikation", overwrites=overwrites, reason="Opretter verifikationskanal for self-verifikation"
        )
        print(f"Created verification channel in {guild.name}: {channel.id}")

        # Send the pinned verification message in Danish
        message = await channel.send(
        "## 🔐 Verifikation af studerende\n\n"
        "For at få adgang til serverens kanaler skal du verificere dig med din EK-mail.\n\n"
        "### Sådan fungerer det:\n"
        "1️⃣ Reagér med ✅ på denne besked.\n"
        "2️⃣ Indtast dit fulde navn, eller fornavn.\n"
        "3️⃣ Vælg den korrekte person fra listen (hvis flere matches findes).\n"
        "4️⃣ Du modtager en bekræftelsesmail på din skolemail.\n"
        "5️⃣ Klik på linket i mailen for at fuldføre verifikationen.\n\n"
        "Når du er verificeret, får du automatisk adgang og dit fornavn bliver sat som nickname.\n\n"
        "⚠️ Hvis problemer opstår, kontakt venligst Arian Lushtaku \n\n"
        )

        await message.pin()
        await message.add_reaction("✅")


        # Save to DB
        data = {
            "guild_id": guild.id,
            "verify_channel_id": channel.id,
            "verify_message_id": message.id
        }
        if guild_state:
            await db.guild_state.update_one(
                {"guild_id": guild.id},
                {"$set": {
                    "verify_channel_id": channel.id,
                    "verify_message_id": message.id
                }}
            )
        else:
            await db.guild_state.insert_one({
                "guild_id": guild.id,
                "verify_channel_id": channel.id,
                "verify_message_id": message.id
            })

    else:
        # Optional: ensure the message still exists
        verify_message_id = guild_state.get("verify_message_id")
        try:
            message = await channel.fetch_message(verify_message_id)
        except:
            message = await channel.send("Reager på denne besked for at starte din verifikation.")
            await message.pin()
            await message.add_reaction("✅")
            await db.guild_state.update_one(
                {"guild_id": guild.id}, {"$set": {"verify_message_id": message.id}}
            )

