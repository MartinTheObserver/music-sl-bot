import os
import re
import requests
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
import threading

# ---------------------------
# Load Environment Variables
# ---------------------------
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))

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
# Fetch Song.link Data
# ---------------------------
async def fetch_song_links(query: str):
    try:
        r = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": query, "userCountry": "US"},
            timeout=20
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Song.link API Error:", e)
        return None

# ---------------------------
# Robust Genius Link Fetch
# ---------------------------
def get_genius_link(title: str, artist: str):
    if not title:
        print("[Genius Warning] Missing song title.")
        return None
    if not GENIUS_API_KEY:
        print("[Genius Warning] Genius API key not set. Genius search skipped.")
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

        if r.status_code == 401:
            print("[Genius Warning] Unauthorized: Check your Genius API key.")
            return None
        elif r.status_code != 200:
            print(f"[Genius Warning] Genius API returned status {r.status_code}: {r.text}")
            return None

        data = r.json()
        hits = data.get("response", {}).get("hits", [])

        if not hits:
            print(f"[Genius Warning] No hits found for query: '{query}'")
            return None

        for hit in hits:
            result = hit.get("result", {})
            result_title = result.get("title", "").lower()
            result_artist = result.get("primary_artist", {}).get("name", "").lower()
            if clean_title.lower() in result_title and artist.lower() in result_artist:
                print(f"[Genius Info] Found exact match: {result.get('url')}")
                return result.get("url")

        print(f"[Genius Info] No exact match. Using first hit: {hits[0]['result'].get('url')}")
        return hits[0]["result"].get("url")

    except requests.exceptions.RequestException as e:
        print(f"[Genius Warning] Request exception: {e}")
        return None
    except Exception as e:
        print(f"[Genius Warning] Unexpected exception: {e}")
        return None

# ---------------------------
# Send Embed (Shared Logic)
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False):
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

    genius_url = get_genius_link(title, artist)
    print("Genius URL found:", genius_url)

    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]

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

    for i, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=title,
            url=genius_url if genius_url else None,  # Title links to Genius
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
    if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return

    song_data = await fetch_song_links(query)
    if not song_data:
        await ctx.send("Could not find links for that song.")
        return

    await send_songlink_embed(ctx, song_data)

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
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link")
async def slash_songlink(interaction: discord.Interaction, query: str):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(
            "Not allowed in this channel.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    song_data = await fetch_song_links(query)
    if not song_data:
        await interaction.followup.send("Could not find links for that song.")
        return

    await send_songlink_embed(interaction, song_data, is_slash=True)

# ---------------------------
# Bot Ready Event
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

    if not GENIUS_API_KEY:
        print("[Startup Warning] Genius API key not set. Genius URLs will not work.")
    else:
        test_url = get_genius_link("Shape of You", "Ed Sheeran")
        if not test_url:
            print("[Startup Warning] Genius API key may be invalid or Genius search failed.")

# ---------------------------
# Run Bot
# ---------------------------
bot.run(TOKEN)
