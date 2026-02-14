import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from discord.ext import commands
import discord


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app = FastAPI()

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(GZipMiddleware, minimum_size=1000)


intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)
event_mapping = {}

load_dotenv()

EXCLUDED_GUILD_IDS = {
    1465690642897305703
}
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CALENDAR_URL = os.getenv("CALENDER_URL")
MONGODB_URI = os.getenv("MONGODB_URI")

mongo = AsyncIOMotorClient(MONGODB_URI)
db = mongo["discord_bot"]
guild_state_col = db["guild_state"]
studDb = db["studentNames"]
verification_codes = db["verification_codes"]  # Store verification codes
user_verification = db["user_verification"]  # Store user verification status

