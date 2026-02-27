import os
import re
import random
import discord
from discord.ext import commands
from discord import app_commands, ui
from dotenv import load_dotenv
import threading
from flask import Flask
import requests
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
# Flask Web Server (for Render)
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
# Helper Functions
# ---------------------------
async def debug_send(ctx_or_interaction, msg, is_slash=False):
    user = getattr(ctx_or_interaction, "author", None) or getattr(ctx_or_interaction, "user", None)
    if user and user.id == DEBUG_USER_ID:
        if is_slash: await ctx_or_interaction.followup.send(f"```DEBUG: {msg}```", ephemeral=True)
        else: await ctx_or_interaction.send(f"```DEBUG: {msg}```")

def clean_song_title(title: str) -> str:
    title = re.sub(r"\(feat\.?.*?\)|\[feat\.?.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\(.*?Remix.*?\)|\[.*?Remix.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[\[\]\(\)]", "", title)
    title = re.sub(r"[^\w\s&'-]", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()

# ---------------------------
# Song.link & Genius Helpers
# ---------------------------
async def fetch_song_links(query: str, ctx_or_interaction=None, is_slash=False):
    await debug_send(ctx_or_interaction, f"Fetching Song.link data for query: {query}", is_slash)
    try:
        r = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": query, "userCountry": "US"},
            timeout=20
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        await debug_send(ctx_or_interaction, f"Song.link API error: {e}", is_slash)
        return None

def get_genius_link(title: str, artist: str):
    if not title or not GENIUS_API_KEY: return None
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
            if clean_title_str.lower() in result.get("title", "").lower() and artist.lower() in result.get("primary_artist", {}).get("name", "").lower():
                return result.get("url")
        return hits[0]["result"].get("url") if hits else None
    except:
        return None

async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False):
    entity_id = next((uid for uid, e in song_data.get("entitiesByUniqueId", {}).items() if e.get("type")=="song"), None)
    if not entity_id:
        msg = "Could not parse song data."
        if is_slash: await ctx_or_interaction.followup.send(msg)
        else: await ctx_or_interaction.send(msg)
        return

    song = song_data["entitiesByUniqueId"][entity_id]
    title = song.get("title", "Unknown Title")
    artist = song.get("artistName", "Unknown Artist")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")
    genius_url = get_genius_link(title, artist)

    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    platform_links = "\n".join(
        f"[{p.replace('_',' ').title()}]({d['url']})" for p,d in platforms if isinstance(d, dict) and "url" in d
    )

    chunks = []
    current_chunk = ""
    for line in platform_links.split("\n"):
        if len(current_chunk)+len(line)+1 > 1000:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ("\n" if current_chunk else "") + line
    if current_chunk: chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        embed = discord.Embed(title=title, url=genius_url, description=f"by {artist}", color=0x1DB954)
        if thumbnail: embed.set_thumbnail(url=thumbnail)
        embed.add_field(name="Listen On", value=chunk, inline=False)
        if len(chunks) > 1: embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
        # Add Paste Song button
        view = ui.View()
        view.add_item(PasteSongButton())
        if is_slash: await ctx_or_interaction.followup.send(embed=embed, view=view)
        else: await ctx_or_interaction.send(embed=embed, view=view)

# ---------------------------
# Paste Song Modal & Button
# ---------------------------
class PasteSongModal(ui.Modal, title="Paste a Song"):
    song_url = ui.TextInput(label="Song URL", placeholder="Spotify, YouTube, or Apple Music URL")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        song_data = await fetch_song_links(self.song_url.value, interaction, is_slash=True)
        if not song_data:
            await interaction.followup.send("Could not fetch song links.")
            return
        await send_songlink_embed(interaction, song_data, is_slash=True)

class PasteSongButton(ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.success, label="Paste a Song", emoji="🎵")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PasteSongModal())

# ---------------------------
# Prefix Command (!sl)
# ---------------------------
@bot.command(name="sl")
@commands.guild_only()
async def songlink(ctx, *, query: str):
    if ctx.channel.id != ALLOWED_CHANNEL_ID: return
    song_data = await fetch_song_links(query, ctx, is_slash=False)
    if not song_data: await ctx.send("Could not find links for that song."); return
    await send_songlink_embed(ctx, song_data, is_slash=False)

# ---------------------------
# Slash Command (/sl)
# ---------------------------
@tree.command(name="sl", description="Get song links", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link")
async def slash_songlink(interaction: discord.Interaction, query: str):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("Not allowed in this channel.", ephemeral=True)
        return
    await interaction.response.defer()
    song_data = await fetch_song_links(query, interaction, is_slash=True)
    if not song_data: await interaction.followup.send("Could not find links for that song."); return
    await send_songlink_embed(interaction, song_data, is_slash=True)

# ---------------------------
# ECM Button Helpers
# ---------------------------
async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200: return {"error": True}
            return await resp.json()
    except:
        return {"error": True}

async def fetch_quote(): return (await fetch_json(aiohttp.ClientSession(), "https://api.quotable.io/random")).get("content", "Could not fetch quote.")
async def fetch_fact(): return random.choice(["Honey never spoils.", "Bananas are berries.", "Octopuses have three hearts."])
async def fetch_uselessfact(): return random.choice(["Cows have best friends.", "Sloths can hold their breath longer than dolphins.", "Scotland has 421 words for 'snow'."])
async def fetch_timewarp(): return f"In {random.randint(1900,2023)}: Nothing historically notable yet."
async def fetch_color(): return random.choice(["Red","Blue","Green","Yellow","Purple","Orange","Cyan"])
async def fetch_define(term: str):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{term}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200: return f"⚠️ Unable to fetch definition for '{term}'."
                data = await resp.json()
                meaning = data[0].get("meanings", [])[0]
                definition = meaning.get("definitions", [])[0].get("definition", "No definition found.")
                return definition
    except: return f"⚠️ Error fetching definition."

# ---------------------------
# ECM View
# ---------------------------
class ECMView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        buttons = [("Fact","🧠"), ("Useless Fact","🤯"), ("Timewarp","⏳"), ("Color","🎨"), ("Quote","💬"), ("Random","🔀")]
        for label, emoji in buttons:
            self.add_item(ui.Button(style=discord.ButtonStyle.primary, label=label, emoji=emoji, custom_id=label.lower().replace(" ","")))

# ---------------------------
# ECM Menu Command
# ---------------------------
@tree.command(name="ecm", description="Open ECM menu", guild=discord.Object(id=GUILD_ID))
async def ecm_menu(interaction: discord.Interaction):
    await interaction.response.send_message("Select an option:", view=ECMView(), ephemeral=False)

# ---------------------------
# ECM Button Handler
# ---------------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component: return
    cid = interaction.data.get("custom_id")
    if not cid: return
    await interaction.response.defer()
    if cid=="fact": content = await fetch_fact()
    elif cid=="uselessfact": content = await fetch_uselessfact()
    elif cid=="timewarp": content = await fetch_timewarp()
    elif cid=="color": content = await fetch_color()
    elif cid=="quote": content = await fetch_quote()
    elif cid=="random": content = await random.choice([fetch_fact, fetch_uselessfact, fetch_timewarp, fetch_color, fetch_quote])()
    elif cid=="define": content = await fetch_define(interaction.message.content.split(" ",1)[-1])
    else: content = "Unknown action."
    embed = discord.Embed(title=cid.capitalize(), description=content, color=0x00FF00)
    await interaction.followup.send(embed=embed)

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
