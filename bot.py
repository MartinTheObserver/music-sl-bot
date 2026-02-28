import os
import re
import json
import random
import aiohttp
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
DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID"))

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
# Load Weird Laws
# ---------------------------
WEIRD_LAWS = []
weird_laws_path = os.path.join(os.path.dirname(__file__), "weirdlaws.json")
if os.path.exists(weird_laws_path):
    with open(weird_laws_path, "r", encoding="utf-8") as f:
        WEIRD_LAWS = json.load(f)

def get_weird_law():
    if not WEIRD_LAWS:
        return "Unknown", "No weird laws loaded."
    law_entry = random.choice(WEIRD_LAWS)
    return law_entry.get("state", "Unknown"), law_entry.get("law", "No law found.")

# ---------------------------
# Helper: Random Hex Color
# ---------------------------
def random_hex_color():
    return random.randint(0, 0xFFFFFF)

# ---------------------------
# Helper: Ephemeral Debug
# ---------------------------
async def debug_send(ctx_or_interaction, msg, is_slash=False, ephemeral=True):
    user_id = getattr(ctx_or_interaction, "author", None) or getattr(ctx_or_interaction, "user", None)
    if not user_id or user_id.id != DEBUG_USER_ID:
        return
    try:
        if is_slash:
            await ctx_or_interaction.followup.send(f"```DEBUG: {msg}```", ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(f"```DEBUG: {msg}```")
    except:
        pass

# ---------------------------
# Song.link + Genius Helpers
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

async def fetch_song_links(query: str, ctx_or_interaction=None, is_slash=False):
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
    clean_title_text = clean_song_title(title)
    query = f"{clean_title_text} {artist}"
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
    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    platform_links = "\n".join(
        f"[{platform.replace('_',' ').title()}]({data['url']})"
        for platform, data in platforms if isinstance(data, dict) and "url" in data
    )
    embed = discord.Embed(
        title=title,
        url=genius_url,
        description=f"by {artist}\n\n{platform_links}",
        color=random_hex_color()
    )
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if is_slash:
        await ctx_or_interaction.followup.send(embed=embed)
    else:
        await ctx_or_interaction.send(embed=embed)

# ---------------------------
# Prefix Command (!sl)
# ---------------------------
@bot.command(name="sl")
@commands.guild_only()
async def songlink(ctx, *, query: str):
    if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return
    data = await fetch_song_links(query, ctx, is_slash=False)
    if not data:
        await ctx.send("Could not find links for that song.")
        return
    await send_songlink_embed(ctx, data, is_slash=False)

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
    data = await fetch_song_links(query, interaction, is_slash=True)
    if not data:
        await interaction.followup.send("Could not find links for that song.")
        return
    await send_songlink_embed(interaction, data, is_slash=True)

# ---------------------------
# Fetch Quote
# ---------------------------
async def fetch_quote():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.quotable.io/random") as resp:
                j = await resp.json()
                return j.get("content", "No quote available.")
    except:
        return "No quote available."

# ---------------------------
# Define Word
# ---------------------------
async def define_word(word: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}") as resp:
                j = await resp.json()
                if isinstance(j, list) and j:
                    meaning = j[0]["meanings"][0]["definitions"][0]["definition"]
                    return meaning
    except:
        pass
    return "No definition found."

# ---------------------------
# Wiki Summary
# ---------------------------
async def wiki_summary(query: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{query}") as resp:
                j = await resp.json()
                return j.get("extract", "SONGLINK: ❌ No article found.")
    except:
        return "SONGLINK: ❌ No article found."

# ---------------------------
# ECM Button View
# ---------------------------
class ECMView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # Buttons
        self.add_item(discord.ui.Button(label="Define", style=discord.ButtonStyle.primary, custom_id="define"))
        self.add_item(discord.ui.Button(label="Wiki", style=discord.ButtonStyle.primary, custom_id="wiki"))
        self.add_item(discord.ui.Button(label="Weird Law", style=discord.ButtonStyle.danger, custom_id="weird_law"))
        self.add_item(discord.ui.Button(label="Useless Fact", style=discord.ButtonStyle.secondary, custom_id="useless_fact"))
        self.add_item(discord.ui.Button(label="Random Quote", style=discord.ButtonStyle.success, custom_id="quote"))

    @discord.ui.button(label="Placeholder", style=discord.ButtonStyle.secondary, disabled=True)
    async def dummy(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def on_timeout(self):
        pass

# ---------------------------
# ECM Button Callbacks
# ---------------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not interaction.type == discord.InteractionType.component:
        return
    cid = interaction.data.get("custom_id")
    await interaction.response.defer()
    if cid == "quote":
        quote_text = await fetch_quote()
        await interaction.followup.send(embed=discord.Embed(title="Quote", description=quote_text, color=random_hex_color()))
    elif cid == "define":
        await interaction.followup.send("Use `define: word` in chat to get a definition.")  # user will type
    elif cid == "wiki":
        await interaction.followup.send("Use `wiki: query` in chat to get a summary.")  # user will type
    elif cid == "weird_law":
        state, law = get_weird_law()
        await interaction.followup.send(embed=discord.Embed(title=f"Weird Law: {state}", description=law, color=random_hex_color()))
    elif cid == "useless_fact":
        await interaction.followup.send(embed=discord.Embed(title="Useless Fact", description="Something trivial.", color=random_hex_color()))

# ---------------------------
# ECM Slash Command
# ---------------------------
@tree.command(
    name="ecm",
    description="Open ECM Entertainment menu",
    guild=discord.Object(id=GUILD_ID)
)
async def ecm_command(interaction: discord.Interaction):
    view = ECMView()
    await interaction.response.send_message("Welcome to ECM Entertainment! Choose an option below:", view=view)

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
