import os
import requests
import discord
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
import threading

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

# Start Flask in background thread
threading.Thread(target=run_flask).start()

# ---------------------------
# Discord Bot
# ---------------------------
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def get_song_links(url):
    try:
        r = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": url, "userCountry": "US"},
            timeout=20
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None, None, None

    links = []
    for platform, info in data.get("linksByPlatform", {}).items():
        if isinstance(info, dict) and "url" in info:
            name = platform.replace("_", " ").title()
            links.append(f"[{name}]({info['url']})")

    title = data.get("entityTitle", "")
    artist = ""

for entity in data.get("entitiesByUniqueId", {}).values():
    if entity.get("type") == "song":
        artist = entity.get("artistName", "")
        if not title:
            title = entity.get("title", "")
        thumbnail = entity.get("thumbnailUrl") or entity.get("artworkUrl")
        break

return links, title, artist, thumbnail


def get_genius_link(title, artist):
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


@tree.command(
    name="sl",
    description="Convert music link",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(url="Paste a Spotify/Apple/YouTube link")
async def sl(interaction: discord.Interaction, url: str):

    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(
            "Not allowed in this channel.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    links, title, artist, thumbnail = get_song_links(url)

    if not links:
        await interaction.followup.send("Could not fetch links.")
        return

    genius_url, genius_image =
    get_genius_link(title,artist)

embed = discord.Embed(
    title=f"{title} — {artist}",
    color=discord.Color.orange()
)

if thumbnail:
    embed.set_thumbnail(url=thumbnail)

embed.add_field(
    name="Platforms",
    value="\n".join(links),
    inline=False
)

if genius_url:
    embed.add_field(
        name="Lyrics",
        value=f"[Genius]({genius_url})",
        inline=False
    )

    if not thumbnail and genius_image:
        embed.set_thumbnail(url=genius_image)

@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {client.user}")


client.run(TOKEN)@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Synced and logged in as {client.user}")


client.run(TOKEN)
