import os
import re
import json
import random
import requests
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
from dotenv import load_dotenv
from flask import Flask
import threading
import asyncio
import aiohttp

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
# Helper: Ephemeral Debug
# ---------------------------
async def debug_send(ctx_or_interaction, msg, is_slash=False, ephemeral=True, debug_enabled=True):
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
        print(f"[DEBUG ERROR] {e}")

# ---------------------------
# Helper: Clean Song Title
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
# Song.link API
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
        await debug_send(ctx_or_interaction, f"Song.link API keys: {list(data.keys())}", is_slash=is_slash, debug_enabled=debug_enabled)
        return data
    except Exception as e:
        await debug_send(ctx_or_interaction, f"Song.link fetch error: {e}", is_slash=is_slash, debug_enabled=debug_enabled)
        return None

# ---------------------------
# Genius API
# ---------------------------
def get_genius_link(title: str, artist: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    if not title or not GENIUS_API_KEY:
        return None
    clean_title_str = clean_song_title(title)
    query = f"{clean_title_str} {artist}"
    try:
        r = requests.get(
            "https://api.genius.com/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
            timeout=20
        )
        data = r.json()
        hits = data.get("response", {}).get("hits", [])
        for hit in hits:
            result = hit.get("result", {})
            result_title = result.get("title", "").lower()
            result_artist = result.get("primary_artist", {}).get("name", "").lower()
            if clean_title_str.lower() in result_title and artist.lower() in result_artist:
                return result.get("url")
        return hits[0]["result"].get("url") if hits else None
    except Exception as e:
        if ctx_or_interaction and debug_enabled:
            asyncio.create_task(debug_send(ctx_or_interaction, f"Genius error: {e}", is_slash=is_slash, debug_enabled=debug_enabled))
        return None

# ---------------------------
# Send Song Embed
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False, debug_enabled=True):
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

    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    platform_links = "\n".join(
        f"[{platform.replace('_',' ').title()}]({data['url']})"
        for platform, data in platforms if isinstance(data, dict) and "url" in data
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
            description=f"by {artist}\n\n{chunk}",
            color=0x1DB954
        )
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if len(chunks) > 1:
            embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
        if is_slash:
            await ctx_or_interaction.followup.send(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

    # Add Song Modal Button
    view = View()
    view.add_item(Button(label="🔎 Query Another Song", style=discord.ButtonStyle.secondary, custom_id="song_modal"))
    await ctx_or_interaction.followup.send("Use the button below to query another song:", view=view) if is_slash else await ctx_or_interaction.send("Use the button below to query another song:", view=view)

# ---------------------------
# Prefix / Slash Song.link
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

@tree.command(
    name="sl",
    description="Get song links",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link")
async def slash_songlink(interaction: discord.Interaction, query: str):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("Not allowed here.", ephemeral=True)
        return
    await interaction.response.defer()
    song_data = await fetch_song_links(query, interaction, is_slash=True)
    if not song_data:
        await interaction.followup.send("Could not find links for that song.")
        return
    await send_songlink_embed(interaction, song_data, is_slash=True)

# ---------------------------
# ECM View
# ---------------------------
class ECMView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Fact", style=discord.ButtonStyle.success, custom_id="fact"))
        self.add_item(Button(label="Useless Fact", style=discord.ButtonStyle.success, custom_id="uselessfact"))
        self.add_item(Button(label="Quote", style=discord.ButtonStyle.success, custom_id="quote"))
        self.add_item(Button(label="Chaos", style=discord.ButtonStyle.danger, custom_id="chaos"))
        self.add_item(Button(label="Color", style=discord.ButtonStyle.primary, custom_id="color"))
        self.add_item(Button(label="Define", style=discord.ButtonStyle.primary, custom_id="define"))
        self.add_item(Button(label="Weird Law", style=discord.ButtonStyle.secondary, custom_id="weirdlaw"))

# ---------------------------
# Fetch JSON Helper
# ---------------------------
async def fetch_json(session, url):
    async with session.get(url) as resp:
        return await resp.json()

# ---------------------------
# ECM Button Callbacks
# ---------------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not interaction.type == discord.InteractionType.component:
        return
    custom_id = interaction.data.get("custom_id")
    async with aiohttp.ClientSession() as session:
        if custom_id == "fact":
            data = await fetch_json(session, "https://uselessfacts.jsph.pl/random.json?language=en")
            embed = discord.Embed(title="Random Fact", description=data.get("text"), color=0x00FF00)
            await interaction.response.send_message(embed=embed)
        elif custom_id == "uselessfact":
            data = await fetch_json(session, "https://uselessfacts.jsph.pl/random.json?language=en")
            embed = discord.Embed(title="Useless Fact", description=data.get("text"), color=0x00FF00)
            await interaction.response.send_message(embed=embed)
        elif custom_id == "quote":
            data = await fetch_json(session, "https://api.quotable.io/random")
            embed = discord.Embed(title="Quote", description=f"{data.get('content')}\n— {data.get('author')}", color=0xFFD700)
            await interaction.response.send_message(embed=embed)
        elif custom_id == "chaos":
            facts = []
            facts.append((await fetch_json(session, "https://uselessfacts.jsph.pl/random.json?language=en")).get("text"))
            facts.append((await fetch_json(session, "https://api.quotable.io/random")).get("content"))
            embed = discord.Embed(title="Chaos", description="\n• ".join(facts), color=0xFF4500)
            await interaction.response.send_message(embed=embed)
        elif custom_id == "color":
            color = random.randint(0, 0xFFFFFF)
            embed = discord.Embed(title="Random Color", description=f"Hex: #{color:06X}", color=color)
            await interaction.response.send_message(embed=embed)
        elif custom_id == "weirdlaw":
            with open("weirdlaws.json", "r") as f:
                laws = json.load(f)
            law = random.choice(laws)
            embed = discord.Embed(title="Weird Law", description=law, color=0x8A2BE2)
            await interaction.response.send_message(embed=embed)
        elif custom_id == "define":
            await interaction.response.send_modal(WikiModal())

# ---------------------------
# Wiki Modal
# ---------------------------
class WikiModal(Modal):
    def __init__(self):
        super().__init__(title="Define / Explain")
        self.input = TextInput(label="Query", placeholder="Enter term to define")
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        query = self.input.value
        summary = "No definition found."
        try:
            r = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{query}")
            if r.status_code == 200:
                data = r.json()
                summary = data.get("extract", summary)
        except Exception:
            pass
        embed = discord.Embed(title=f"Definition: {query}", description=summary, color=0x1E90FF)
        await interaction.response.send_message(embed=embed)

# ---------------------------
# /ecm Command
# ---------------------------
@tree.command(
    name="ecm",
    description="Open ECM Entertainment menu",
    guild=discord.Object(id=GUILD_ID)
)
async def ecm_menu(interaction: discord.Interaction):
    view = ECMView()
    await interaction.response.send_message("Choose a fun action from the buttons below:", view=view)

# ---------------------------
# Bot Ready
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

# ---------------------------
# Run Bot
# ---------------------------
bot.run(TOKEN)
