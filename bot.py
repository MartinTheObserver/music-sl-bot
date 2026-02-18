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

threading.Thread(target=run_flask).start()

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
        )

        if not thumbnail and genius_image:
            embed.set_thumbnail(url=genius_image)

    await interaction.followup.send(embed=embed)


@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Synced and logged in as {client.user}")


client.run(TOKEN)
