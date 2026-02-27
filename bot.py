import os
import re
import json
import requests
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
import threading
import asyncio
from discord.ui import View, Button, Modal, TextInput
import datetime
import aiohttp
import random

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
WEIRD_LAWS_FILE = "weirdlaws.json"
if os.path.exists(WEIRD_LAWS_FILE):
    with open(WEIRD_LAWS_FILE, "r") as f:
        WEIRD_LAWS = json.load(f)
else:
    WEIRD_LAWS = [
        "In Switzerland, it is illegal to own just one guinea pig.",
        "In Alabama, it is illegal to wear a fake mustache in church.",
        "In Samoa, it is illegal to forget your wife's birthday."
    ]

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
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------------------
# Helper: Ephemeral Debug Sender
# ---------------------------
async def debug_send(ctx_or_interaction, msg, is_slash=False, ephemeral=True, debug_enabled=True):
    if not debug_enabled:
        return
    try:
        user = await bot.fetch_user(DEBUG_USER_ID)
        await user.send(f"[DEBUG] {msg}")
    except Exception as e:
        print(f"[DEBUG ERROR] {e}")

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

async def fetch_song_links(query: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    await debug_send(ctx_or_interaction, f"Fetching Song.link data for {query}", is_slash=is_slash, debug_enabled=debug_enabled)
    try:
        r = requests.get("https://api.song.link/v1-alpha.1/links", params={"url": query, "userCountry": "US"}, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data
    except Exception as e:
        await debug_send(ctx_or_interaction, f"Song.link error: {e}", is_slash=is_slash, debug_enabled=debug_enabled)
        return None

def get_genius_link(title: str, artist: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    if not title or not GENIUS_API_KEY:
        return None
    clean_title_text = clean_song_title(title)
    query = f"{clean_title_text} {artist}"
    try:
        r = requests.get("https://api.genius.com/search", params={"q": query}, headers={"Authorization": f"Bearer {GENIUS_API_KEY}"}, timeout=20)
        data = r.json()
        hits = data.get("response", {}).get("hits", [])
        for hit in hits:
            result = hit.get("result", {})
            result_title = result.get("title", "").lower()
            result_artist = result.get("primary_artist", {}).get("name", "").lower()
            if clean_title_text.lower() in result_title and artist.lower() in result_artist:
                return result.get("url")
        return hits[0]["result"].get("url") if hits else None
    except Exception as e:
        asyncio.create_task(debug_send(ctx_or_interaction, f"Genius API error: {e}", is_slash=is_slash, debug_enabled=debug_enabled))
        return None

async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False, debug_enabled=True):
    entity_id = next((uid for uid, e in song_data.get("entitiesByUniqueId", {}).items() if e.get("type")=="song"), None)
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
    platform_links = "\n".join(f"[{p.replace('_',' ').title()}]({d['url']})" for p,d in platforms if isinstance(d, dict) and "url" in d)
    chunks = []
    current = ""
    for line in platform_links.split("\n"):
        if len(current)+len(line)+1>1000:
            chunks.append(current)
            current=line
        else:
            current += ("\n" if current else "") + line
    if current: chunks.append(current)
    for i,chunk in enumerate(chunks):
        embed = discord.Embed(title=title, url=genius_url, description=f"by {artist}", color=0x1DB954)
        if thumbnail: embed.set_thumbnail(url=thumbnail)
        embed.add_field(name="Listen On", value=chunk, inline=False)
        if len(chunks)>1: embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
        if is_slash:
            await ctx_or_interaction.followup.send(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

# ---------------------------
# !sl Command
# ---------------------------
@bot.command(name="sl")
@commands.guild_only()
async def songlink(ctx, *, query:str):
    debug_enabled=False
    if query.lower().startswith("debug "):
        debug_enabled=True
        query=query[6:].strip()
    if ctx.channel.id!=ALLOWED_CHANNEL_ID:
        return
    song_data=await fetch_song_links(query,ctx,is_slash=False,debug_enabled=debug_enabled)
    if not song_data:
        await ctx.send("Could not find links for that song.")
        return
    await send_songlink_embed(ctx,song_data,is_slash=False,debug_enabled=debug_enabled)

# ---------------------------
# /sl Command
# ---------------------------
@tree.command(name="sl", description="Get song links", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link", debug="Show debug messages for yourself")
async def slash_songlink(interaction:discord.Interaction, query:str, debug:bool=False):
    if interaction.channel_id!=ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("Not allowed in this channel.", ephemeral=True)
        return
    await interaction.response.defer()
    song_data=await fetch_song_links(query, interaction, is_slash=True, debug_enabled=debug)
    if not song_data:
        await interaction.followup.send("Could not find links for that song.")
        return
    await send_songlink_embed(interaction, song_data, is_slash=True, debug_enabled=debug)

# ---------------------------
# ECM Free APIs
# ---------------------------
async def fetch_json(session,url):
    async with session.get(url) as resp:
        if resp.status!=200: return None
        return await resp.json()

async def fetch_fact(): 
    async with aiohttp.ClientSession() as session:
        data=await fetch_json(session,"https://uselessfacts.jsph.pl/random.json?language=en")
        return data.get("text","Could not fetch fact.") if data else "Could not fetch fact."

async def fetch_trivia():
    async with aiohttp.ClientSession() as session:
        data=await fetch_json(session,"https://opentdb.com/api.php?amount=1&type=multiple")
        if data and data.get("results"):
            q=data["results"][0]
            return f"**{q['question']}**\n||{q['correct_answer']}||"
        return "Could not fetch trivia."

async def fetch_today_in_history():
    today=datetime.datetime.utcnow()
    url=f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{today.month}/{today.day}"
    async with aiohttp.ClientSession() as session:
        data=await fetch_json(session,url)
        if data and data.get("events"):
            events=data["events"][:3]
            return "\n".join(f"**{e['year']}** - {e['text']}" for e in events)
        return "Could not fetch today in history."

async def fetch_eli5(topic):
    async with aiohttp.ClientSession() as session:
        url=f"https://en.wikipedia.org/api/rest_v1/page/summary/{topic}"
        data=await fetch_json(session,url)
        if data and data.get("extract"):
            return data["extract"]
        return f"Could not find an ELI5 for '{topic}'."

async def fetch_define(term):
    async with aiohttp.ClientSession() as session:
        url=f"https://en.wikipedia.org/api/rest_v1/page/summary/{term}"
        data=await fetch_json(session,url)
        if data and data.get("extract"):
            return data["extract"].split(".")[0]+"."
        return f"Could not define '{term}'."

async def fetch_quote():
    async with aiohttp.ClientSession() as session:
        data=await fetch_json(session,"https://api.quotable.io/random")
        if data:
            return f'"{data.get("content")}" — {data.get("author")}'
        return "Could not fetch a quote."

async def fetch_weirdlaw():
    return random.choice(WEIRD_LAWS)

async def fetch_timewarp(year):
    async with aiohttp.ClientSession() as session:
        url=f"https://en.wikipedia.org/api/rest_v1/page/summary/{year}"
        data=await fetch_json(session,url)
        if data and data.get("extract"):
            return "\n".join(data["extract"].split(".")[:3])
        return f"No events found for {year}."

async def fetch_color_info(query):
    named_colors={"red":"#FF0000","green":"#00FF00","blue":"#0000FF","orange":"#FF8800"}
    hex_code=query if query.startswith("#") else named_colors.get(query.lower(),"#FFFFFF")
    return f"**Color:** {hex_code}"

async def fetch_chaos():
    return random.choice([
        await fetch_fact(),
        await fetch_trivia(),
        await fetch_today_in_history(),
        await fetch_quote(),
        await fetch_weirdlaw()
    ])

# ---------------------------
# ECM Modals
# ---------------------------
class ELI5Modal(Modal,title="ELI5 - What should I explain?"):
    topic=TextInput(label="Topic", placeholder="e.g., black holes", required=True)
    async def on_submit(self, interaction:discord.Interaction):
        result=await fetch_eli5(self.topic.value)
        embed=discord.Embed(title=f"🧠 ELI5: {self.topic.value}", description=result, color=0x1F8B4C)
        await interaction.response.edit_message(embed=embed, view=self.view)

class DefineModal(Modal,title="Define a term"):
    term=TextInput(label="Term", placeholder="e.g., gaslighting", required=True)
    async def on_submit(self, interaction:discord.Interaction):
        result=await fetch_define(self.term.value)
        embed=discord.Embed(title=f"📚 Define: {self.term.value}", description=result, color=0x3498DB)
        await interaction.response.edit_message(embed=embed, view=self.view)

class TimewarpModal(Modal,title="Timewarp - Enter a year or era"):
    year=TextInput(label="Year/Era", placeholder="e.g., 1999, 1800s", required=True)
    async def on_submit(self, interaction:discord.Interaction):
        result=await fetch_timewarp(self.year.value)
        embed=discord.Embed(title=f"⏳ Timewarp: {self.year.value}", description=result, color=0x9B59B6)
        await interaction.response.edit_message(embed=embed, view=self.view)

class ColorModal(Modal,title="Color Info"):
    query=TextInput(label="Color Hex or Name", placeholder="#FF8800 or orange", required=True)
    async def on_submit(self, interaction:discord.Interaction):
        result=await fetch_color_info(self.query.value)
        embed=discord.Embed(title=f"🎨 Color Info: {self.query.value}", description=result, color=0xE67E22)
        await interaction.response.edit_message(embed=embed, view=self.view)

# ---------------------------
# ECM Button View (full)
# ---------------------------
class ECMView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fact", style=discord.ButtonStyle.primary, emoji="🧠")
    async def fact_button(self, interaction:discord.Interaction, button:Button):
        result=await fetch_fact()
        embed=discord.Embed(title="🧠 Fact", description=result, color=0x1F8B4C)
        await interaction.response.edit_message(embed=embed, view=self)
        await debug_send(interaction,f"Fact fetched: {result}")

    @discord.ui.button(label="Trivia", style=discord.ButtonStyle.success, emoji="🎲")
    async def trivia_button(self, interaction:discord.Interaction, button:Button):
        result=await fetch_trivia()
        embed=discord.Embed(title="🎲 Trivia", description=result, color=0x2ECC71)
        await interaction.response.edit_message(embed=embed, view=self)
        await debug_send(interaction,f"Trivia fetched: {result}")

    @discord.ui.button(label="Today in History", style=discord.ButtonStyle.secondary, emoji="📜")
    async def history_button(self, interaction:discord.Interaction, button:Button):
        result=await fetch_today_in_history()
        embed=discord.Embed(title="📜 Today in History", description=result, color=0xF1C40F)
        await interaction.response.edit_message(embed=embed, view=self)
        await debug_send(interaction,f"Today in history fetched: {result}")

    @discord.ui.button(label="ELI5", style=discord.ButtonStyle.primary, emoji="👶")
    async def eli5_button(self, interaction:discord.Interaction, button:Button):
        await interaction.response.send_modal(ELI5Modal())

    @discord.ui.button(label="Define", style=discord.ButtonStyle.primary, emoji="📚")
    async def define_button(self, interaction:discord.Interaction, button:Button):
        await interaction.response.send_modal(DefineModal())

    @discord.ui.button(label="Quote", style=discord.ButtonStyle.success, emoji="💬")
    async def quote_button(self, interaction:discord.Interaction, button:Button):
        result=await fetch_quote()
        embed=discord.Embed(title="💬 Quote", description=result, color=0x9B59B6)
        await interaction.response.edit_message(embed=embed, view=self)
        await debug_send(interaction,f"Quote fetched: {result}")

    @discord.ui.button(label="Weird Law", style=discord.ButtonStyle.secondary, emoji="⚖️")
    async def law_button(self, interaction:discord.Interaction, button:Button):
        result=await fetch_weirdlaw()
        embed=discord.Embed(title="⚖️ Weird Law", description=result, color=0xE74C3C)
        await interaction.response.edit_message(embed=embed, view=self)
        await debug_send(interaction,f"Weird law fetched: {result}")

    @discord.ui.button(label="Timewarp", style=discord.ButtonStyle.primary, emoji="⏳")
    async def timewarp_button(self, interaction:discord.Interaction, button:Button):
        await interaction.response.send_modal(TimewarpModal())

    @discord.ui.button(label="Color", style=discord.ButtonStyle.secondary, emoji="🎨")
    async def color_button(self, interaction:discord.Interaction, button:Button):
        await interaction.response.send_modal(ColorModal())

    @discord.ui.button(label="Chaos", style=discord.ButtonStyle.danger, emoji="🔀")
    async def chaos_button(self, interaction:discord.Interaction, button:Button):
        result=await fetch_chaos()
        embed=discord.Embed(title="🔀 Chaos", description=result, color=0x34495E)
        await interaction.response.edit_message(embed=embed, view=self)
        await debug_send(interaction,f"Chaos fetched: {result}")

# ---------------------------
# ECM Command
# ---------------------------
@tree.command(name="ecm", description="Open ECM interactive panel", guild=discord.Object(id=GUILD_ID))
async def ecm_panel(interaction:discord.Interaction):
    view=ECMView()
    embed=discord.Embed(title="E.C.M Entertainment Panel", description="Click buttons below for fun interactions!", color=0x8E44AD)
    await interaction.response.send_message(embed=embed, view=view)

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
