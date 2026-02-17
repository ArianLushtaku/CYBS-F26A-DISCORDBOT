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

async def send_verification(member: discord.Member, channel: discord.TextChannel):
    """Send verification instructions inside the created ticket channel."""
    try:
        existing = await user_verification.find_one(
            {"discord_id": str(member.id)}
        )

        if existing and existing.get("verified"):
            return True

        embed = discord.Embed(
            title="Verifikation Påkrævet!",
            description=(
                "Velkommen til serveren! Før du får adgang til alle kanaler, "
                "skal vi bekræfte din identitet."
            ),
            color=discord.Color.blue()
        )

        embed.add_field(
            name="Sådan bekræfter du",
            value=(
                "1. Besvar venligst med dit **fulde navn** eller kun dit **fornavn**.\n"
                "2. Jeg vil søge efter dig i vores system.\n"
                "3. Hvis der er flere matches, vil jeg bede dig vælge den rigtige.\n"
                "4. Når navnet er bekræftet, sender jeg en bekræftelsesemail til din skole-email."
            ),
            inline=False
        )

        embed.set_footer(text="Koden udløber efter 6 minutter.")

        await channel.send(
            content=member.mention,
            embed=embed
        )

        return True

    except Exception as e:
        print(f"Error sending verification in channel for {member}: {e}")
        return False

async def verify_member(member, name):
    """Verify a member's identity based on their name."""
    try:
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
            code = generate_verification_code()
            expiry = datetime.now(timezone.utc) + timedelta(hours=24)  # Code expires in 24 hours
            verification_start = datetime.now(timezone.utc)  # Track when verification started
            
            await verification_codes.update_one(
                {"discord_id": str(member.id)},
                {"$set": {
                    "member": member.name,
                    "code": code, 
                    "expiry": expiry, 
                    "used": False,
                    "verification_start": verification_start,
                    "student": student_name
                }},
                upsert=True
            )
            
            # Send verification email
            email_sent = await send_verification_email(member, student)
            if email_sent:
                return True, (
                    f"✅ **Navn fundet!**\n\n"
                    f"**Navn:** {student_name}\n"
                    f"**Email:** {student.get('mail', student.get('email', 'Ikke tilgængelig'))}\n\n"
                    f"📧 En bekræftelsesemail er blevet sendt til din skole-email.\n"
                    f"Tjek venligst din email og klik på bekræftelseslinket for at fuldføre verifikationen.\n "
                    f"Der kan muligvis gå 1 minut eller mere før du kan se den i indboksen"
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
        verification = await verification_codes.find_one({"member": member.name})
        code = verification.get('code')

        subject = "Bekræft din email - Discord Verifikation"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height:1.5; color: #111;">
            <h2 style="color: #2a9d8f;">Hej {student['name'].split()[0]},</h2>
            <p>En Discord bruger, <strong>{member.name}</strong>, prøver at verificere sin profil med dit navn. Indtast denne kode på discord.</p>
            <h3>Din verifikationskode:</h3>
            <p style="font-size:24px; font-weight:bold;">{code}</p>
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
    


async def create_ttl_index():
    try:
        await verification_codes.create_index(
            "verification_expiry",
            expireAfterSeconds=0  
        )
        print("TTL index created for verification_codes")
    except Exception as e:
        print(f"Error creating TTL index: {e}")