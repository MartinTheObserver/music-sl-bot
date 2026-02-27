import os
import re
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
# Flask Web Server (Railway/Render requirement)
# ---------------------------
app = Flask(__name__)
@app.route("/")
def home(): return "Bot is alive."
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
# Helper: Debug sender
# ---------------------------
async def debug_send(ctx_or_interaction, msg, is_slash=False, ephemeral=True, debug_enabled=True):
    if not debug_enabled: return
    try:
        user_id = getattr(ctx_or_interaction, "author", None) or getattr(ctx_or_interaction, "user", None)
        if not user_id or user_id.id != DEBUG_USER_ID: return
        if is_slash:
            await ctx_or_interaction.followup.send(f"```DEBUG: {msg}```", ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(f"```DEBUG: {msg}```")
    except Exception as e: print(f"[DEBUG ERROR] {e}")

# ---------------------------
# Helper: Clean song titles
# ---------------------------
def clean_song_title(title: str) -> str:
    if not title: return ""
    title = re.sub(r"\(feat\.?.*?\)|\[feat\.?.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\(.*?Remix.*?\)|\[.*?Remix.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[\[\]\(\)]", "", title)
    title = re.sub(r"[^\w\s&'-]", "", title)
    return re.sub(r"\s+", " ", title).strip()

# ---------------------------
# Fetch Song.link Data
# ---------------------------
async def fetch_song_links(query: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    await debug_send(ctx_or_interaction, f"Fetching Song.link data for query: {query}", is_slash=is_slash, debug_enabled=debug_enabled)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.song.link/v1-alpha.1/links", params={"url": query, "userCountry": "US"}, timeout=20) as r:
                data = await r.json()
                await debug_send(ctx_or_interaction, f"Song.link API returned keys: {list(data.keys())}", is_slash=is_slash, debug_enabled=debug_enabled)
                return data
    except Exception as e:
        await debug_send(ctx_or_interaction, f"Song.link error: {e}", is_slash=is_slash, debug_enabled=debug_enabled)
        return None

# ---------------------------
# Genius API
# ---------------------------
def get_genius_link(title: str, artist: str):
    if not title or not GENIUS_API_KEY: return None
    query = f"{clean_song_title(title)} {artist}"
    try:
        r = requests.get(
            "https://api.genius.com/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
            timeout=20
        )
        hits = r.json().get("response", {}).get("hits", [])
        if not hits: return None
        for hit in hits:
            result = hit.get("result", {})
            if clean_song_title(title).lower() in result.get("title", "").lower() and artist.lower() in result.get("primary_artist", {}).get("name","").lower():
                return result.get("url")
        return hits[0]["result"].get("url")
    except: return None

# ---------------------------
# Song.embed sender
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False):
    entity_id = next((uid for uid, e in song_data.get("entitiesByUniqueId", {}).items() if e.get("type")=="song"), None)
    if not entity_id:
        msg = "Could not parse song data."
        await (ctx_or_interaction.followup.send(msg) if is_slash else ctx_or_interaction.send(msg))
        return

    song = song_data["entitiesByUniqueId"][entity_id]
    title, artist = song.get("title","Unknown"), song.get("artistName","Unknown")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")
    genius_url = get_genius_link(title, artist)

    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    platform_links = "\n".join(f"[{p.replace('_',' ').title()}]({d['url']})" for p,d in platforms if isinstance(d, dict) and "url" in d)

    embed = discord.Embed(title=title, url=genius_url, description=f"by {artist}", color=0x1DB954)
    if thumbnail: embed.set_thumbnail(url=thumbnail)
    embed.add_field(name="Listen On", value=platform_links[:1000], inline=False)

    # Add button to input another song
    class NewSLModal(ui.Modal, title="Paste a song URL"):
        song_url = ui.TextInput(label="Song URL")

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer()
            data = await fetch_song_links(self.song_url.value, interaction, is_slash=True)
            if data: await send_songlink_embed(interaction, data, is_slash=True)
            else: await interaction.followup.send("Could not find links.")

    view = ui.View()
    view.add_item(ui.Button(label="Paste another song", style=discord.ButtonStyle.green, custom_id="paste_song", row=1))
    if is_slash: await ctx_or_interaction.followup.send(embed=embed, view=view)
    else: await ctx_or_interaction.send(embed=embed, view=view)

# ---------------------------
# !sl prefix
# ---------------------------
@bot.command(name="sl")
@commands.guild_only()
async def sl_prefix(ctx, *, query):
    if ctx.channel.id != ALLOWED_CHANNEL_ID: return
    song_data = await fetch_song_links(query, ctx, is_slash=False)
    if song_data: await send_songlink_embed(ctx, song_data, is_slash=False)
    else: await ctx.send("Could not find links.")

# ---------------------------
# /sl slash
# ---------------------------
@tree.command(name="sl", description="Get song links", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link")
async def sl(interaction: discord.Interaction, query:str):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("Not allowed in this channel.", ephemeral=True)
        return
    await interaction.response.defer()
    song_data = await fetch_song_links(query, interaction, is_slash=True)
    if song_data: await send_songlink_embed(interaction, song_data, is_slash=True)
    else: await interaction.followup.send("Could not find links.")

# ---------------------------
# ECM Extra Buttons
# ---------------------------
async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=15) as resp:
            return await resp.json()
    except: return {}

async def fetch_quote():
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, "https://api.quotable.io/random")
        return data.get("content", "No quote available.")

async def fetch_define(word):
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}")
        if isinstance(data, list) and data:
            defs = data[0].get("meanings", [])
            return "\n".join([f"- {m['definitions'][0]['definition']}" for m in defs if m.get("definitions")])
        return "No definition found."

def random_hex_color(): return "#{:06X}".format(random.randint(0,0xFFFFFF))

class DefineModal(ui.Modal, title="Define a Word"):
    word = ui.TextInput(label="Enter word")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        definition = await fetch_define(self.word.value)
        embed = discord.Embed(title=f"Definition: {self.word.value}", description=definition, color=0x00FF00)
        await interaction.followup.send(embed=embed)

class ECMView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ui.Button(label="Fact", style=discord.ButtonStyle.primary, custom_id="fact"))
        self.add_item(ui.Button(label="Useless Fact", style=discord.ButtonStyle.primary, custom_id="useless"))
        self.add_item(ui.Button(label="Color", style=discord.ButtonStyle.secondary, custom_id="color"))
        self.add_item(ui.Button(label="Quote", style=discord.ButtonStyle.success, custom_id="quote"))
        self.add_item(ui.Button(label="Random", style=discord.ButtonStyle.danger, custom_id="random"))
        self.add_item(ui.Button(label="Define", style=discord.ButtonStyle.secondary, custom_id="define"))

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not interaction.type == discord.InteractionType.component: return
    cid = interaction.data.get("custom_id")
    if not cid: return

    if cid=="fact": await interaction.response.send_message("Random Fact: " + random.choice([
        "Cats sleep 70% of their lives.", "Bananas are berries.", "A group of flamingos is called a flamboyance."
    ]))
    elif cid=="useless": await interaction.response.send_message("Useless Fact: " + random.choice([
        "Oxford University is older than the Aztec Empire.", "You cannot burp in space.", "Sharks existed before trees."
    ]))
    elif cid=="color": await interaction.response.send_message(f"Color: {random_hex_color()}")
    elif cid=="quote":
        await interaction.response.defer()
        q = await fetch_quote()
        await interaction.followup.send(embed=discord.Embed(title="Quote", description=q, color=0xFFD700))
    elif cid=="random":
        choice = random.choice(["fact","useless","color","quote"])
        if choice=="fact": await interaction.response.send_message("Random Fact: " + random.choice([
            "Cats sleep 70% of their lives.", "Bananas are berries.", "A group of flamingos is called a flamboyance."
        ]))
        elif choice=="useless": await interaction.response.send_message("Useless Fact: " + random.choice([
            "Oxford University is older than the Aztec Empire.", "You cannot burp in space.", "Sharks existed before trees."
        ]))
        elif choice=="color": await interaction.response.send_message(f"Color: {random_hex_color()}")
        elif choice=="quote":
            await interaction.response.defer()
            q = await fetch_quote()
            await interaction.followup.send(embed=discord.Embed(title="Quote", description=q, color=0xFFD700))
    elif cid=="define":
        await interaction.response.send_modal(DefineModal())

# ---------------------------
# ECM Slash Command
# ---------------------------
@tree.command(name="ecm", description="Open ECM fun menu", guild=discord.Object(id=GUILD_ID))
async def ecm(interaction: discord.Interaction):
    await interaction.response.send_message("ECM Menu", view=ECMView(), ephemeral=True)

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
