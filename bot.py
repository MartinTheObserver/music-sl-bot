import os
import re
import json
import aiohttp
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
from dotenv import load_dotenv
from flask import Flask
import threading
import requests
import random

# ---------------------------
# Environment
# ---------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))
DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID"))

# Load weird laws JSON
try:
    with open("weirdlaws.json", "r") as f:
        WEIRD_LAWS = json.load(f)
except:
    WEIRD_LAWS = [{"law":"No weird laws loaded yet."}]

# ---------------------------
# Flask Server
# ---------------------------
app = Flask(__name__)
@app.route("/")
def home(): return "Bot is alive."

def run_flask(): 
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
threading.Thread(target=run_flask, daemon=True).start()

# ---------------------------
# Bot Setup
# ---------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------------------
# Debug helper
# ---------------------------
async def debug_send(ctx_or_interaction, msg, is_slash=False, ephemeral=True, debug_enabled=True):
    if not debug_enabled: return
    try:
        user = getattr(ctx_or_interaction, "author", None) or getattr(ctx_or_interaction, "user", None)
        if not user or user.id != DEBUG_USER_ID: return
        if is_slash:
            await ctx_or_interaction.followup.send(f"```DEBUG: {msg}```", ephemeral=ephemeral)
        else:
            await ctx_or_interaction.send(f"```DEBUG: {msg}```")
    except Exception as e:
        print(f"[DEBUG ERROR] {e}")

# ---------------------------
# Helpers
# ---------------------------
def clean_song_title(title: str) -> str:
    if not title: return ""
    title = re.sub(r"\(feat\.?.*?\)|\[feat\.?.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\(.*?Remix.*?\)|\[.*?Remix.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[\[\]\(\)]", "", title)
    title = re.sub(r"[^\w\s&'-]", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()

async def fetch_json(session, url, retries=3, delay=2):
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=10) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception:
            if attempt < retries-1: await asyncio.sleep(delay)
            else: return {"error": f"Failed to fetch {url}"}

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
        r.raise_for_status()
        data = r.json()
        hits = data.get("response", {}).get("hits", [])
        for hit in hits:
            result = hit.get("result", {})
            result_title = result.get("title", "").lower()
            result_artist = result.get("primary_artist", {}).get("name", "").lower()
            if clean_title_str.lower() in result_title and artist.lower() in result_artist:
                return result.get("url")
        return hits[0]["result"].get("url") if hits else None
    except: return None

async def fetch_song_links(query: str, ctx_or_interaction=None, is_slash=False):
    try:
        r = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": query, "userCountry": "US"},
            timeout=20
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        if ctx_or_interaction: await debug_send(ctx_or_interaction, f"Song.link error: {e}", is_slash=is_slash)
        return None

# ---------------------------
# Song.link Embed + Add Another Song
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False):
    entity_id = next((uid for uid, e in song_data.get("entitiesByUniqueId", {}).items() if e.get("type")=="song"), None)
    if not entity_id:
        msg = "Could not parse song data."
        await (ctx_or_interaction.send(msg) if not is_slash else ctx_or_interaction.followup.send(msg))
        return
    song = song_data["entitiesByUniqueId"][entity_id]
    title = song.get("title", "Unknown")
    artist = song.get("artistName", "Unknown")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")
    genius_url = get_genius_link(title, artist)
    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    platform_links = "\n".join(f"[{p.replace('_',' ').title()}]({d['url']})" for p,d in platforms if isinstance(d, dict) and "url" in d)

    embed = discord.Embed(
        title=title, url=genius_url,
        description=f"by {artist}\n\n{platform_links}",
        color=0x1DB954
    )
    if thumbnail: embed.set_thumbnail(url=thumbnail)

    class AddSongView(View):
        @discord.ui.button(label="Add Another Song", style=discord.ButtonStyle.success, custom_id="add_song")
        async def add_song_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            class AddSongModal(Modal, title="Add Another Song"):
                song_url = TextInput(label="Song URL", placeholder="Paste Spotify, Apple, or YouTube link")
                async def on_submit(self_inner, interaction_inner: discord.Interaction):
                    await interaction_inner.response.defer()
                    new_data = await fetch_song_links(self_inner.song_url.value, interaction_inner, is_slash=True)
                    if not new_data: await interaction_inner.followup.send("Could not find links."); return
                    await send_songlink_embed(interaction_inner, new_data, is_slash=True)
            await interaction.response.send_modal(AddSongModal())

    if is_slash: await ctx_or_interaction.followup.send(embed=embed, view=AddSongView())
    else: await ctx_or_interaction.send(embed=embed, view=AddSongView())

# ---------------------------
# Prefix / Slash Song.link
# ---------------------------
@bot.command(name="sl")
async def sl_prefix(ctx, *, query: str):
    if ctx.channel.id != ALLOWED_CHANNEL_ID: return
    data = await fetch_song_links(query, ctx)
    if not data: await ctx.send("Could not find links."); return
    await send_songlink_embed(ctx, data, is_slash=False)

@tree.command(name="sl", description="Get song links", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(query="Spotify, Apple, or YouTube link")
async def sl_slash(interaction: discord.Interaction, query: str):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("Not allowed in this channel.", ephemeral=True); return
    await interaction.response.defer()
    data = await fetch_song_links(query, interaction, is_slash=True)
    if not data: await interaction.followup.send("Could not find links."); return
    await send_songlink_embed(interaction, data, is_slash=True)

# ---------------------------
# ECM View & Buttons
# ---------------------------
class ECMView(View):
    def __init__(self):
        super().__init__(timeout=None)
        buttons = [
            ("Quote","💬",discord.ButtonStyle.success),
            ("Fact","🧠",discord.ButtonStyle.primary),
            ("Useless Fact","🤯",discord.ButtonStyle.primary),
            ("Today in History","📜",discord.ButtonStyle.primary),
            ("Wiki","👶",discord.ButtonStyle.primary),
            ("Define","📖",discord.ButtonStyle.primary),
            ("Color","🎨",discord.ButtonStyle.success),
            ("Chaos","🔀",discord.ButtonStyle.danger),
            ("Trivia","❓",discord.ButtonStyle.success),
            ("TimeWarp","⏳",discord.ButtonStyle.success),
            ("Weird Law","⚖️",discord.ButtonStyle.primary)
        ]
        for label, emoji, style in buttons:
            self.add_item(Button(label=label, style=style, custom_id=label.lower().replace(" ",""), emoji=emoji))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        await debug_send(interaction, f"Error in ECM button: {error}", is_slash=True)

# ---------------------------
# ECM button handlers
# ---------------------------
async def ecm_button_handler(interaction: discord.Interaction, button_id: str):
    async with aiohttp.ClientSession() as session:
        if button_id=="quote":
            data = await fetch_json(session,"https://api.quotable.io/random")
            content = f"{data.get('content','No quote')} — {data.get('author','Unknown')}"
        elif button_id=="fact":
            data = await fetch_json(session,"https://uselessfacts.jsph.pl/random.json?language=en")
            content = data.get("text","No fact")
        elif button_id=="uselessfact":
            data = await fetch_json(session,"https://uselessfacts.jsph.pl/random.json?language=en")
            content = data.get("text","No fact")
        elif button_id=="todayinhistory":
            data = await fetch_json(session,"http://history.muffinlabs.com/date")
            events = data.get("data",{}).get("Events",[])
            ev = random.choice(events) if events else {"text":"No events today"}
            content = f"{ev.get('year','')} — {ev.get('text','')}"
        elif button_id=="wiki":
            topic="Example" # Normally ask modal for input
            data = await fetch_json(session,f"https://en.wikipedia.org/api/rest_v1/page/summary/{topic}")
            content = data.get("extract","No summary found")
        elif button_id=="define":
            word="example"
            data = await fetch_json(session,f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}")
            if isinstance(data,list):
                meaning=data[0].get("meanings",[{}])[0].get("definitions",[{}])[0].get("definition","No definition")
                content=f"{word}: {meaning}"
            else: content="No definition found"
        elif button_id=="color":
            hex_val="#%06x"%random.randint(0,0xFFFFFF)
            content=f"Random Color: {hex_val}"
        elif button_id=="chaos":
            quotes = await fetch_json(session,"https://api.quotable.io/random")
            fact = await fetch_json(session,"https://uselessfacts.jsph.pl/random.json?language=en")
            content=f"{quotes.get('content','No quote')}\n— {quotes.get('author','Unknown')}\n\n{fact.get('text','No fact')}"
        elif button_id=="trivia":
            data = await fetch_json(session,"https://opentdb.com/api.php?amount=1&type=multiple")
            if data.get("results"):
                q=data["results"][0]
                content=f"**{q.get('question')}**\nAnswer: {q.get('correct_answer')}"
            else: content="No trivia available"
        elif button_id=="timewarp":
            year=random.randint(1900,2025)
            content=f"Random Year: {year}"
        elif button_id=="weirdlaw":
            content=random.choice(WEIRD_LAWS).get("law","No law")
        else: content="Unknown button"

        embed = discord.Embed(title=button_id.replace("_"," ").title(), description=content, color=0x00ff00)
        await interaction.response.send_message(embed=embed)

# ---------------------------
# ECM Slash
# ---------------------------
@tree.command(name="ecm", description="Open ECM menu", guild=discord.Object(id=GUILD_ID))
async def ecm_slash(interaction: discord.Interaction):
    view = ECMView()
    for item in view.children:
        async def callback(inter, iid=item.custom_id):
            await ecm_button_handler(inter, iid)
        item.callback = callback
    await interaction.response.send_message("Select a command:", view=view, ephemeral=True)

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
