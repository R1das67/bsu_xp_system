import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import json
import time

# -----------------------------
# CONFIGURATION
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_FILE = "config.json"
DATA_FILE = "data.json"

# -----------------------------
# SAFE FILE HANDLING
# -----------------------------
def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=4)
        return default
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# -----------------------------
# CONFIG & DATA
# -----------------------------
config = load_json(CONFIG_FILE, {
    "xp_log_channel_id": None,
    "application_channel_id": None,
    "information_log_channel_id": None,
    "police_member_role_id": None,
    "role_system": {}
})

data = load_json(DATA_FILE, {
    "xp": {},
    "chat_count": {},
    "last_message": {},
    "voice_sessions": {},
    "applications": {}
})

# -----------------------------
# BOT SETUP
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -----------------------------
# PERMISSION CHECKS
# -----------------------------
def is_police(member: discord.Member):
    role_id = config.get("police_member_role_id")
    return role_id and role_id in [r.id for r in member.roles]

def is_admin(member: discord.Member):
    return member.guild_permissions.administrator

# -----------------------------
# XP HANDLING
# -----------------------------
def add_xp(user_id: int, amount: int, reason: str):
    uid = str(user_id)
    data["xp"][uid] = data["xp"].get(uid, 0) + amount
    save_json(DATA_FILE, data)

def get_xp(user_id: int):
    return data["xp"].get(str(user_id), 0)

async def log_xp(guild, member, amount, reason):
    channel = guild.get_channel(config["xp_log_channel_id"])
    if channel:
        await channel.send(
            f"**{member.display_name}** +{amount} XP ({reason})"
        )

# -----------------------------
# CHAT XP
# -----------------------------
CHAT_BATCH = 100
CHAT_XP = 10
CHAT_COOLDOWN = 30

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    if not is_police(message.author):
        return

    uid = str(message.author.id)
    now = time.time()
    last = data["last_message"].get(uid, {"time": 0, "content": ""})

    if now - last["time"] < CHAT_COOLDOWN:
        return
    if last["content"] == message.content:
        return
    if len(message.content) < 5:
        return

    data["last_message"][uid] = {"time": now, "content": message.content}
    data["chat_count"][uid] = data["chat_count"].get(uid, 0) + 1

    if data["chat_count"][uid] % CHAT_BATCH == 0:
        add_xp(uid, CHAT_XP, "Chat Activity")
        await log_xp(message.guild, message.author, CHAT_XP, "Chat Activity")

    save_json(DATA_FILE, data)
    await bot.process_commands(message)

# -----------------------------
# VOICE XP (LIVE ONLY)
# -----------------------------
VOICE_INTERVAL = 600
VOICE_XP = 5
MAX_MUTE_TIME = 300

@tasks.loop(seconds=60)
async def voice_xp_loop():
    now = time.time()
    for guild in bot.guilds:
        for uid, session in list(data["voice_sessions"].items()):
            member = guild.get_member(int(uid))
            if not member or not is_police(member) or not member.voice:
                continue

            muted = member.voice.self_mute or member.voice.self_deaf
            muted_since = session.get("muted_since")

            if muted:
                if muted_since is None:
                    session["muted_since"] = now
                elif now - muted_since > MAX_MUTE_TIME:
                    session["last_xp"] = now
            else:
                session["muted_since"] = None

            if now - session["last_xp"] >= VOICE_INTERVAL:
                session["last_xp"] = now
                add_xp(uid, VOICE_XP, "Voice Activity")
                await log_xp(guild, member, VOICE_XP, "Voice Activity")

    save_json(DATA_FILE, data)

@bot.event
async def on_voice_state_update(member, before, after):
    if not is_police(member):
        return
    uid = str(member.id)
    now = time.time()

    if after.channel and not before.channel:
        data["voice_sessions"][uid] = {
            "join": now,
            "last_xp": now,
            "muted_since": None
        }
    elif before.channel and not after.channel:
        data["voice_sessions"].pop(uid, None)

    save_json(DATA_FILE, data)

# -----------------------------
# READY
# -----------------------------
@bot.event
async def on_ready():
    voice_xp_loop.start()
    await bot.tree.sync()
    print(f"XP Bot ready as {bot.user}")

# -----------------------------
# XP COMMAND
# -----------------------------
@bot.tree.command(name="show-my-xp")
async def show_my_xp(interaction: discord.Interaction):
    if not is_police(interaction.user):
        await interaction.response.send_message("You are not part of the unit.", ephemeral=True)
        return
    xp = get_xp(interaction.user.id)
    await interaction.response.send_message(f"Your current XP: **{xp}**", ephemeral=True)

# -----------------------------
# ROLE REQUEST VIEW
# -----------------------------
class RoleDecisionView(discord.ui.View):
    def __init__(self, user_id, role_id):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.role_id = role_id

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, custom_id="role_yes")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_police(interaction.user):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return

        member = interaction.guild.get_member(int(self.user_id))
        role = interaction.guild.get_role(self.role_id)

        if member and role:
            await member.add_roles(role)

        await self.finish(interaction, True)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, custom_id="role_no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_police(interaction.user):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return
        await self.finish(interaction, False)

    async def finish(self, interaction, approved):
        for c in self.children:
            c.disabled = True
        await interaction.message.edit(view=self)

        channel = interaction.guild.get_channel(config["information_log_channel_id"])
        if channel:
            if approved:
                text = (
                    "**__Congratulations 🎉__**\n"
                    f"You got the role **<@&{self.role_id}>**\n"
                    f"Decided by: {interaction.user.mention}"
                )
            else:
                text = (
                    "**__Sorry 😟__**\n"
                    f"You did not get the role **<@&{self.role_id}>**\n"
                    f"Decided by: {interaction.user.mention}"
                )
            await channel.send(f"<@{self.user_id}>", embed=discord.Embed(description=text))

        data["applications"].pop(self.user_id, None)
        save_json(DATA_FILE, data)

# -----------------------------
# ROLE REQUEST COMMAND
# -----------------------------
@bot.tree.command(name="request-a-role")
async def request_role(interaction: discord.Interaction, role_name: str):
    if not is_police(interaction.user):
        await interaction.response.send_message("You are not part of the unit.", ephemeral=True)
        return

    uid = str(interaction.user.id)
    xp = get_xp(uid)

    role_id = None
    needed_xp = None

    for rid, xp_req in config["role_system"].items():
        role = interaction.guild.get_role(int(rid))
        if role and role.name.lower() == role_name.lower():
            role_id = int(rid)
            needed_xp = xp_req
            break

    if not role_id:
        roles = [
            f"{interaction.guild.get_role(int(rid)).name} ({xp} XP)"
            for rid, xp in config["role_system"].items()
            if interaction.guild.get_role(int(rid))
        ]
        await interaction.response.send_message(
            "Available roles:\n" + "\n".join(roles),
            ephemeral=True
        )
        return

    if xp < needed_xp:
        await interaction.response.send_message(
            f"Not enough XP ({xp}/{needed_xp})",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="Role Request",
        description=f"**{interaction.user.display_name}**\nXP: {xp}\nRole: <@&{role_id}>",
        color=discord.Color.blue()
    )

    view = RoleDecisionView(uid, role_id)
    channel = interaction.guild.get_channel(config["application_channel_id"])
    if channel:
        await channel.send(embed=embed, view=view)

    data["applications"][uid] = {"role": role_id}
    save_json(DATA_FILE, data)

    await interaction.response.send_message("Role request submitted.", ephemeral=True)

# -----------------------------
# ADMIN COMMANDS
# -----------------------------
@bot.tree.command(name="pick-police-member-role")
async def pick_police_member_role(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    config["police_member_role_id"] = role.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message("Police role set.", ephemeral=True)

@bot.tree.command(name="add-role-system-with-xp")
async def add_role_system(interaction: discord.Interaction, role: discord.Role, xp: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    config["role_system"][str(role.id)] = xp
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message("Role added.", ephemeral=True)

# -----------------------------
# RUN
# -----------------------------
bot.run(TOKEN)
