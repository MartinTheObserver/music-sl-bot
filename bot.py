import os
import re
import json
import random
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, ui
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
DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID"))

# ---------------------------
# Load Weird Laws JSON
# ---------------------------
WEIRD_LAWS_PATH = "weirdlaws.json"
if os.path.exists(WEIRD_LAWS_PATH):
    with open(WEIRD_LAWS_PATH, "r", encoding="utf-8") as f:
        WEIRD_LAWS = json.load(f)
else:
    WEIRD_LAWS = []

# ---------------------------
# Flask Web Server
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
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------------------
# Helper Functions
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

def get_random_hex_color() -> int:
    return random.randint(0, 0xFFFFFF)

def get_weird_law():
    if not WEIRD_LAWS:
        return ("Unknown", "No weird laws available.")
    law_entry = random.choice(WEIRD_LAWS)
    state = law_entry.get("state", "Unknown")
    law = law_entry.get("law", "No law available.")
    return state, law

async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=15) as resp:
            return await resp.json()
    except Exception:
        return None

# ---------------------------
# Music Bot Functions
# ---------------------------
async def fetch_song_links(query: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    # Original Song.link fetch logic
    import requests
    try:
        r = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": query, "userCountry": "US"},
            timeout=20
        )
        r.raise_for_status()
        return r.json()
    except:
        return None

def get_genius_link(title: str, artist: str):
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
        data = r.json()
        hits = data.get("response", {}).get("hits", [])
        if hits:
            return hits[0]["result"].get("url")
        return None
    except:
        return None

async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False):
    entity_id = None
    for uid, entity in song_data.get("entitiesByUniqueId", {}).items():
        if entity.get("type") == "song":
            entity_id = uid
            break
    if not entity_id:
        await ctx_or_interaction.send("Could not parse song data.")
        return

    song = song_data["entitiesByUniqueId"][entity_id]
    title = song.get("title", "Unknown Title")
    artist = song.get("artistName", "Unknown Artist")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")
    genius_url = get_genius_link(title, artist)
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
            url=genius_url if genius_url else None,
            description=f"by {artist}",
            color=0x1DB954
        )
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        embed.add_field(name="Listen On", value=chunk, inline=False)
        if len(chunks) > 1:
            embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
        await ctx_or_interaction.send(embed=embed)

# ---------------------------
# Prefix Command (!sl)
# ---------------------------
@bot.command(name="sl")
@commands.guild_only()
async def songlink(ctx, *, query: str):
    if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return
    song_data = await fetch_song_links(query, ctx, is_slash=False)
    if not song_data:
        await ctx.send("Could not find links for that song.")
        return
    await send_songlink_embed(ctx, song_data, is_slash=False)

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
        await interaction.response.send_message("Not allowed in this channel.", ephemeral=True)
        return
    await interaction.response.defer()
    song_data = await fetch_song_links(query, interaction, is_slash=True)
    if not song_data:
        await interaction.followup.send("Could not find links for that song.")
        return
    await send_songlink_embed(interaction, song_data, is_slash=True)

# ---------------------------
# ECM Buttons (New Features)
# ---------------------------
class ECMView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Weird Law", style=discord.ButtonStyle.danger)
    async def law_btn(self, interaction: discord.Interaction, button: ui.Button):
        state, law = get_weird_law()
        embed = discord.Embed(
            title=f"Weird Law from {state}",
            description=law,
            color=get_random_hex_color()
        )
        await interaction.response.send_message(embed=embed)

    @ui.button(label="Wiki/Explanation", style=discord.ButtonStyle.primary)
    async def wiki_btn(self, interaction: discord.Interaction, button: ui.Button):
        class WikiModal(ui.Modal, title="Wiki Query"):
            query = ui.TextInput(label="Enter topic", placeholder="Type a topic to fetch from Wikipedia...")

            async def on_submit(self, modal_interaction: discord.Interaction):
                await modal_interaction.response.defer()
                async with aiohttp.ClientSession() as session:
                    data = await fetch_json(session, f"https://en.wikipedia.org/api/rest_v1/page/summary/{self.query.value.replace(' ', '_')}")
                    if data and "extract" in data:
                        embed = discord.Embed(title=self.query.value, description=data["extract"], color=get_random_hex_color())
                    else:
                        embed = discord.Embed(title="Wiki", description="❌ No article found.", color=get_random_hex_color())
                    await modal_interaction.followup.send(embed=embed)
        await interaction.response.send_modal(WikiModal())

    @ui.button(label="Define", style=discord.ButtonStyle.success)
    async def define_btn(self, interaction: discord.Interaction, button: ui.Button):
        class DefineModal(ui.Modal, title="Define Query"):
            term = ui.TextInput(label="Enter term", placeholder="Word to define")
            async def on_submit(self, modal_interaction: discord.Interaction):
                await modal_interaction.response.defer()
                async with aiohttp.ClientSession() as session:
                    data = await fetch_json(session, f"https://api.dictionaryapi.dev/api/v2/entries/en/{self.term.value}")
                    if data and isinstance(data, list) and "meanings" in data[0]:
                        meanings = data[0]["meanings"]
                        defs = []
                        for m in meanings:
                            for d in m.get("definitions", []):
                                defs.append(d.get("definition"))
                        desc = "\n".join(defs)[:1000] if defs else "No definition found."
                        embed = discord.Embed(title=self.term.value, description=desc, color=get_random_hex_color())
                    else:
                        embed = discord.Embed(title=self.term.value, description="❌ No definition found.", color=get_random_hex_color())
                    await modal_interaction.followup.send(embed=embed)
        await interaction.response.send_modal(DefineModal())

    @ui.button(label="Random Color", style=discord.ButtonStyle.secondary)
    async def color_btn(self, interaction: discord.Interaction, button: ui.Button):
        color = get_random_hex_color()
        embed = discord.Embed(
            title="Random Color",
            description=f"Hex: #{color:06X}",
            color=color
        )
        await interaction.response.send_message(embed=embed)

# ---------------------------
# ECM Command
# ---------------------------
@tree.command(
    name="ecm",
    description="Open ECM feature menu",
    guild=discord.Object(id=GUILD_ID)
)
async def ecm_command(interaction: discord.Interaction):
    await interaction.response.send_message("Select a feature:", view=ECMView())

# ---------------------------
# Bot Ready Event
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

# ---------------------------
# Run Bot
# ---------------------------
bot.run(TOKEN)
