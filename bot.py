import os
import re
import json
import requests
import discord
import threading
import asyncio
import random
import base64

from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones
from flask import Flask

# ---------------------------
# Environment Variables (Railway)
# ---------------------------
TOKEN = os.environ["DISCORD_TOKEN"]
GENIUS_API_KEY = os.environ.get("GENIUS_API_KEY")
API_NINJA_RANDOM_WORD_KEY = os.environ.get("API_NINJA_RANDOM_WORD_KEY")
GUILD_ID = int(os.environ["GUILD_ID"])
ALLOWED_CHANNEL_ID = int(os.environ["ALLOWED_CHANNEL_ID"])
DEBUG_USER_ID = int(os.environ.get("DEBUG_USER_ID", 0))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = os.environ.get("GITHUB_FILE", "timezones.json")

# ---------------------------
# Flask server (Railway requirement)
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
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------------------
# Global Timezone DB (GitHub)
# ---------------------------
timezones = {}
timezones_sha = None
timezone_dirty = False
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
github_headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

async def load_timezones_from_github():
    global timezones_sha
    r = requests.get(GITHUB_API, headers=github_headers)
    if r.status_code != 200:
        print("Failed to fetch timezone database.")
        return {}
    data = r.json()
    timezones_sha = data["sha"]
    decoded = json.loads(base64.b64decode(data["content"]).decode())
    return decoded

async def push_timezones_to_github():
    global timezone_dirty, timezones_sha
    if not timezone_dirty: return
    encoded = base64.b64encode(json.dumps(timezones, indent=4).encode()).decode()
    payload = {"message":"Update timezone database","content":encoded,"sha":timezones_sha}
    r = requests.put(GITHUB_API, headers=github_headers, json=payload)
    if r.status_code in [200,201]:
        data = r.json()
        timezones_sha = data["content"]["sha"]
        timezone_dirty = False
        print("Timezone DB synced to GitHub")
    else: print("GitHub update failed")

async def timezone_sync_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(300)
        await push_timezones_to_github()

# ---------------------------
# GeoNames helpers
# ---------------------------
GEONAMES_USER = "martintheobserver"

def search_location(location: str, max_results=10):
    url = f"http://api.geonames.org/searchJSON?q={location}&maxRows={max_results}&username={GEONAMES_USER}"
    res = requests.get(url).json()
    return res.get("geonames", [])

def get_timezone(lat, lng):
    url = f"http://api.geonames.org/timezoneJSON?lat={lat}&lng={lng}&username={GEONAMES_USER}"
    res = requests.get(url).json()
    return res.get("timezoneId")

async def handle_zone(ctx_or_interaction, location: str, is_interaction=False):
    results = search_location(location)
    if not results:
        msg = f"❌ Could not find any matches for `{location}`."
        if is_interaction: await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else: await ctx_or_interaction.send(msg)
        return

    city = results[0]
    tz = get_timezone(city["lat"], city["lng"])
    region = city.get("adminName1")
    region_text = f", {region}" if region else ""
    msg = f"🌍 {city['name']}{region_text}, {city['countryName']} → `{tz}`"
    if is_interaction: await ctx_or_interaction.response.send_message(msg)
    else: await ctx_or_interaction.send(msg)

# ---------------------------
# Timezone Modal & View
# ---------------------------
class TimezoneModal(Modal):
    def __init__(self, user_id):
        super().__init__(title="Set Your Timezone")
        self.user_id = user_id
        self.add_item(TextInput(
            label="Enter your timezone or city",
            placeholder="America/New_York or New York",
            required=True
        ))

    async def on_submit(self, interaction: discord.Interaction):
        global timezone_dirty
        zone = self.children[0].value.strip()
        if zone in available_timezones():
            tz_name = zone
        else:
            matches = [z for z in available_timezones() if zone.lower() in z.lower()]
            tz_name = matches[0] if matches else None

        if not tz_name:
            await interaction.response.send_message("Could not find a matching timezone.", ephemeral=True)
            return

        timezones[str(self.user_id)] = tz_name
        timezone_dirty = True
        await interaction.response.send_message(f"Timezone saved: **{tz_name}**", ephemeral=True)

class TimezoneView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Set Your Timezone", style=discord.ButtonStyle.primary, custom_id="timezone_set")
    async def set_timezone(self, interaction: discord.Interaction, button: Button):
        modal = TimezoneModal(interaction.user.id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Refresh Times", style=discord.ButtonStyle.secondary, custom_id="timezone_refresh")
    async def refresh(self, interaction: discord.Interaction, button: Button):
        embed = await build_timezone_embed(interaction.user, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

async def build_timezone_embed(viewer, guild):
    now = datetime.now().astimezone()
    embed = discord.Embed(title="Server Times", description=f"Last refreshed: {now.strftime('%Y-%m-%d %I:%M %p')}", color=discord.Color.green())
    if not timezones:
        embed.description += "\n\nNo timezones saved yet."
        return embed
    for uid, tz in timezones.items():
        member = guild.get_member(int(uid))
        if not member:
            continue
        try:
            t = datetime.now(ZoneInfo(tz))
            display = t.strftime("%A %I:%M %p")
        except:
            display = "Invalid TZ"
        embed.add_field(name=member.display_name, value=f"{display}\n`{tz}`", inline=True)
    return embed

# ---------------------------
# Load Weird Laws Database
# ---------------------------
with open("weird_laws.json", "r", encoding="utf-8") as f:
    WEIRD_LAWS = json.load(f)

# ---------------------------
# Weird Laws Viewer
# ---------------------------
class WeirdLawView(View):
    def __init__(self, laws, index=0):
        super().__init__(timeout=None)
        self.laws = laws
        self.index = index

    def create_embed(self):
        law = self.laws[self.index]
        embed = discord.Embed(
            title="🌍 Weird Law",
            description=f"**{law['law']}**",
            color=discord.Color.orange()
        )
        embed.add_field(name="Location", value=f"{law['region']}, {law['country']}", inline=False)
        embed.add_field(name="Explanation", value=law["description"], inline=False)
        embed.set_footer(text=f"Source: {law['source']} | #{self.index+1}/{len(self.laws)}")
        return embed

    @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.secondary, custom_id="weirdlaw_prev")
    async def previous(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index - 1) % len(self.laws)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🎲 Random", style=discord.ButtonStyle.primary, custom_id="weirdlaw_random")
    async def random_law(self, interaction: discord.Interaction, button: Button):
        self.index = random.randint(0, len(self.laws) - 1)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Next ➡", style=discord.ButtonStyle.secondary, custom_id="weirdlaw_next")
    async def next(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index + 1) % len(self.laws)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

# ---------------------------
# ZenQuotes Viewer
# ---------------------------
class ZenQuoteView(View):
    def __init__(self, quote_text="", author=""):
        super().__init__(timeout=None)
        self.quote_text = quote_text
        self.author = author

    def create_embed(self):
        embed = discord.Embed(
            title="💬 Random Quote",
            description=f"“{self.quote_text}”\n\n— {self.author}" if self.author else f"“{self.quote_text}”",
            color=discord.Color.green()
        )
        return embed

    async def fetch_new_quote(self):
        try:
            r = requests.get("https://zenquotes.io/api/random", timeout=10)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                self.quote_text = data[0].get("q", "No quote found")
                self.author = data[0].get("a", "")
            else:
                self.quote_text = "No quote found"
                self.author = ""
        except Exception as e:
            self.quote_text = f"Error fetching quote: {e}"
            self.author = ""

    @discord.ui.button(label="🎲 New Quote", style=discord.ButtonStyle.primary, custom_id="quote_new")
    async def new_quote(self, interaction: discord.Interaction, button: Button):
        await self.fetch_new_quote()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

# ---------------------------
# WordView Class
# ---------------------------
class WordView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.pages = []
        self.page_types = []
        self.index = 0

    async def fetch_random_word(self):
        url = "https://api.api-ninjas.com/v1/randomword"
        headers = {"X-Api-Key": API_NINJA_RANDOM_WORD_KEY}
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            word = r.json().get("word", "example")
            if isinstance(word, list): word = word[0]
            return str(word)
        except: return "example"

    async def dictionary(self, word):
        defs, examples, pron = [], [], "N/A"
        try:
            r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=10)
            if r.status_code == 200:
                data = r.json()[0]
                if data.get("phonetics"):
                    pron = data["phonetics"][0].get("text", "N/A")
                for meaning in data.get("meanings", []):
                    for d in meaning.get("definitions", []):
                        defs.append(d.get("definition"))
                        if d.get("example"):
                            examples.append(d.get("example"))
        except: pass
        return pron, defs[:10], examples[:8]

    async def generate(self):
        word = await self.fetch_random_word()
        pron, defs, examples = await self.dictionary(word)
        self.pages = []
        self.page_types = []

        embed = discord.Embed(
            title=word.capitalize(),
            description=f"Pronunciation: {pron}",
            color=discord.Color.blurple()
        )
        if defs: embed.add_field(name="Definitions", value="\n".join(f"• {d}" for d in defs), inline=False)
        if examples: embed.add_field(name="Examples", value="\n".join(f"• {e}" for e in examples), inline=False)
        self.pages.append(embed)
        self.index = 0

    @discord.ui.button(label="🎲 Random Word", style=discord.ButtonStyle.primary, custom_id="word_random")
    async def new_word(self, interaction: discord.Interaction, button: Button):
        await self.generate()
        await interaction.response.edit_message(embed=self.pages[0], view=self)

# ---------------------------
# Song.link Helpers
# ---------------------------
def clean_song_title(title: str) -> str:
    if not title: return ""
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
    except Exception as e:
        if is_slash:
            await ctx_or_interaction.followup.send(f"Error fetching song data: {e}")
        else:
            await ctx_or_interaction.send(f"Error fetching song data: {e}")
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
    except: return None

async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False):
    entity_id = None
    for uid, entity in song_data.get("entitiesByUniqueId", {}).items():
        if entity.get("type") == "song":
            entity_id = uid
            break
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
        f"[{platform.replace('_',' ').title()}]({data['url']})"
        for platform, data in platforms
        if isinstance(data, dict) and "url" in data
    )

    # Split into 1000-char chunks
    chunks, current_chunk = [], ""
    for line in platform_links.split("\n"):
        if len(current_chunk) + len(line) + 1 > 1000:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ("\n" if current_chunk else "") + line
    if current_chunk: chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=title,
            url=genius_url if genius_url else None,
            description=f"by {artist}",
            color=0x1DB954
        )
        if thumbnail: embed.set_thumbnail(url=thumbnail)
        embed.add_field(name="Listen On", value=chunk, inline=False)
        if len(chunks) > 1: embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
        if is_slash: await ctx_or_interaction.followup.send(embed=embed)
        else: await ctx_or_interaction.send(embed=embed)

# ---------------------------
# Prefix and Slash Commands (word, weird, quote, sl)
# ---------------------------
@bot.command(name="word")
async def prefix_word(ctx):
    view = WordView()
    await view.generate()
    await ctx.send(embed=view.pages[0], view=view)

@tree.command(name="word", description="Discover a random word")
async def slash_word(interaction: discord.Interaction):
    view = WordView()
    await view.generate()
    await interaction.response.send_message(embed=view.pages[0], view=view)

@bot.command(name="weird")
async def prefix_weird(ctx):
    laws_list = list(WEIRD_LAWS.values())
    if not laws_list:
        await ctx.send("Weird laws database is empty.")
        return
    view = WeirdLawView(laws_list)
    await ctx.send(embed=view.create_embed(), view=view)

@tree.command(name="weird", description="Random weird law", guild=discord.Object(id=GUILD_ID))
async def slash_weird(interaction: discord.Interaction):
    laws_list = list(WEIRD_LAWS.values())
    if not laws_list:
        await interaction.response.send_message("Weird laws database is empty.", ephemeral=True)
        return
    view = WeirdLawView(laws_list)
    await interaction.response.send_message(embed=view.create_embed(), view=view)

@bot.command(name="quote")
async def prefix_quote(ctx):
    view = ZenQuoteView()
    await view.fetch_new_quote()
    await ctx.send(embed=view.create_embed(), view=view)

@tree.command(name="quote", description="Random inspirational quote", guild=discord.Object(id=GUILD_ID))
async def slash_quote(interaction: discord.Interaction):
    view = ZenQuoteView()
    await view.fetch_new_quote()
    await interaction.response.send_message(embed=view.create_embed(), view=view)

@bot.command(name="sl")
async def songlink_prefix(ctx, *, query: str):
    if ctx.channel.id != ALLOWED_CHANNEL_ID: return
    song_data = await fetch_song_links(query, ctx, is_slash=False)
    if not song_data: await ctx.send("Could not find links for that song."); return
    await send_songlink_embed(ctx, song_data, is_slash=False)

@tree.command(name="sl", description="Get song links", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link")
async def songlink_slash(interaction: discord.Interaction, query: str):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("Not allowed in this channel.", ephemeral=True)
        return
    await interaction.response.defer()
    song_data = await fetch_song_links(query, interaction, is_slash=True)
    if not song_data: await interaction.followup.send("Could not find links for that song."); return
    await send_songlink_embed(interaction, song_data, is_slash=True)

# ---------------------------
# Bot on_ready
# ---------------------------
@bot.event
async def on_ready():
    global timezones
    print(f"Logged in as {bot.user}")

    # Load timezone DB from GitHub
    if GITHUB_TOKEN and GITHUB_REPO:
        timezones = await load_timezones_from_github()
        bot.loop.create_task(timezone_sync_loop())

    # Add persistent views
    bot.add_view(WordView())
    bot.add_view(ZenQuoteView())
    bot.add_view(WeirdLawView(list(WEIRD_LAWS.values())))
    bot.add_view(TimezoneView())

    await tree.sync()
    print("Commands synced.")

# ---------------------------
# Run Bot
# ---------------------------
bot.run(TOKEN)