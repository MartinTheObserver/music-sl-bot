import os
import re
import requests
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
import threading
import asyncio
import json
import random
from discord.ui import View, Button

# ---------------------------
# Load Environment Variables
# ---------------------------
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")
API_NINJAS_KEY = os.getenv("API_NINJAS_KEY")
GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))
DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID"))

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
# Load Weird Laws Database
# ---------------------------
with open("weird_laws.json", "r", encoding="utf-8") as f:
    WEIRD_LAWS = json.load(f)

# ---------------------------
# Weird Laws Viewer Class
# ---------------------------
class WeirdLawView(View):
    def __init__(self, laws, index=0):
        super().__init__(timeout=120)
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

    @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index - 1) % len(self.laws)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🎲 Random", style=discord.ButtonStyle.primary)
    async def random_law(self, interaction: discord.Interaction, button: Button):
        self.index = random.randint(0, len(self.laws) - 1)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Next ➡", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index + 1) % len(self.laws)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

# ---------------------------
# ZenQuotes Viewer Class
# ---------------------------
class ZenQuoteView(View):
    def __init__(self, quote_text="", author=""):
        super().__init__(timeout=120)
        self.quote_text = quote_text
        self.author = author

    def create_embed(self):
        embed = discord.Embed(
            title="💬 Random Quote",
            description=f"“{self.quote_text}”\n\n— {self.author}" if self.author else f"“{self.quote_text}”",
            color=discord.Color.green()
        )
        return embed

    @discord.ui.button(label="🎲 New Quote", style=discord.ButtonStyle.primary)
    async def new_quote(self, interaction: discord.Interaction, button: Button):
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
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

# ---------------------------
# Helper: Ephemeral Debug Sender
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
        print(f"[DEBUG ERROR] Could not send debug message: {e}")

# ---------------------------
# Helper: Clean Song Title for Genius Search
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
# Fetch Song.link Data
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
        await debug_send(ctx_or_interaction, f"Song.link API returned keys: {list(data.keys())}", is_slash=is_slash, debug_enabled=debug_enabled)
        return data
    except Exception as e:
        await debug_send(ctx_or_interaction, f"Song.link error: {e}", is_slash=is_slash, debug_enabled=debug_enabled)
        return None

# ---------------------------
# Genius API Helper
# ---------------------------
def get_genius_link(title: str, artist: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
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
        for hit in hits:
            result = hit.get("result", {})
            result_title = result.get("title", "").lower()
            result_artist = result.get("primary_artist", {}).get("name", "").lower()
            if clean_title.lower() in result_title and artist.lower() in result_artist:
                return result.get("url")
        return hits[0]["result"].get("url") if hits else None
    except Exception:
        return None

# ---------------------------
# Send Song.link Embed
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
        if is_slash:
            await ctx_or_interaction.followup.send(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

# ---------------------------
# Random Word Helper (API Ninjas)
# ---------------------------
async def random_word():
    """Fetch a truly random word from API Ninjas."""
    try:
        r = requests.get(
            "https://api.api-ninjas.com/v1/randomword",
            headers={"X-Api-Key": API_NINJAS_KEY},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        return data.get("word", "word")
    except Exception as e:
        print(f"[Random Word Error] {e}")
        return "word"

# ---------------------------
# Dictionary, Related, Etymology Helpers
# ---------------------------
async def dictionary(word):
    r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=10)
    if r.status_code != 200:
        return "N/A", [], []
    data = r.json()[0]
    pronunciation = data.get("phonetics", [{"text": "N/A"}])[0].get("text", "N/A")
    definitions, examples = [], []
    for meaning in data.get("meanings", []):
        for d in meaning.get("definitions", []):
            definitions.append(d.get("definition"))
            if d.get("example"):
                examples.append(d.get("example"))
    return pronunciation, definitions[:10], examples[:6]

async def related(word):
    r = requests.get(f"https://api.datamuse.com/words?ml={word}&max=20", timeout=10)
    return [x["word"] for x in r.json()]

async def etymology(word):
    try:
        r = requests.get(f"https://en.wiktionary.org/w/api.php?action=parse&page={word}&prop=text&format=json", timeout=10)
        html = r.json()["parse"]["text"]["*"]
        m = re.search(r"Etymology.*?<p>(.*?)</p>", html, re.S)
        if m:
            return re.sub("<.*?>", "", m.group(1))
    except:
        pass
    return "Etymology not found."

# ---------------------------
# Word Viewer Class
# ---------------------------
class WordView(View):
    def __init__(self):
        super().__init__(timeout=120)
        self.pages = []
        self.index = 0

    async def generate(self):
        word = await random_word()
        pron, defs, examples = await dictionary(word)
        rel = await related(word)
        ety = await etymology(word)
        self.pages = []

        def chunk(lst, n):
            for i in range(0, len(lst), n):
                yield lst[i:i+n]

        def build_embed(title, content):
            embed = discord.Embed(
                title=word.capitalize(),
                url=f"https://www.google.com/search?q=define+{word}",
                description=f"Pronunciation: {pron}",
                color=discord.Color.blurple()
            )
            embed.add_field(name=title, value=content, inline=False)
            return embed

        for c in chunk(defs, 5):
            self.pages.append(build_embed(f"[Definitions](https://en.wiktionary.org/wiki/{word})", "\n".join(f"• {d}" for d in c)))
        for c in chunk(examples, 4):
            self.pages.append(build_embed(f"[Examples](https://en.wiktionary.org/wiki/{word})", "\n".join(f"• {e}" for e in c)))
        for c in chunk(rel, 8):
            self.pages.append(build_embed(f"[Related Words](https://api.datamuse.com/words?ml={word})", ", ".join(c)))
        self.pages.append(build_embed(f"[Etymology](https://en.wiktionary.org/wiki/{word}#Etymology)", ety[:900]))
        self.index = 0

    @discord.ui.button(label="⬅ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index - 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="➡ Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index + 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="🎲 New Word", style=discord.ButtonStyle.primary)
    async def new_word(self, interaction: discord.Interaction, button: Button):
        await self.generate()
        await interaction.response.edit_message(embed=self.pages[0], view=self)

# ---------------------------
# PREFIX COMMANDS
# ---------------------------
@bot.command(name="word")
async def prefix_word(ctx):
    view = WordView()
    await view.generate()
    await ctx.send(embed=view.pages[0], view=view)

@bot.command(name="weird")
async def prefix_weird(ctx):
    laws_list = list(WEIRD_LAWS.values())
    index = random.randint(0, len(laws_list) - 1)
    view = WeirdLawView(laws_list, index)
    await ctx.send(embed=view.create_embed(), view=view)

@bot.command(name="quote")
async def prefix_quote(ctx):
    try:
        r = requests.get("https://zenquotes.io/api/random", timeout=10)
        r.raise_for_status()
        data = r.json()
        quote_text = data[0].get("q", "No quote found")
        author = data[0].get("a", "")
    except Exception as e:
        quote_text = f"Error fetching quote: {e}"
        author = ""
    view = ZenQuoteView(quote_text, author)
    await ctx.send(embed=view.create_embed(), view=view)

# ---------------------------
# SLASH COMMANDS
# ---------------------------
@tree.command(name="word", description="Discover a random word")
async def slash_word(interaction: discord.Interaction):
    view = WordView()
    await view.generate()
    await interaction.response.send_message(embed=view.pages[0], view=view)

@tree.command(name="weird", description="Browse weird laws from around the world")
async def slash_weird(interaction: discord.Interaction):
    laws_list = list(WEIRD_LAWS.values())
    index = random.randint(0, len(laws_list) - 1)
    view = WeirdLawView(laws_list, index)
    await interaction.response.send_message(embed=view.create_embed(), view=view)

@tree.command(name="quote", description="Get a random quote")
async def slash_quote(interaction: discord.Interaction):
    try:
        r = requests.get("https://zenquotes.io/api/random", timeout=10)
        r.raise_for_status()
        data = r.json()
        quote_text = data[0].get("q", "No quote found")
        author = data[0].get("a", "")
    except Exception as e:
        quote_text = f"Error fetching quote: {e}"
        author = ""
    view = ZenQuoteView(quote_text, author)
    await interaction.response.send_message(embed=view.create_embed(), view=view)

# ---------------------------
# SL PREFIX COMMANDS
# ---------------------------
@bot.command(name="sl")
@commands.guild_only()
@commands.has_permissions(send_messages=True)
async def songlink(ctx, *, query: str):
    debug_enabled = False
    if query.lower().startswith("debug "):
        debug_enabled = True
        query = query[6:].strip()
    if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return
    song_data = await fetch_song_links(query, ctx, is_slash=False, debug_enabled=debug_enabled)
    if not song_data:
        await ctx.send("Could not find links for that song.")
        return
    await send_songlink_embed(ctx, song_data, is_slash=False, debug_enabled=debug_enabled)

@tree.command(name="sl", description="Get song links", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link", debug="Show debug messages for yourself")
async def slash_songlink(interaction: discord.Interaction, query: str, debug: bool = False):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("Not allowed in this channel.", ephemeral=True)
        return
    await interaction.response.defer()
    song_data = await fetch_song_links(query, interaction, is_slash=True, debug_enabled=debug)
    if not song_data:
        await interaction.followup.send("Could not find links for that song.")
        return
    await send_songlink_embed(interaction, song_data, is_slash=True, debug_enabled=debug)

# ---------------------------
# Genius API Test on Startup
# ---------------------------
async def validate_genius_key():
    if not GENIUS_API_KEY:
        print("[Startup Warning] Genius API key not set.")
        return
    try:
        r = requests.get(
            "https://api.genius.com/search",
            params={"q": "Shape of You Ed Sheeran"},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
            timeout=20
        )
        if r.status_code == 401:
            user = await bot.fetch_user(DEBUG_USER_ID)
            await debug_send(user, "Genius API key is invalid (401 Unauthorized)", debug_enabled=True)
        elif r.status_code != 200:
            user = await bot.fetch_user(DEBUG_USER_ID)
            await debug_send(user, f"Genius API returned {r.status_code}: {r.text}", debug_enabled=True)
        else:
            data = r.json()
            hits = data.get("response", {}).get("hits", [])
            user = await bot.fetch_user(DEBUG_USER_ID)
            if hits:
                await debug_send(user, f"Genius API key validated successfully. Found {len(hits)} hit(s) for test search.", debug_enabled=True)
            else:
                await debug_send(user, "Genius API key seems valid but no hits returned for test search.", debug_enabled=True)
    except Exception as e:
        user = await bot.fetch_user(DEBUG_USER_ID)
        await debug_send(user, f"Exception during Genius API validation: {e}", debug_enabled=True)

# ---------------------------
# Bot Ready Event
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")
    asyncio.create_task(validate_genius_key())

# ---------------------------
# Run Bot
# ---------------------------
bot.run(TOKEN)
