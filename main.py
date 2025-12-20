import discord
from discord.ext import commands
import os
import json

# -------------------------------------------------
# BASIC SETTINGS
# -------------------------------------------------
TOKEN = os.getenv("DISCORD_TOKEN")

CONFIG_FILE = "config.json"
DATA_FILE = "data.json"

# -------------------------------------------------
# SAFE FILE HANDLING
# -------------------------------------------------
def ensure_file(path: str, default: dict):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=4)

# -------------------------------------------------
# INTENTS
# -------------------------------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# -------------------------------------------------
# ON READY
# -------------------------------------------------
@bot.event
async def on_ready():
    print(f"[BOOT] Logged in as {bot.user}")

    # ensure config & data exist
    ensure_file(CONFIG_FILE, {
        "panic_channel_id": None,
        "panic_role_id": None,
        "xp_log_channel_id": None,
        "application_channel_id": None,
        "information_log_channel_id": None,
        "police_role_id": None,
        "highrank_role_id": None
    })

    ensure_file(DATA_FILE, {
        "xp": {},
        "voice_sessions": {},
        "applications": {}
    })

    # load extensions (systems)
    await load_extensions()

    # sync slash commands
    await bot.tree.sync()
    print("[BOOT] Slash commands synced")

# -------------------------------------------------
# LOAD MODULES
# -------------------------------------------------
async def load_extensions():
    modules = [
        "systems.panic",
        "systems.xp_chat",
        "systems.xp_voice",
        "systems.xp_commands",
        "systems.applications"
    ]

    for module in modules:
        try:
            await bot.load_extension(module)
            print(f"[MODULE] Loaded {module}")
        except Exception as e:
            print(f"[ERROR] Failed to load {module}: {e}")

# -------------------------------------------------
# START BOT
# -------------------------------------------------
bot.run(TOKEN)
