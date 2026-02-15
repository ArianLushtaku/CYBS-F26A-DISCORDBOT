import base64
import os
import string
import discord
import re
import random

from fastapi import Request
from fastapi.responses import HTMLResponse
from utils import *
from helper_functions import *
from datetime import timezone, datetime, timedelta
import discord
from bot_event import *
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def build_verification_email(to_email, subject, html_content):
    # Create a multipart message
    msg = MIMEMultipart("alternative")
    msg["To"] = to_email.strip()
    msg["From"] = os.environ["EMAIL_SENDER"]
    msg["Subject"] = subject

    # Create the HTML part
    html_part = MIMEText(html_content, "html", "utf-8")
    msg.attach(html_part)

    # Encode as base64 for Gmail API
    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw_message}


def generate_verification_code():
    """Generate a random 6-digit verification code."""
    return ''.join(random.choices(string.digits, k=6))

async def send_verification_dm(member):
    """Send a verification DM to the member."""
    try:
        # Check if user is already verified
        existing = await user_verification.find_one({"discord_id": str(member.id)})
        if existing and 'verified' in existing and existing['verified']:
            return True
            
        # Generate and store verification code
        code = generate_verification_code()
        expiry = datetime.now(timezone.utc) + timedelta(hours=24)  # Code expires in 24 hours
        verification_start = datetime.now(timezone.utc)  # Track when verification started
        
        await verification_codes.update_one(
            {"discord_id": str(member.id)},
            {"$set": {
                "code": code, 
                "expiry": expiry, 
                "used": False,
                "verification_start": verification_start,
                "name_provided": False  # Reset name_provided flag
            }},
            upsert=True
        )
        
        # Send DM with verification instructions
        embed = discord.Embed(
            title="Verifikation Påkrævet!",
            description="Velkommen til serveren! Før du får adgang til alle kanaler, skal vi bekræfte din identitet.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Verifikationskode", value=f"Din verifikationskode er: `{code}`")
        embed.add_field(name="Sådan bekræfter du", 
                       value="1. Besvar venligst med dit **fulde navn** eller kun dit **fornavn**.\n"
                             "2. Jeg vil søge efter dig i vores system.\n"
                             "3. Hvis der er flere matches, vil jeg bede dig vælge den rigtige.\n"
                             "4. Når navnet er bekræftet, sender jeg en bekræftelsesemail til din skole-email.",
                       inline=False)
        embed.set_footer(text="Denne kode udløber om 24 timer.")
        
        await member.send(embed=embed)
        return True
    except Exception as e:
        print(f"Error sending verification DM to {member}: {e}")
        return False

async def verify_member(member, name):
    """Verify a member's identity based on their name."""
    try:
        # Normalize the name
        name = re.sub(r'\s+', ' ', name.strip())
        
        if not name or len(name) < 2:
            return False, "Navnet er for kort. Angiv venligst dit fulde navn eller fornavn."
        
        # Search for students
        students = await search_students_by_name(name)
        
        if not students:
            return False, "❌ Ingen studerende fundet med det navn.\n\nPrøv venligst:\n• Dit fulde navn (fornavn efternavn)\n• Kun dit fornavn\n• Kontroller stavning"
        
        # Single match found
        if len(students) == 1:
            student = students[0]
            existing_verification = await user_verification.find_one({
            "student_id": student["_id"],
            "verified": True
                })

            if existing_verification:
                return False, f"Personen er allerede verificeret, under brugernavnet: {existing_verification['discord_username']}"

            student_name = student.get('name', 'Ukendt')
            
            # Send verification email
            email_sent = await send_verification_email(member, student)
            if email_sent:
                return True, (
                    f"✅ **Navn fundet!**\n\n"
                    f"**Navn:** {student_name}\n"
                    f"**Email:** {student.get('mail', student.get('email', 'Ikke tilgængelig'))}\n\n"
                    f"📧 En bekræftelsesemail er blevet sendt til din skole-email.\n"
                    f"Tjek venligst din email og klik på bekræftelseslinket for at fuldføre verifikationen."
                )
            else:
                return False, "❌ Kunne ikke sende bekræftelsesemail. Kontakt venligst en administrator for hjælp."
        
        # Multiple matches found
        else:
            # Store the possible matches for later reference
            await verification_codes.update_one(
                {"discord_id": str(member.id)},
                {"$set": {"possible_matches": students}},
                upsert=True
            )
            
            # Build options list
            options = []
            for i, s in enumerate(students, 1):
                student_name = s.get('name', 'Ukendt navn')
                student_email = s.get('mail', s.get('email', ''))
                options.append(f"**{i}.** {student_name} ({student_email})")
            
            options_text = "\n".join(options)
            
            return False, (
                f"🔍 **Flere matches fundet** ({len(students)} resultater)\n\n"
                f"{options_text}\n\n"
                f"Angiv venligst nummeret på den studerende, du er (f.eks. skriv **1**, **2**, osv.):"
            )
            
    except Exception as e:
        print(f"Error verifying member {member}: {e}")
        import traceback
        traceback.print_exc()
        return False, "❌ Der opstod en fejl under verifikationen. Prøv venligst igen senere."


async def send_verification_email(member, student):
    """Send a verification email to the student's school email."""
    try:
        # Generate a verification token
        token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        expiry = datetime.now(timezone.utc) + timedelta(hours=24)

        # Use localhost for default, but allow override via environment variable
        # In production, set BASE_URL to your public domain
        base_url = os.getenv("BASE_URL")
        verification_url = f"{base_url}/verify-email/{token}"
        
        # Store the verification token
        await verification_codes.update_one(
            {"discord_id": str(member.id)},
            {"$set": {
                "verification_token": token,
                "verification_expiry": expiry,
                "student_id": student["_id"],
                "hold_type": student.get("hold", "hold_a")  # Default to hold_a if not specified
            }},
            upsert=True
        )
        subject = "Bekræft din email - Discord Verifikation"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height:1.5; color: #111;">
            <h2 style="color: #2a9d8f;">Hej {student['name'].split()[0]},</h2>
            <p>En Discord bruger, <strong>{member.name}</strong>, prøver at verificere sin profil med dit navn. Klik på linket nedenfor for at bekræfte din email:</p>
            <p><a href="{verification_url}" style="display:inline-block; padding:10px 20px; background-color:#2a9d8f; color:white; text-decoration:none; border-radius:5px;">Bekræft email</a></p>
            <p style="color: #555;">Dette link udløber om 24 timer.</p>
            <p>Hvis du ikke har bedt om denne email, kan du ignorere den.</p>
            <hr>
            <p style="font-size:0.9em; color:#888;">Din Trofaste Robot, CYBS-F26-A</p>
        </body>
        </html>
        """
        # Get email address (try 'mail' first, then 'email' for compatibility)
        email_address = student.get('mail') or student.get('email')
        if not email_address:
            print(f"Error: No email address found for student {student.get('name', 'Unknown')}")
            return False
        
        # Create message
        creds = Credentials(
            None,
            refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            token_uri="https://oauth2.googleapis.com/token"
        )

        service = build("gmail", "v1", credentials=creds)

        # Construct the email
        message = build_verification_email(email_address, subject, body)

        # Send the email
        try:
            sent = service.users().messages().send(userId="me", body=message).execute()
            print(f"Verification email sent to {email_address}, message ID: {sent['id']}")
            return True
        except Exception as e:
            print(f"Error sending verification email via GMAIL: {e}")
            return False
    except Exception as e:
        print(f"Error sending verification email: {e}")
        return False
    
async def complete_verification(member):
    """Complete the verification process for a member."""
    try:
        # Get the verification record
        record = await verification_codes.find_one({"discord_id": str(member.id)})
        if not record:
            return False, "Ingen verifikationspost fundet. Start venligst verifikationsprocessen forfra."
            
        # Check if already verified
        user_record = await user_verification.find_one({"discord_id": str(member.id)})
        if user_record and user_record.get('verified'):
            return True, "Du er allerede bekræftet!"
            
        # Get the student record
        student = await studDb.find_one({"_id": record["student_id"]})
        if not student:
            return False, "Studerendes data ikke fundet. Kontakt venligst en administrator."
            
        # Assign the appropriate role based on hold type
        hold_type = record.get("hold_type", "hold_a").lower()
        role_name = "Hold A" if hold_type == "hold_a" else "Hold B"
        
        # Find the role in the server
        role = discord.utils.get(member.guild.roles, name=role_name)
        if not role:
            # Create the role if it doesn't exist
            try:
                role = await member.guild.create_role(name=role_name, mentionable=True)
            except Exception as e:
                print(f"Error creating role {role_name}: {e}")
                return False, f"Fejl: Kunne ikke finde eller oprette {role_name} rollen. Kontakt venligst en administrator."
        
        # Assign the role to the member
        try:
            await member.add_roles(role)
        except Exception as e:
            print(f"Error adding role to {member}: {e}")
            return False, f"Error: Could not assign the {role_name} role. Please contact an administrator."
        
        # Set the member's nickname to their first name
        # Split the full name into parts
        name_parts = student["name"].split()
        first_name = name_parts[0]

        # Get initials of all other names
        other_initials = ' '.join([f"{part[0]}." for part in name_parts[1:]])

        # Combine first name and initials
        nickname = f"{first_name} {other_initials}".strip()  # "John D." for "John Doe"

        # Set nickname
        try:
            await member.edit(nick=nickname)
        except Exception as e:
            print(f"Error setting nickname for {member}: {e}")

        
        # Mark as verified in the database
        await user_verification.update_one(
            {"discord_id": str(member.id)},
            {"$set": {
                "verified": True,
                "verified_at": datetime.now(timezone.utc),
                "student_id": student["_id"],
                "hold_type": hold_type,
                "name": student["name"],
                "email": student.get("mail", student.get("email", "")),
                "discord_username": f"{member.name}#{member.discriminator}"
            }},
            upsert=True
        )
        
        # Clean up the verification code
        await verification_codes.delete_one({"discord_id": str(member.id)})
        
        return True, f"✅ Verifikation fuldført! Du har fået {role_name} rollen og dit kaldenavn er blevet sat til {nickname}."
        
    except Exception as e:
        print(f"Error completing verification for {member}: {e}")
        return False, "Der opstod en fejl under verifikationen. Kontakt venligst en administrator."

async def create_ttl_index():
    try:
        await verification_codes.create_index(
            "verification_expiry",
            expireAfterSeconds=0  
        )
        print("TTL index created for verification_codes")
    except Exception as e:
        print(f"Error creating TTL index: {e}")

async def complete_verification_task(member, record):
    """Background task to complete the verification process."""
    try:
        # Get the student record
        student = await studDb.find_one({"_id": record["student_id"]})
        if not student:
            print(f"Student record not found for {member}")
            return
            
        # Get the hold type
        hold_type = record.get("hold_type", "hold_a").lower()
        role_name = "Hold A" if hold_type == "hold_a" else "Hold B"
        
        # Get or create the role
        role = discord.utils.get(member.guild.roles, name=role_name)
        if not role:
            try:
                role = await member.guild.create_role(
                    name=role_name, 
                    mentionable=True,
                    reason="Auto-created role for verification"
                )
                # Move the role to a reasonable position
                try:
                    # Try to position it below the @everyone role
                    everyone_role = member.guild.default_role
                    await role.edit(position=1)  # Just above @everyone
                except:
                    pass
            except Exception as e:
                print(f"Error creating role {role_name}: {e}")
                return
        
        # Assign the role
        try:
            await member.add_roles(role)
        except Exception as e:
            print(f"Error adding role to {member}: {e}")
            return
        
        # Set nickname
        # Split the full name into parts
        name_parts = student["name"].split()
        first_name = name_parts[0]

        # Get initials of all other names
        other_initials = ' '.join([f"{part[0]}." for part in name_parts[1:]])

        # Combine first name and initials
        nickname = f"{first_name} {other_initials}".strip()  # "John D." for "John Doe"

        # Set nickname
        try:
            await member.edit(nick=nickname)
        except Exception as e:
            print(f"Error setting nickname for {member}: {e}")

        
        # Mark as verified in the database
        await user_verification.update_one(
            {"discord_id": str(member.id)},
            {"$set": {
                "verified": True,
                "verified_at": datetime.now(timezone.utc),
                "student_id": student["_id"],
                "hold_type": hold_type,
                "name": student["name"],
                "email": student.get("mail", student.get("email", "")),
                "discord_username": f"{member.name}#{member.discriminator}"
            }},
            upsert=True
        )
        
        # Remove the unverified role if it exists
        try:
            unverified_role = discord.utils.get(member.guild.roles, name="Unverified")
            if unverified_role and unverified_role in member.roles:
                await member.remove_roles(unverified_role)
        except Exception as e:
            print(f"Error removing Unverified role: {e}")
            
        # Send a DM to the user
        try:
            await member.send(f"✅ Din email er blevet bekræftet! Du har nu adgang til {role_name} kanalerne.")
        except:
            pass  # User might have DMs disabled
            
    except Exception as e:
        print(f"Error in complete_verification_task: {e}")

async def complete_verification_by_id(discord_id, record):
    """Complete verification by fetching member in bot's event loop."""
    try:
        # Fetch member in bot's event loop
        member = None
        guild = None
        
        for g in bot.guilds:
            if g.id in EXCLUDED_GUILD_IDS:
                continue
            try:
                member = await g.fetch_member(int(discord_id))
                if member:
                    guild = g
                    break
            except:
                continue
        
        if not member or not guild:
            print(f"Could not find member {discord_id} in any guild")
            return
        
        # Now call the actual verification task
        await complete_verification_task(member, record)
    except Exception as e:
        print(f"Error in complete_verification_by_id: {e}")
        import traceback
        traceback.print_exc()

@bot.tree.command(name="verify_all", description="Verify all members without Hold A or Hold B roles")
@admin_only()
async def verify_all(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    print(f"Verification requested in guild: {guild.name} (ID: {guild.id})")
    
    # Get the roles to check (using correct names with spaces)
    hold_a = discord.utils.get(guild.roles, name="Hold A")
    hold_b = discord.utils.get(guild.roles, name="Hold B")
    
    print(f"Found roles - Hold A: {hold_a is not None}, Hold B: {hold_b is not None}")
    
    # Get all members who don't have either role
    members_to_verify = []
    total_members = 0
    verified_count = 0
    failed_count = 0

    for member in guild.members:
        total_members += 1
        # Skip bots explicitly
        if member.bot:
            continue
            
        has_hold_a = hold_a in member.roles if hold_a else False
        has_hold_b = hold_b in member.roles if hold_b else False
        
        # Also check if already verified in database
        existing = await user_verification.find_one({"discord_id": str(member.id)})
        if existing and existing.get('verified'):
            continue
        
        if not has_hold_a and not has_hold_b:
            members_to_verify.append(member)
    
    print(f"Total members: {total_members}")
    print(f"Bots: {sum(1 for m in guild.members if m.bot)}")
    print(f"Members to verify: {len(members_to_verify)}")
    
    if not members_to_verify:
        await interaction.followup.send(
            "Ingen brugere skal verificeres. Enten har alle allerede en Hold A eller Hold B rolle, "
            "eller der er ingen brugere på serveren.",
            ephemeral=True
        )
        return

    
    # Send initial response
    await interaction.followup.send(f"Starter verifikation for {len(members_to_verify)} medlemmer...", ephemeral=True)
    
    # Process each member
    for member in members_to_verify:
        try:
            # Double-check it's not a bot
            if member.bot:
                continue
                
            # Use the existing verification function
            result = await send_verification_dm(member)
            if result:
                verified_count += 1
            else:
                failed_count += 1
            await asyncio.sleep(1)  # Rate limiting
        except Exception as e:
            print(f"Failed to verify {member}: {e}")
            failed_count += 1
    
    # Send completion message
    await interaction.followup.send(
        f"Verifikation fuldført!\n"
        f"✅ Sendt til {verified_count} medlemmer\n"
        f"❌ Fejlede for {failed_count} medlemmer",
        ephemeral=True
    )

async def handle_email_verification_on_bot_loop(token: str):
    """Handle email verification entirely on bot's event loop."""
    # All database and Discord operations happen here on bot's loop
    record = await verification_codes.find_one({"verification_token": token})
    if not record:
        return False, "Ugyldig eller udløbet token"

    # Check expiry - handle both timezone-aware and timezone-naive datetimes
    if record.get("verification_expiry"):
        expiry = record["verification_expiry"]
        # Make expiry timezone-aware if it's naive
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        # Compare with timezone-aware datetime
        if expiry < datetime.now(timezone.utc):
            return False, "Tokenet er udløbet"

    # Check if already used
    if record.get("used"):
        return False, "Dette link er allerede brugt"

    discord_id = int(record["discord_id"])
    member = None
    
    # Find member in bot's guilds (this is now on bot's loop)
    for guild in bot.guilds:
        if guild.id in EXCLUDED_GUILD_IDS:
            continue
        try:
            member = await guild.fetch_member(discord_id)
            if member:
                break
        except:
            continue

    if not member:
        return False, "Discord medlem ikke fundet"

    # Complete verification (already on bot's loop)
    try:
        success, message = await complete_verification(member)
    except Exception as e:
        print(f"Error completing verification for Discord member {discord_id}: {e}")
        import traceback
        traceback.print_exc()
        return False, f"Fejl under verifikation: {e}"

    return success, message

async def handle_email_verification(token: str):
    """Handle email verification by scheduling on bot's event loop."""
    # Check if bot loop is available
    if not hasattr(bot, 'loop') or not bot.loop or not bot.loop.is_running():
        return False, "Bot er ikke klar. Prøv igen om et øjeblik."
    
    # Schedule the entire verification process on bot's event loop
    try:
        future = asyncio.run_coroutine_threadsafe(
            handle_email_verification_on_bot_loop(token),
            bot.loop
        )
        success, message = future.result(timeout=15.0)
        return success, message
    except asyncio.TimeoutError:
        return False, "Verifikation tog for lang tid. Prøv venligst igen."
    except Exception as e:
        print(f"Error in handle_email_verification: {e}")
        import traceback
        traceback.print_exc()
        return False, f"Fejl under verifikation: {e}"

async def verify_email(token: str, request: Request):
    # Check User-Agent to ignore link scanners / prefetch bots
    ua = request.headers.get("user-agent", "").lower()
    if any(x in ua for x in ["google", "microsoft", "scan", "facebookexternalhit", "linkedinbot"]):
        return HTMLResponse(
            "<html><body style='font-family:monospace; text-align:center; color:#444;'>"
            "<h2>Link scanning detected</h2>"
            "<p>This is an automated scan, not a real verification click.</p>"
            "</body></html>"
        )

    # Call your verification logic on the bot loop
    success, message = await handle_email_verification(token)

    # Build cyber / tech styled HTML page
    if success:
        color = "#2a9d8f"
        title = "✅ Email bekræftet!"
        icon = "🛡️"
    else:
        color = "#e63946"
        title = "❌ Bekræftelse fejlede"
        icon = "⚠️"

    html_content = f"""
    <html>
    <head>
      <meta charset="UTF-8">
      <title>{title}</title>
      <style>
        body {{
            font-family: 'Courier New', monospace;
            background-color: #0f0f0f;
            color: #eee;
            text-align: center;
            padding: 50px;
        }}
        .container {{
            background-color: #1a1a1a;
            border: 2px solid {color};
            border-radius: 15px;
            display: inline-block;
            padding: 40px;
            max-width: 600px;
        }}
        h1 {{
            color: {color};
            font-size: 2.5em;
        }}
        p {{
            font-size: 1.1em;
            color: #ccc;
        }}
        a.button {{
            display: inline-block;
            margin-top: 20px;
            padding: 12px 25px;
            font-size: 1em;
            background-color: {color};
            color: #0f0f0f;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;
            letter-spacing: 0.5px;
        }}
        .footer {{
            margin-top: 40px;
            font-size: 0.8em;
            color: #888;
        }}
      </style>
    </head>
    <body>
        <div class="container">
            <h1>{icon} {title}</h1>
            <p>{message}</p>
            <p class="footer">Din Trofaste Robot - CYBS-F26-A</p>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(html_content)