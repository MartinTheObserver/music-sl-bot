import os
import re
import json
import random
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
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
try:
    with open("weirdlaws.json", "r", encoding="utf-8") as f:
        WEIRD_LAWS = json.load(f)
except FileNotFoundError:
    WEIRD_LAWS = [{"law": "No weird laws loaded."}]

# ---------------------------
# Flask Server for Keep-Alive
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
# Helper: Debug
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
# Async Fetch JSON
# ---------------------------
async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=15) as resp:
            return await resp.json()
    except Exception as e:
        print(f"[FETCH JSON ERROR] {e}")
        return None

# ---------------------------
# Fetch Song.link Data
# ---------------------------
async def fetch_song_links(query: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    await debug_send(ctx_or_interaction, f"Fetching Song.link for: {query}", is_slash=is_slash, debug_enabled=debug_enabled)
    try:
        r = await asyncio.to_thread(lambda: __import__("requests").get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": query, "userCountry": "US"},
            timeout=20
        ))
        r.raise_for_status()
        return r.json()
    except Exception as e:
        await debug_send(ctx_or_interaction, f"Song.link fetch error: {e}", is_slash=is_slash, debug_enabled=debug_enabled)
        return None

# ---------------------------
# Genius Link Fetch
# ---------------------------
def get_genius_link(title: str, artist: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    if not title or not GENIUS_API_KEY:
        return None
    clean_title = clean_song_title(title)
    query = f"{clean_title} {artist}"
    try:
        import requests
        r = requests.get(
            "https://api.genius.com/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
            timeout=20
        )
        data = r.json()
        hits = data.get("response", {}).get("hits", [])
        if hits:
            for hit in hits:
                result = hit.get("result", {})
                if clean_title.lower() in result.get("title", "").lower() and artist.lower() in result.get("primary_artist", {}).get("name","").lower():
                    return result.get("url")
            return hits[0]["result"].get("url")
        return None
    except Exception as e:
        asyncio.create_task(debug_send(ctx_or_interaction, f"Genius fetch error: {e}", is_slash=is_slash, debug_enabled=debug_enabled))
        return None

# ---------------------------
# Song.link Embed Sender
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False, debug_enabled=True):
    entity_id = None
    for uid, entity in song_data.get("entitiesByUniqueId", {}).items():
        if entity.get("type") == "song":
            entity_id = uid
            break
    if not entity_id:
        msg = "Could not parse song data."
        await (ctx_or_interaction.followup.send if is_slash else ctx_or_interaction.send)(msg)
        return
    song = song_data["entitiesByUniqueId"][entity_id]
    title = song.get("title","Unknown Title")
    artist = song.get("artistName","Unknown Artist")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")
    genius_url = get_genius_link(title, artist, ctx_or_interaction, is_slash, debug_enabled)
    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    platform_links = "\n".join(f"[{k.replace('_',' ').title()}]({v.get('url')})" for k,v in platforms if isinstance(v, dict) and "url" in v)

    # Chunk into pages if too long
    chunks = []
    current_chunk = ""
    for line in platform_links.split("\n"):
        if len(current_chunk)+len(line)+1>1000:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ("\n" if current_chunk else "") + line
    if current_chunk: chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=title,
            url=genius_url,
            description=f"by {artist}\n\n{chunk}"[:4000],
            color=0x1DB954
        )
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if len(chunks)>1:
            embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
        await (ctx_or_interaction.followup.send if is_slash else ctx_or_interaction.send)(embed=embed)
    
    # Add "Add Another Song" button
    view = View()
    view.add_item(Button(label="Add Another Song", style=discord.ButtonStyle.primary, custom_id="add_song"))
    await (ctx_or_interaction.followup.send if is_slash else ctx_or_interaction.send)("Add another song using the button:", view=view)

# ---------------------------
# Prefix !sl Command
# ---------------------------
@bot.command(name="sl")
@commands.guild_only()
async def songlink(ctx, *, query: str):
    if ctx.channel.id != ALLOWED_CHANNEL_ID: return
    song_data = await fetch_song_links(query, ctx)
    if not song_data:
        await ctx.send("Could not find links for that song.")
        return
    await send_songlink_embed(ctx, song_data)

# ---------------------------
# Slash /sl Command
# ---------------------------
@tree.command(name="sl", description="Get song links", guild=discord.Object(id=GUILD_ID))
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
# ECM View Buttons
# ---------------------------
class ECMView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Fact", style=discord.ButtonStyle.secondary, custom_id="fact", emoji="🧠"))
        self.add_item(Button(label="UselessFact", style=discord.ButtonStyle.secondary, custom_id="uselessfact", emoji="🤔"))
        self.add_item(Button(label="TimeWarp", style=discord.ButtonStyle.primary, custom_id="timewarp", emoji="⏳"))
        self.add_item(Button(label="Define", style=discord.ButtonStyle.success, custom_id="define", emoji="📖"))
        self.add_item(Button(label="Quote", style=discord.ButtonStyle.success, custom_id="quote", emoji="💬"))
        self.add_item(Button(label="Chaos", style=discord.ButtonStyle.danger, custom_id="chaos", emoji="🔀"))
        self.add_item(Button(label="Color", style=discord.ButtonStyle.secondary, custom_id="color", emoji="🎨"))
        self.add_item(Button(label="WeirdLaw", style=discord.ButtonStyle.primary, custom_id="weirdlaw", emoji="⚖️"))

# ---------------------------
# Button Callbacks
# ---------------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not interaction.data or "custom_id" not in interaction.data: return
    cid = interaction.data["custom_id"]
    async with aiohttp.ClientSession() as session:
        if cid=="fact":
            data = await fetch_json(session, "https://uselessfacts.jsph.pl/random.json?language=en")
            embed = discord.Embed(title="Random Fact", description=data.get("text","No fact available")[:4000], color=0x00FF00)
            await interaction.response.send_message(embed=embed)
        elif cid=="uselessfact":
            data = await fetch_json(session, "https://uselessfacts.jsph.pl/random.json?language=en")
            embed = discord.Embed(title="Useless Fact", description=data.get("text","No fact")[:4000], color=0x00FF00)
            await interaction.response.send_message(embed=embed)
        elif cid=="timewarp":
            year = random.randint(1000,2025)
            data = await fetch_json(session, f"http://history.muffinlabs.com/date")
            desc = f"Random Year: {year}\nFacts:\n"
            facts = data.get("data", {}).get("Events", [])
            facts = [f"{f['year']}: {f['text']}" for f in facts if int(f['year'])==year]
            if not facts: facts=["No historical facts for this year."]
            embed = discord.Embed(title="TimeWarp", description="\n".join(facts)[:4000], color=0xFFD700)
            await interaction.response.send_message(embed=embed)
        elif cid=="define":
            modal = Modal(title="Define a Term")
            modal.term_input = TextInput(label="Term", placeholder="Enter term to define", style=discord.TextStyle.short)
            modal.add_item(modal.term_input)
            async def modal_callback(interaction2: discord.Interaction):
                term = modal.term_input.value
                async with aiohttp.ClientSession() as s2:
                    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{term}"
                    data2 = await fetch_json(s2,url)
                    desc = data2.get("extract","No definition found.")[:4000]
                    embed = discord.Embed(title=f"Definition: {term}", description=desc, color=0x00FFFF)
                    await interaction2.response.send_message(embed=embed)
            modal.on_submit = modal_callback
            await interaction.response.send_modal(modal)
        elif cid=="quote":
            data = await fetch_json(session,"https://api.quotable.io/random")
            embed = discord.Embed(title="Quote", description=f"{data.get('content','No quote')} — {data.get('author','Unknown')}"[:4000], color=0x8A2BE2)
            await interaction.response.send_message(embed=embed)
        elif cid=="chaos":
            # Combine random outputs
            data = await fetch_json(session,"https://api.quotable.io/random")
            embed = discord.Embed(title="Chaos", description=f"Quote: {data.get('content','No quote')}\nAuthor: {data.get('author','Unknown')}"[:4000], color=0xFF4500)
            await interaction.response.send_message(embed=embed)
        elif cid=="color":
            color = "%06x" % random.randint(0,0xFFFFFF)
            embed = discord.Embed(title="Random Color", description=f"Hex: #{color}", color=int(color,16))
            await interaction.response.send_message(embed=embed)
        elif cid=="weirdlaw":
            law = random.choice(WEIRD_LAWS).get("law","No law found.")
            embed = discord.Embed(title="Weird Law", description=law[:4000], color=0xFF69B4)
            await interaction.response.send_message(embed=embed)
        elif cid=="add_song":
            modal = Modal(title="Add Another Song")
            modal.song_input = TextInput(label="Song URL", placeholder="Paste link here", style=discord.TextStyle.short)
            modal.add_item(modal.song_input)
            async def song_modal_callback(interaction2: discord.Interaction):
                url = modal.song_input.value
                song_data = await fetch_song_links(url, interaction2, is_slash=True)
                if not song_data:
                    await interaction2.response.send_message("Could not find links for that song.")
                    return
                await send_songlink_embed(interaction2, song_data, is_slash=True)
            modal.on_submit = song_modal_callback
            await interaction.response.send_modal(modal)

# ---------------------------
# Bot Ready
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
