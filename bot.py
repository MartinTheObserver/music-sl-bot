import os
import requests
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
import threading
from typing import List, Tuple

# ---------------------------
# Helper Functions
# ---------------------------
def chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))

# ---------------------------
# Flask Web Server (Required by Render)
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
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # For slash commands

# ---------------------------
# Song Link Fetching
# ---------------------------
async def fetch_song_links(query: str) -> dict:
    """Fetch song.link API data by query (Spotify/YouTube/Apple)"""
    try:
        r = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": query, "userCountry": "US"},
            timeout=20
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Error fetching song links:", e)
        return None

def get_song_links(url: str) -> Tuple[List[str], str, str, str]:
    try:
        r = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": url, "userCountry": "US"},
            timeout=20
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None, None, None, None

    links = []
    for platform, info in data.get("linksByPlatform", {}).items():
        if isinstance(info, dict) and "url" in info:
            name = platform.replace("_", " ").title()
            links.append(f"[{name}]({info['url']})")

    title = data.get("entityTitle", "")
    artist = ""
    thumbnail = None

    for entity in data.get("entitiesByUniqueId", {}).values():
        if entity.get("type") == "song":
            artist = entity.get("artistName", "")
            if not title:
                title = entity.get("title", "")
            thumbnail = entity.get("thumbnailUrl") or entity.get("artworkUrl")
            break

    return links, title, artist, thumbnail

def get_genius_link(title: str, artist: str) -> Tuple[str, str]:
    if not title:
        return None, None
    try:
        r = requests.get(
            "https://api.genius.com/search",
            params={"q": f"{title} {artist}"},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
            timeout=20
        )
        if r.status_code == 200:
            hits = r.json()["response"]["hits"]
            if hits:
                result = hits[0]["result"]
                return result.get("url"), result.get("song_art_image_url")
    except Exception as e:
        print("Genius error:", e)
    return None, None

# ---------------------------
# Embed Sending Logic (Shared)
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False):
    entity_id = song_data["entityUniqueId"]
    links = list(song_data["linksByPlatform"].items())
    chunks = list(chunked(links, 20))

    for i, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=song_data["entitiesByUniqueId"][entity_id]["title"],
            description=song_data["entitiesByUniqueId"][entity_id]["artistName"],
            color=0x1DB954
        )

        if i > 0:
            embed.set_footer(text=f"Continued ({i+1}/{len(chunks)})")

        for platform, data in chunk:
            embed.add_field(
                name=platform.title(),
                value=data["url"],
                inline=False
            )

        if is_slash:
            await ctx_or_interaction.followup.send(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

# ---------------------------
# Prefix Command (!sl)
# ---------------------------
@bot.command(name="sl")
async def songlink(ctx, *, query: str):
    song_data = await fetch_song_links(query)
    if not song_data:
        await ctx.send("Could not find links for that song.")
        return
    await send_songlink_embed(ctx, song_data)

# ---------------------------
# Slash Command (/sl)
# ---------------------------
@tree.command(
    name="sl",
    description="Get song links",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link")
async def slash_songlink(interaction: discord.Interaction, query: str):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(
            "Not allowed in this channel.", ephemeral=True
        )
        return

    await interaction.response.defer()
    song_data = await fetch_song_links(query)
    if not song_data:
        await interaction.followup.send("Could not find links for that song.")
        return
    await send_songlink_embed(interaction, song_data, is_slash=True)

# ---------------------------
# Bot Events
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

# ---------------------------
# Run Bot
# ---------------------------
bot.run(TOKEN)
