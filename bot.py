import os
import re
import requests
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
import threading
import asyncio

# ---------------------------
# Load Environment Variables
# ---------------------------
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))
DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID"))  # Your Discord ID for ephemeral debug

# ---------------------------
# Flask Web Server (Render requirement)
# ---------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive."

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ---------------------------
# Discord Bot Setup
# ---------------------------
intents = discord.Intents.default()
intents.message_content = True  # REQUIRED for prefix commands

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------------------
# Helper: Ephemeral Debug Sender
# ---------------------------
async def debug_send(ctx_or_interaction, msg, is_slash=False, ephemeral=True, debug_enabled=True):
    """Send ephemeral debug messages only if debug_enabled and DEBUG_USER_ID matches"""
    if not debug_enabled:
        return
    try:
        user_id = getattr(ctx_or_interaction, "author", None) or getattr(ctx_or_interaction, "user", None)
        if not user_id or user_id.id != DEBUG_USER_ID:
            return
        if is_slash:
            await ctx_or_interaction.followup.send(f"```DEBUG: {msg}```", ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(f"```DEBUG: {msg}```")
    except Exception as e:
        print(f"[DEBUG ERROR] Could not send debug message: {e}")

# ---------------------------
# Helper: Clean Song Title for Genius Search
# ---------------------------
def clean_song_title(title: str) -> str:
    if not title:
        return ""
    title = re.sub(r"\(feat\.?.*?\)|\[feat\.?.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\(.*?Remix.*?\)|\[.*?Remix.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[\[\]\(\)]", "", title)
    title = re.sub(r"[^\w\s&'-]", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()

# ---------------------------
# Fetch Song.link Data with Debug
# ---------------------------
async def fetch_song_links(query: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    await debug_send(ctx_or_interaction, f"Fetching Song.link data for query: {query}", is_slash=is_slash, debug_enabled=debug_enabled)
    try:
        r = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": query, "userCountry": "US"},
            timeout=20
        )
        r.raise_for_status()
        data = r.json()
        await debug_send(ctx_or_interaction, f"Song.link API returned keys: {list(data.keys())}", is_slash=is_slash, debug_enabled=debug_enabled)
        return data
    except requests.exceptions.RequestException as e:
        await debug_send(ctx_or_interaction, f"Song.link API request error: {e}", is_slash=is_slash, debug_enabled=debug_enabled)
        return None
    except Exception as e:
        await debug_send(ctx_or_interaction, f"Song.link unexpected error: {e}", is_slash=is_slash, debug_enabled=debug_enabled)
        return None

# ---------------------------
# Robust Genius Link Fetch with Full Debug
# ---------------------------
def get_genius_link(title: str, artist: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    if not title or not GENIUS_API_KEY:
        return None

    clean_title = clean_song_title(title)
    query = f"{clean_title} {artist}"

    try:
        r = requests.get(
            "https://api.genius.com/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
            timeout=20
        )

        if ctx_or_interaction and debug_enabled:
            if r.status_code == 401:
                asyncio.create_task(debug_send(ctx_or_interaction, f"Genius API 401 Unauthorized for query: {query}", is_slash=is_slash, debug_enabled=debug_enabled))
                return None
            elif r.status_code != 200:
                asyncio.create_task(debug_send(ctx_or_interaction, f"Genius API returned status {r.status_code}: {r.text}", is_slash=is_slash, debug_enabled=debug_enabled))

        data = r.json()
        hits = data.get("response", {}).get("hits", [])

        if not hits and ctx_or_interaction and debug_enabled:
            asyncio.create_task(debug_send(ctx_or_interaction, f"No Genius hits found for query: {query}", is_slash=is_slash, debug_enabled=debug_enabled))
            return None

        for hit in hits:
            result = hit.get("result", {})
            result_title = result.get("title", "").lower()
            result_artist = result.get("primary_artist", {}).get("name", "").lower()
            if clean_title.lower() in result_title and artist.lower() in result_artist:
                if ctx_or_interaction and debug_enabled:
                    asyncio.create_task(debug_send(ctx_or_interaction, f"Found exact Genius match: {result.get('url')}", is_slash=is_slash, debug_enabled=debug_enabled))
                return result.get("url")

        if hits and ctx_or_interaction and debug_enabled:
            asyncio.create_task(debug_send(ctx_or_interaction, f"No exact Genius match. Using first hit: {hits[0]['result'].get('url')}", is_slash=is_slash, debug_enabled=debug_enabled))

        return hits[0]["result"].get("url") if hits else None

    except requests.exceptions.RequestException as e:
        if ctx_or_interaction and debug_enabled:
            asyncio.create_task(debug_send(ctx_or_interaction, f"Genius API request exception: {e}", is_slash=is_slash, debug_enabled=debug_enabled))
        return None
    except Exception as e:
        if ctx_or_interaction and debug_enabled:
            asyncio.create_task(debug_send(ctx_or_interaction, f"Genius unexpected exception: {e}", is_slash=is_slash, debug_enabled=debug_enabled))
        return None

# ---------------------------
# Send Embed with Debug
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False, debug_enabled=True):
    await debug_send(ctx_or_interaction, f"Parsing Song.link entities...", is_slash=is_slash, debug_enabled=debug_enabled)
    entity_id = None
    for uid, entity in song_data.get("entitiesByUniqueId", {}).items():
        if entity.get("type") == "song":
            entity_id = uid
            break

    if not entity_id:
        msg = "Could not parse song data."
        if is_slash:
            await ctx_or_interaction.followup.send(msg)
        else:
            await ctx_or_interaction.send(msg)
        return

    song = song_data["entitiesByUniqueId"][entity_id]
    title = song.get("title", "Unknown Title")
    artist = song.get("artistName", "Unknown Artist")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")

    genius_url = get_genius_link(title, artist, ctx_or_interaction, is_slash, debug_enabled)
    await debug_send(ctx_or_interaction, f"Genius URL used: {genius_url}", is_slash=is_slash, debug_enabled=debug_enabled)

    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    await debug_send(ctx_or_interaction, f"Found {len(platforms)} platform links.", is_slash=is_slash, debug_enabled=debug_enabled)

    platform_links = "\n".join(
        f"[{platform.replace('_',' ').title()}]({data['url']})"
        for platform, data in platforms
        if isinstance(data, dict) and "url" in data
    )

    chunks = []
    current_chunk = ""
    for line in platform_links.split("\n"):
        if len(current_chunk) + len(line) + 1 > 1000:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ("\n" if current_chunk else "") + line
    if current_chunk:
        chunks.append(current_chunk)

    await debug_send(ctx_or_interaction, f"Split links into {len(chunks)} embed page(s).", is_slash=is_slash, debug_enabled=debug_enabled)

    for i, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=title,
            url=genius_url if genius_url else None,
            description=f"by {artist}",
            color=0x1DB954
        )

        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        embed.add_field(
            name="Listen On",
            value=chunk,
            inline=False
        )

        if len(chunks) > 1:
            embed.set_footer(text=f"Page {i+1}/{len(chunks)}")

        if is_slash:
            await ctx_or_interaction.followup.send(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

# ---------------------------
# Prefix Command (!sl)
# ---------------------------
@bot.command(name="sl")
@commands.guild_only()
@commands.has_permissions(send_messages=True)
async def songlink(ctx, *, query: str):
    debug_enabled = False
    if query.lower().startswith("debug "):
        debug_enabled = True
        query = query[6:].strip()

    if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return

    song_data = await fetch_song_links(query, ctx, is_slash=False, debug_enabled=debug_enabled)
    if not song_data:
        await ctx.send("Could not find links for that song.")
        return

    await send_songlink_embed(ctx, song_data, is_slash=False, debug_enabled=debug_enabled)

@songlink.error
async def songlink_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("This command cannot be used in DMs.")

# ---------------------------
# Slash Command (/sl)
# ---------------------------
@tree.command(
    name="sl",
    description="Get song links",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link", debug="Show debug messages for yourself")
async def slash_songlink(interaction: discord.Interaction, query: str, debug: bool = False):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(
            "Not allowed in this channel.",
            ephemeral=True
        )
        return

    await interaction.response.defer()
    song_data = await fetch_song_links(query, interaction, is_slash=True, debug_enabled=debug)
    if not song_data:
        await interaction.followup.send("Could not find links for that song.")
        return

    await send_songlink_embed(interaction, song_data, is_slash=True, debug_enabled=debug)

# ---------------------------
# Genius API Test on Startup
# ---------------------------
async def validate_genius_key():
    if not GENIUS_API_KEY:
        print("[Startup Warning] Genius API key not set.")
        return
    try:
        r = requests.get(
            "https://api.genius.com/search",
            params={"q": "Shape of You Ed Sheeran"},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
            timeout=20
        )
        if r.status_code == 401:
            user = await bot.fetch_user(DEBUG_USER_ID)
            await debug_send(user, "Genius API key is invalid (401 Unauthorized)", debug_enabled=True)
        elif r.status_code != 200:
            user = await bot.fetch_user(DEBUG_USER_ID)
            await debug_send(user, f"Genius API returned {r.status_code}: {r.text}", debug_enabled=True)
        else:
            data = r.json()
            hits = data.get("response", {}).get("hits", [])
            user = await bot.fetch_user(DEBUG_USER_ID)
            if hits:
                await debug_send(user, f"Genius API key validated successfully. Found {len(hits)} hit(s) for test search.", debug_enabled=True)
            else:
                await debug_send(user, "Genius API key seems valid but no hits returned for test search.", debug_enabled=True)
    except Exception as e:
        user = await bot.fetch_user(DEBUG_USER_ID)
        await debug_send(user, f"Exception during Genius API validation: {e}", debug_enabled=True)

# ---------------------------
# Bot Ready Event
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")
    # Run Genius API validation asynchronously
    asyncio.create_task(validate_genius_key())

# ---------------------------
# Run Bot
# ---------------------------
bot.run(TOKEN)
