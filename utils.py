import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from motor.motor_asyncio import AsyncIOMotorClient
from discord.ext import commands
import discord

load_dotenv()

# FastAPI app
app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Discord bot
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Config
EXCLUDED_GUILD_IDS = os.getenv("EXCLUDED_GUILD_IDS", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CALENDAR_URL = os.getenv("CALENDER_URL")
MONGODB_URI = os.getenv("MONGODB_URI")

# MongoDB
mongo = AsyncIOMotorClient(MONGODB_URI)
db = mongo["discord_bot"]
guild_state_col = db["guild_state"]
