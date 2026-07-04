import asyncio
import random
import logging
import datetime
import json
import os
import signal
from typing import Optional

# Data directory - uses Railway persistent volume if available, else current directory
DATA_DIR = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ".")

import discord
from discord.ext import commands, tasks

# ==================== CONFIGURATION ====================
CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def setup_config():
    # Check environment variables first (for Railway/cloud deployment)
    token = os.environ.get("DISCORD_TOKEN")
    guild_id = os.environ.get("GUILD_ID")

    if token and guild_id:
        print("Using environment variables for config.")
        return {"token": token, "guild_id": int(guild_id), "welcome_channel_id": int(os.environ.get("WELCOME_CHANNEL_ID")) if os.environ.get("WELCOME_CHANNEL_ID") else None}

    # Fall back to config.json
    config = load_config()

    if not config.get("token"):
        print("ERROR: No DISCORD_TOKEN found! Set it as an env var or in config.json")
        return config

    if not config.get("guild_id"):
        print("ERROR: No GUILD_ID found! Set it as an env var or in config.json")
        return config

    return config

config = setup_config()
TOKEN = config.get("token") or ""
GUILD_ID = int(config["guild_id"]) if config.get("guild_id") else None
WELCOME_CHANNEL_ID = int(config["welcome_channel_id"]) if config.get("welcome_channel_id") else None

# Welcome message settings
WELCOME_FILE = os.path.join(DATA_DIR, "welcome.json")
DEFAULT_WELCOME = "**Thanks** for __joining__ us @new_user Enjoy ur stay <3! :yelo_flowers:"
CASUAL_MESSAGES = [
    "wassup gang",
    "Ahh such a rough day",
    "What are you guys doing",
    "yo what's good",
    "bruh I'm so tired today",
    "anyone down to play something",
    "lmao what happened",
    "sheeeesh",
    "who just joined lol",
    "vibes are immaculate rn",
]

# Presence settings
ACTIVITIES_FILE = os.path.join(DATA_DIR, "activities.json")
DEFAULT_ACTIVITIES = [
    {"type": "playing", "name": "Valorant"},
    {"type": "watching", "name": "YouTube"},
    {"type": "listening", "name": "Spotify"},
    {"type": "playing", "name": "Minecraft"},
    {"type": "competing", "name": "in Chess"},
]

# Command owner (only this account can run commands, configurable via env)
COMMAND_OWNER_ID = int(os.environ["COMMAND_OWNER_ID"]) if os.environ.get("COMMAND_OWNER_ID") else 1499437690901369113

# Anti-detection settings
MIN_TYPING_DELAY = 1.0
MAX_TYPING_DELAY = 3.0
MIN_SEND_DELAY = 0.5
MAX_SEND_DELAY = 2.0
STATUS_ROTATE_ENABLED = True
STATUS_ROTATE_MINUTES = 10  # Rotate status every X minutes
ACTIVITY_ROTATE_ENABLED = True
ACTIVITY_ROTATE_MINUTES = 15  # Rotate activity every X minutes

# AFK settings
AFK_ENABLED = False
AFK_MESSAGE = "I'm currently AFK. I'll be back soon!"

# Snipe settings (deleted messages)
SNIPE_ENABLED = True

# Logging
LOG_LEVEL = logging.INFO
# ========================================================

# Setup logging
logging.basicConfig(
    level=LOG_LEVEL,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('selfbot')

# Bot setup (no intents needed for selfbots)
bot = commands.Bot(command_prefix="!", self_bot=True)

# ==================== GLOBAL STATE ====================
deleted_messages = {}  # channel_id: list of deleted messages
afk_users = {}  # user_id: afk_message
snipe_enabled = SNIPE_ENABLED

# ==================== HELPER FUNCTIONS ====================

def load_welcome() -> str:
    if os.path.exists(WELCOME_FILE):
        try:
            with open(WELCOME_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("message", DEFAULT_WELCOME)
        except Exception:
            pass
    return DEFAULT_WELCOME

def save_welcome(message: str):
    with open(WELCOME_FILE, "w", encoding="utf-8") as f:
        json.dump({"message": message}, f, indent=2, ensure_ascii=False)

def format_welcome(template: str, member) -> str:
    return template.replace("@new_user", f"<@{member.id}>")

def load_activities() -> list:
    if os.path.exists(ACTIVITIES_FILE):
        try:
            with open(ACTIVITIES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("activities", DEFAULT_ACTIVITIES)
        except Exception:
            return DEFAULT_ACTIVITIES
    return DEFAULT_ACTIVITIES

def save_activities(activities: list):
    with open(ACTIVITIES_FILE, "w", encoding="utf-8") as f:
        json.dump({"activities": activities}, f, indent=2, ensure_ascii=False)

def get_activity_type(type_str: str) -> discord.ActivityType:
    mapping = {
        "playing": discord.ActivityType.playing,
        "watching": discord.ActivityType.watching,
        "listening": discord.ActivityType.listening,
        "competing": discord.ActivityType.competing,
        "streaming": discord.ActivityType.streaming,
    }
    return mapping.get(type_str.lower(), discord.ActivityType.playing)

def random_status() -> discord.Status:
    statuses = [discord.Status.online, discord.Status.idle, discord.Status.dnd]
    weights = [0.6, 0.3, 0.1]  # 60% online, 30% idle, 10% dnd
    return random.choices(statuses, weights=weights, k=1)[0]

def human_typing_time(message_length: int) -> float:
    """Simulate realistic typing speed (50-80 WPM equivalent)"""
    base_time = message_length * random.uniform(0.03, 0.06)
    pause_chance = random.random()
    if pause_chance > 0.95:
        base_time += random.uniform(1.0, 3.0)
    return max(MIN_TYPING_DELAY, min(base_time, 5.0))

def get_time_based_status() -> discord.Status:
    """Return status based on time of day for extra realism"""
    hour = datetime.datetime.now().hour
    if 0 <= hour < 7:
        return discord.Status.idle  # Night = idle
    elif 7 <= hour < 22:
        return discord.Status.online  # Day = online
    else:
        return discord.Status.dnd  # Late night = dnd

# ==================== EVENTS ====================

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Servers: {len(bot.guilds)}")
    logger.info(f"Server list: {', '.join([g.name for g in bot.guilds])}")

    # Set initial presence
    await set_presence()

    # Start background tasks
    if STATUS_ROTATE_ENABLED and not status_rotation.is_running():
        status_rotation.start()
    if ACTIVITY_ROTATE_ENABLED and not activity_rotation.is_running():
        activity_rotation.start()

    logger.info("Selfbot is ready!")

@bot.event
async def on_member_join(member):
    if GUILD_ID is not None and member.guild.id != GUILD_ID:
        return

    # Find channel
    channel = None
    if WELCOME_CHANNEL_ID:
        channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    else:
        channel = member.guild.system_channel

    # Fallback: find first channel with send permissions
    if channel is None:
        for ch in member.guild.text_channels:
            if ch.permissions_for(member.guild.me).send_messages:
                channel = ch
                break

    if channel is None:
        logger.warning(f"No suitable channel found in {member.guild.name}")
        return

    # Build welcome message from saved template
    welcome_template = load_welcome()
    welcome_msg = format_welcome(welcome_template, member)

    # Send a casual message first (no typing to avoid selfbot issues)
    try:
        casual_msg = random.choice(CASUAL_MESSAGES)
        await asyncio.sleep(random.uniform(MIN_SEND_DELAY, MAX_SEND_DELAY))
        await channel.send(casual_msg)
        logger.info(f"Casual message sent: {casual_msg}")
    except Exception as e:
        logger.error(f"Failed to send casual message: {type(e).__name__}: {e}")

    # Wait 20 seconds then send welcome
    await asyncio.sleep(20)

    # Send welcome message
    try:
        typing_time = human_typing_time(len(welcome_msg))
        async with channel.typing():
            await asyncio.sleep(typing_time)
        await asyncio.sleep(random.uniform(MIN_SEND_DELAY, MAX_SEND_DELAY))
        await channel.send(welcome_msg)
        logger.info(f"Welcome sent for {member.name} in {member.guild.name} (simulated {typing_time:.1f}s typing)")

    except discord.Forbidden:
        logger.error(f"Missing permissions in {member.guild.name}")
    except discord.HTTPException as e:
        logger.error(f"Failed to send: {e}")

@bot.event
async def on_message(message):
    global afk_users, snipe_enabled

    # AFK check: if someone mentions an AFK user
    if message.mentions and message.guild:
        for user in message.mentions:
            if user.id in afk_users:
                afk_msg = afk_users[user.id]
                try:
                    await message.channel.send(f"**{user.name}** is currently AFK: {afk_msg}")
                except Exception:
                    pass

    # Auto-react to own messages (like humans do)
    if message.author == bot.user and message.guild and (GUILD_ID is None or message.guild.id == GUILD_ID):
        if random.random() < 0.1:  # 10% chance to react
            try:
                emoji = random.choice(["✅", "👀", "✨", "❤️", "👍"])
                await message.add_reaction(emoji)
            except Exception:
                pass

    # Only process commands from the owner
    if message.author.id == COMMAND_OWNER_ID:
        await bot.process_commands(message)

@bot.event
async def on_message_delete(message):
    """Store deleted messages for snipe"""
    if not snipe_enabled:
        return
    if message.author.bot:
        return

    channel_id = message.channel.id
    if channel_id not in deleted_messages:
        deleted_messages[channel_id] = []

    deleted_messages[channel_id].append({
        "author": str(message.author),
        "content": message.content,
        "time": datetime.datetime.now().timestamp()
    })

    # Keep only last 5 deleted messages per channel
    if len(deleted_messages[channel_id]) > 5:
        deleted_messages[channel_id] = deleted_messages[channel_id][-5:]

# ==================== PRESENCE ====================

async def set_presence(status: Optional[discord.Status] = None, activity: Optional[discord.Activity] = None):
    if status is None:
        status = discord.Status.online

    if activity is None:
        activities = load_activities()
        if activities:
            chosen = random.choice(activities)
            activity = discord.Activity(
                type=get_activity_type(chosen.get("type", "playing")),
                name=chosen.get("name", "something")
            )
        else:
            activity = discord.Activity(
                type=discord.ActivityType.playing,
                name="something"
            )

    await bot.change_presence(status=status, activity=activity)
    logger.debug(f"Presence set: {status}")

@tasks.loop(minutes=STATUS_ROTATE_MINUTES)
async def status_rotation():
    """Rotate between Online/Idle/DND to look human"""
    new_status = random_status()
    await set_presence(status=new_status)
    logger.debug(f"Status rotated to {new_status}")

@status_rotation.before_loop
async def before_status_rotation():
    await bot.wait_until_ready()

@tasks.loop(minutes=ACTIVITY_ROTATE_MINUTES)
async def activity_rotation():
    """Rotate through different activities"""
    activities = load_activities()
    if not activities:
        return
    chosen = random.choice(activities)
    activity = discord.Activity(
        type=get_activity_type(chosen.get("type", "playing")),
        name=chosen.get("name", "something")
    )
    await set_presence(activity=activity)
    logger.debug(f"Activity rotated to {chosen.get('type')}: {chosen.get('name')}")

@activity_rotation.before_loop
async def before_activity_rotation():
    await bot.wait_until_ready()

# ==================== COMMANDS ====================

@bot.command(name="status")
async def change_status_cmd(ctx, status_type: str = "online"):
    """Change status: online, idle, dnd, invisible"""
    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    new_status = status_map.get(status_type.lower(), discord.Status.online)
    await set_presence(status=new_status)
    await ctx.send(f"Status changed to {status_type}")

@bot.command(name="activity")
async def change_activity_cmd(ctx, activity_type: str = "playing", *, activity_name: str = "something"):
    """Change activity: playing, watching, listening, competing"""
    activity = discord.Activity(
        type=get_activity_type(activity_type),
        name=activity_name
    )
    await set_presence(activity=activity)
    await ctx.send(f"Activity changed to {activity_type} {activity_name}")

@bot.command(name="customstatus")
async def custom_status_cmd(ctx, *, status_text: str):
    """Set a custom status"""
    activity = discord.CustomActivity(name=status_text)
    await set_presence(activity=activity)
    await ctx.send(f"Custom status set: {status_text}")

@bot.command(name="toggle")
async def toggle_rotation(ctx):
    """Toggle status rotation on/off"""
    global STATUS_ROTATE_ENABLED
    STATUS_ROTATE_ENABLED = not STATUS_ROTATE_ENABLED
    state = "enabled" if STATUS_ROTATE_ENABLED else "disabled"
    if STATUS_ROTATE_ENABLED and not status_rotation.is_running():
        status_rotation.start()
    elif not STATUS_ROTATE_ENABLED and status_rotation.is_running():
        status_rotation.cancel()
    await ctx.send(f"Status rotation {state}")

@bot.command(name="testwelcome")
async def test_welcome_cmd(ctx, member: Optional[discord.Member] = None):
    """Test the welcome message on yourself or a specified member"""
    if member is None:
        member = ctx.author

    channel = ctx.channel
    welcome_template = load_welcome()
    welcome_msg = format_welcome(welcome_template, member)

    async with channel.typing():
        await asyncio.sleep(random.uniform(1.0, 2.0))

    await asyncio.sleep(random.uniform(MIN_SEND_DELAY, MAX_SEND_DELAY))
    await ctx.send(welcome_msg)
    await ctx.send("Welcome message sent!", delete_after=3)

@bot.command(name="test")
async def test_cmd(ctx):
    """Send a test message to the welcome channel"""
    if WELCOME_CHANNEL_ID:
        channel = ctx.guild.get_channel(WELCOME_CHANNEL_ID) if ctx.guild else None
    else:
        channel = ctx.guild.system_channel if ctx.guild else None

    if channel is None:
        await ctx.send("Could not find the welcome channel.")
        return

    try:
        await channel.send("hii")
        await ctx.send(f"Sent `hii` to {channel.mention}", delete_after=3)
    except discord.Forbidden:
        await ctx.send(f"Missing permissions in {channel.mention}")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@bot.command(name="ping")
async def ping_cmd(ctx):
    """Check latency"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"Pong! {latency}ms")

@bot.command(name="servers")
async def list_servers_cmd(ctx):
    """List all servers"""
    server_list = "\n".join([f"- {g.name} (ID: {g.id})" for g in bot.guilds])
    await ctx.send(f"**Servers:**\n{server_list}")

@bot.command(name="set")
async def set_welcome_cmd(ctx, *, message: str):
    """Set the welcome message. Use @new_user where the user mention should go.
    
    Example: !set Welcome @new_user to our server! Have fun!
    """
    save_welcome(message)
    preview = format_welcome(message, ctx.author)
    await ctx.send(f"Welcome message updated!\n\n**Preview:**\n{preview}")

@bot.command(name="getwelcome")
async def get_welcome_cmd(ctx):
    """Show the current welcome message"""
    current = load_welcome()
    preview = format_welcome(current, ctx.author)
    await ctx.send(f"**Current welcome message:**\n{preview}\n\n**Template:**\n`{current}`")

@bot.command(name="resetwelcome")
async def reset_welcome_cmd(ctx):
    """Reset welcome message to default"""
    save_welcome(DEFAULT_WELCOME)
    await ctx.send("Welcome message reset to default!")

@bot.command(name="afk")
async def afk_cmd(ctx, *, message: str = None):
    """Set yourself as AFK with an optional message"""
    global afk_users
    afk_msg = message or AFK_MESSAGE
    afk_users[ctx.author.id] = afk_msg
    await ctx.send(f"**{ctx.author.name}** is now AFK: {afk_msg}")

@bot.command(name="unafk")
async def unafk_cmd(ctx):
    """Remove your AFK status"""
    global afk_users
    if ctx.author.id in afk_users:
        del afk_users[ctx.author.id]
        await ctx.send(f"Welcome back, **{ctx.author.name}**!")
    else:
        await ctx.send("You weren't AFK.")

@bot.command(name="snipe")
async def snipe_cmd(ctx):
    """Show the last deleted message in this channel"""
    channel_id = ctx.channel.id
    if channel_id not in deleted_messages or not deleted_messages[channel_id]:
        await ctx.send("No deleted messages to snipe!")
        return

    msg_data = deleted_messages[channel_id][-1]
    embed = discord.Embed(
        description=msg_data["content"],
        color=discord.Color.red(),
        timestamp=datetime.datetime.fromtimestamp(msg_data["time"])
    )
    embed.set_author(name=msg_data["author"])
    embed.set_footer(text="Deleted message")
    await ctx.send(embed=embed)

@bot.command(name="togglesnipe")
async def toggle_snipe_cmd(ctx):
    """Toggle snipe on/off"""
    global snipe_enabled
    snipe_enabled = not snipe_enabled
    state = "enabled" if snipe_enabled else "disabled"
    await ctx.send(f"Snipe {state}")

@bot.command(name="addactivity")
async def add_activity_cmd(ctx, activity_type: str, *, activity_name: str):
    """Add an activity to the rotation. Types: playing, watching, listening, competing"""
    activities = load_activities()
    activities.append({"type": activity_type.lower(), "name": activity_name})
    save_activities(activities)
    await ctx.send(f"Added: {activity_type} {activity_name}")

@bot.command(name="removeactivity")
async def remove_activity_cmd(ctx, index: int):
    """Remove an activity by index (use !listactivities to see indices)"""
    activities = load_activities()
    if 0 <= index < len(activities):
        removed = activities.pop(index)
        save_activities(activities)
        await ctx.send(f"Removed: {removed.get('type')} {removed.get('name')}")
    else:
        await ctx.send("Invalid index!")

@bot.command(name="listactivities")
async def list_activities_cmd(ctx):
    """List all activities in the rotation"""
    activities = load_activities()
    if not activities:
        await ctx.send("No activities configured.")
        return
    lines = [f"`{i}` - {a.get('type')}: {a.get('name')}" for i, a in enumerate(activities)]
    await ctx.send("**Activities:**\n" + "\n".join(lines))

@bot.command(name="clearactivities")
async def clear_activities_cmd(ctx):
    """Clear all activities"""
    save_activities([])
    await ctx.send("All activities cleared!")

@bot.command(name="activityrotate")
async def toggle_activity_rotate_cmd(ctx):
    """Toggle activity rotation"""
    global ACTIVITY_ROTATE_ENABLED
    ACTIVITY_ROTATE_ENABLED = not ACTIVITY_ROTATE_ENABLED
    state = "enabled" if ACTIVITY_ROTATE_ENABLED else "disabled"
    if ACTIVITY_ROTATE_ENABLED and not activity_rotation.is_running():
        activity_rotation.start()
    elif not ACTIVITY_ROTATE_ENABLED and activity_rotation.is_running():
        activity_rotation.cancel()
    await ctx.send(f"Activity rotation {state}")

@bot.command(name="helpall")
async def help_all_cmd(ctx):
    """Show all available commands"""
    help_text = """
**Welcome Commands:**
`!set <message>` - Set welcome message (use @new_user)
`!getwelcome` - View current message
`!resetwelcome` - Reset to default
`!testwelcome` - Test welcome message

**Presence Commands:**
`!status <online|idle|dnd|invisible>` - Change status
`!activity <type> <name>` - Set activity
`!customstatus <text>` - Set custom status
`!toggle` - Toggle status rotation
`!activityrotate` - Toggle activity rotation
`!addactivity <type> <name>` - Add activity to rotation
`!removeactivity <index>` - Remove activity
`!listactivities` - List all activities
`!clearactivities` - Clear all activities

**Utility Commands:**
`!afk [message]` - Set AFK status
`!unafk` - Remove AFK
`!snipe` - Show last deleted message
`!togglesnipe` - Toggle snipe
`!ping` - Check latency
`!servers` - List servers
"""
    await ctx.send(help_text)

# ==================== RUN ====================

def shutdown_handler():
    logger.info("Shutting down...")
    asyncio.create_task(bot.close())

if __name__ == "__main__":
    if not TOKEN or TOKEN == "YOUR_TOKEN_HERE":
        logger.error("Please set your token in config.json or DISCORD_TOKEN env var!")
    else:
        signal.signal(signal.SIGTERM, lambda s, f: shutdown_handler())
        bot.run(TOKEN)
