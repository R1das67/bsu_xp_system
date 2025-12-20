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
    "police_role_id": None,
    "highrank_role_id": None,
    "role_system": {}  # role_id: xp_needed
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
    role_id = config.get("police_role_id")
    return role_id in [r.id for r in member.roles]

def is_highrank(member: discord.Member):
    role_id = config.get("highrank_role_id")
    return role_id in [r.id for r in member.roles]

def is_admin(member: discord.Member):
    return member.guild_permissions.administrator

# -----------------------------
# XP HANDLING
# -----------------------------
def add_xp(user_id: int, amount: int, reason: str = "unknown"):
    uid = str(user_id)
    data["xp"][uid] = data["xp"].get(uid, 0) + amount
    data.setdefault("xp_logs", []).append({
        "user_id": uid,
        "amount": amount,
        "reason": reason,
        "time": int(time.time())
    })
    save_json(DATA_FILE, data)

def get_xp(user_id: int):
    return data["xp"].get(str(user_id), 0)

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
    last = data["last_message"].get(uid, {"time":0, "content":""})

    if now - last["time"] < CHAT_COOLDOWN:
        return
    if last["content"] == message.content:
        return
    if len(message.content) < 5:
        return

    data["last_message"][uid] = {"time": now, "content": message.content}
    data["chat_count"][uid] = data.get("chat_count", {}).get(uid, 0) + 1

    if data["chat_count"][uid] % CHAT_BATCH == 0:
        add_xp(uid, CHAT_XP, reason="Chat Activity")
        log_channel = bot.get_channel(config["xp_log_channel_id"])
        if log_channel:
            await log_channel.send(f"💬 {message.author.mention} +{CHAT_XP} XP (Chat Activity)")

    save_json(DATA_FILE, data)
    await bot.process_commands(message)

# -----------------------------
# VOICE XP
# -----------------------------
VOICE_INTERVAL = 600  # 10min
VOICE_XP = 5
MAX_MUTE_TIME = 300  # 5min

@tasks.loop(seconds=60)
async def voice_xp_loop():
    now = time.time()
    for guild in bot.guilds:
        for uid, session in list(data.get("voice_sessions", {}).items()):
            member = guild.get_member(int(uid))
            if not member or not is_police(member):
                continue
            channel = member.voice.channel if member.voice else None
            if not channel:
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

            elapsed = now - session.get("last_xp", now)
            if elapsed >= VOICE_INTERVAL:
                add_xp(uid, VOICE_XP, reason="Voice Activity")
                session["last_xp"] = now
                log_channel = bot.get_channel(config["xp_log_channel_id"])
                if log_channel:
                    await log_channel.send(f"🎙️ {member.mention} +{VOICE_XP} XP (Voice Activity)")

    save_json(DATA_FILE, data)

@bot.event
async def on_ready():
    voice_xp_loop.start()
    await bot.tree.sync()
    print(f"XP Bot ready as {bot.user}")

@bot.event
async def on_voice_state_update(member, before, after):
    if not is_police(member):
        return
    uid = str(member.id)
    now = time.time()

    if after.channel and not before.channel:
        data["voice_sessions"][uid] = {"join": now, "last_xp": now, "muted_since": None}
    elif before.channel and not after.channel:
        session = data["voice_sessions"].pop(uid, None)
        if session:
            total = now - session["join"]
            earned = int(total // VOICE_INTERVAL) * VOICE_XP
            if earned > 0:
                add_xp(uid, earned, reason="Voice Session End")
                log_channel = bot.get_channel(config["xp_log_channel_id"])
                if log_channel:
                    await log_channel.send(f"🎙️ {member.mention} +{earned} XP (Voice Session End)")
    save_json(DATA_FILE, data)

# -----------------------------
# XP COMMANDS
# -----------------------------
@bot.tree.command(name="show-my-xp")
async def show_my_xp(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    xp = get_xp(uid)
    await interaction.response.send_message(f"Your current XP: **{xp}**", ephemeral=True)

# -----------------------------
# ROLE REQUEST
# -----------------------------
class RoleDecisionView(discord.ui.View):
    def __init__(self, user_id, role_id):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.role_id = role_id

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, custom_id="role_yes")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_highrank(interaction.user):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return
        member = interaction.guild.get_member(int(self.user_id))
        role = interaction.guild.get_role(self.role_id)
        await member.add_roles(role)
        await self.finish(interaction, True)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, custom_id="role_no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_highrank(interaction.user):
            await interaction.response.send_message("No permission.", ephemeral=True)
            return
        await self.finish(interaction, False)

    async def finish(self, interaction, approved):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        info = bot.get_channel(config["information_log_channel_id"])
        result = "Congratulations 🎉" if approved else "Sorry 😟"
        embed = discord.Embed(
            title=result,
            description=f"Decided by: {interaction.user.mention}",
            color=discord.Color.green() if approved else discord.Color.red()
        )
        await info.send(f"<@{self.user_id}>", embed=embed)

        data["applications"].pop(self.user_id, None)
        save_json(DATA_FILE, data)

# Angepasste Role-Request
@bot.tree.command(name="request-a-role")
async def request_role(interaction: discord.Interaction, role_name: str):
    uid = str(interaction.user.id)
    xp = get_xp(uid)

    # Suche die Rolle im XP-System
    role_id = None
    needed_xp = 0
    for rid, xp_needed in config["role_system"].items():
        r = interaction.guild.get_role(int(rid))
        if r and r.name.lower() == role_name.lower():
            role_id = rid
            needed_xp = xp_needed
            break

    if not role_id:
        # Liste aller verfügbaren Rollen + XP
        roles_list = []
        for rid, xp_needed in config["role_system"].items():
            r = interaction.guild.get_role(int(rid))
            if r:
                roles_list.append(f"{r.name} ({xp_needed} XP)")
        roles_str = "\n".join(roles_list) if roles_list else "No roles available."
        await interaction.response.send_message(
            f"This role is not in the XP system. Available roles:\n{roles_str}",
            ephemeral=True
        )
        return

    if uid in data["applications"]:
        await interaction.response.send_message("You already have an open request.", ephemeral=True)
        return

    if xp < needed_xp:
        await interaction.response.send_message(
            f"Not enough XP for this role. Needed: {needed_xp}, you have: {xp}",
            ephemeral=True
        )
        return

    role = interaction.guild.get_role(int(role_id))
    embed = discord.Embed(
        title="Role Request",
        description=f"**{interaction.user.display_name}**\nXP: {xp}\nRequested Role: {role.name}",
        color=discord.Color.blue()
    )

    view = RoleDecisionView(uid, role.id)
    channel = bot.get_channel(config["application_channel_id"])
    msg = await channel.send(embed=embed, view=view)

    data["applications"][uid] = {"role": role.id, "message": msg.id}
    save_json(DATA_FILE, data)

    await interaction.response.send_message("Role request submitted.", ephemeral=True)

# -----------------------------
# ADMIN CONFIG COMMANDS
# -----------------------------
@bot.tree.command(name="pick-xp-log-channel")
async def pick_xp_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_admin(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    config["xp_log_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f"XP Log Channel set to {channel.mention}", ephemeral=True)

@bot.tree.command(name="pick-application-channel")
async def pick_application_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_admin(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    config["application_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f"Application Channel set to {channel.mention}", ephemeral=True)

@bot.tree.command(name="pick-information-log")
async def pick_information_log(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_admin(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    config["information_log_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f"Information Log Channel set to {channel.mention}", ephemeral=True)

# -----------------------------
# ROLE SYSTEM COMMANDS
# -----------------------------
@bot.tree.command(name="add-role-system-with-xp")
async def add_role_system(interaction: discord.Interaction, role: discord.Role, xp: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    config["role_system"][str(role.id)] = xp
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f"Added role {role.name} with {xp} XP requirement.", ephemeral=True)

@bot.tree.command(name="edit-role-system")
async def edit_role_system(interaction: discord.Interaction, role: discord.Role, xp: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    if str(role.id) not in config["role_system"]:
        await interaction.response.send_message("This role is not in the XP system.", ephemeral=True)
        return
    config["role_system"][str(role.id)] = xp
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f"Updated role {role.name} to {xp} XP requirement.", ephemeral=True)

# -----------------------------
# RUN
# -----------------------------
bot.run(TOKEN)
