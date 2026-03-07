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
GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))
DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID"))  # Your Discord ID for ephemeral debug

# API Ninja key for random word
API_NINJA_RANDOM_WORD_KEY = os.getenv("API_NINJA_RANDOM_WORD_KEY")

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
intents.message_content = True  # REQUIRED for prefix commands

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

    # Helper method for prefix commands (ctx)
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

    # Button callback (slash or UI)
    @discord.ui.button(label="🎲 New Quote", style=discord.ButtonStyle.primary)
    async def new_quote(self, interaction: discord.Interaction, button: Button):
        await self.fetch_new_quote()
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
# ---------------------------
# WORD FEATURE (NEW)
# ---------------------------
class WordView(View):
    def __init__(self):
        super().__init__(timeout=180)
        self.pages = []
        self.page_types = []
        self.index = 0

    async def fetch_random_word(self):
        url = "https://api.api-ninjas.com/v1/randomword"
        headers = {"X-Api-Key": API_NINJA_RANDOM_WORD_KEY}
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            return r.json().get("word", None)
        except Exception as e:
            print(f"[WordView] Random word fetch failed: {e}")
            return None

    async def dictionary(self, word):
        try:
            r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=10)
            if r.status_code == 200:
                data = r.json()[0]
                pron = "N/A"
                if data.get("phonetics"):
                    pron = data["phonetics"][0].get("text", "N/A")
                defs, examples = [], []
                for meaning in data.get("meanings", []):
                    for d in meaning.get("definitions", []):
                        defs.append(d.get("definition"))
                        if d.get("example"):
                            examples.append(d.get("example"))
                return pron, defs[:10], examples[:6]
        except:
            pass
        try:
            r = requests.get(f"https://api.datamuse.com/words?sp={word}&md=d&max=1", timeout=10)
            data = r.json()
            defs = []
            if data and "defs" in data[0]:
                defs = [d.split("\t")[1] for d in data[0]["defs"]]
            return "N/A", defs[:10], []
        except:
            return "N/A", [], []

    async def related_words(self, word):
        try:
            r = requests.get(f"https://api.datamuse.com/words?ml={word}&max=20", timeout=10)
            return [x["word"] for x in r.json()]
        except:
            return []

    async def etymology(self, word):
        try:
            r = requests.get(f"https://en.wiktionary.org/w/api.php?action=parse&page={word}&prop=text&format=json", timeout=10)
            html = r.json()["parse"]["text"]["*"]
            m = re.search(r"Etymology.*?<p>(.*?)</p>", html, re.S)
            if m:
                text = re.sub("<.*?>", "", m.group(1))
                return text[:900]
        except:
            pass
        return "Etymology not found."

    async def generate(self):
        word = await self.fetch_random_word()
        if not word:
            word = "example"
        pron, defs, examples = await self.dictionary(word)
        rel = await self.related_words(word)
        ety = await self.etymology(word)
        self.pages = []
        self.page_types = []

        def build_embed(embed_word, title, content):
            embed = discord.Embed(
                title=embed_word.capitalize() if isinstance(embed_word, str) else str(embed_word),
                url=f"https://www.google.com/search?q=define+{word}",
                description=f"Pronunciation: {pron}",
                color=discord.Color.blurple()
            )
            embed.add_field(name=title, value=content or "N/A", inline=False)
            return embed

        if defs:
            self.pages.append(build_embed(word, "Definitions", "\n".join(f"• {d}" for d in defs)))
            self.page_types.append("Definitions")
        if examples:
            self.pages.append(build_embed(word, "Examples", "\n".join(f"• {e}" for e in examples)))
            self.page_types.append("Examples")
        if rel:
            self.pages.append(build_embed(word, "Related Words", ", ".join(rel[:15])))
            self.page_types.append("Related Words")
        self.pages.append(build_embed(word, "Etymology", ety))
        self.page_types.append("Etymology")

        self.index = 0
        for i, embed in enumerate(self.pages):
            next_type = self.page_types[i+1] if i+1 < len(self.pages) else "End"
            embed.set_footer(text=f"Page {i+1}/{len(self.pages)} | Next: {next_type}")

    @discord.ui.button(label="⬅ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index - 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

@discord.ui.button(label="🎲 Random Word", style=discord.ButtonStyle.primary)
    async def new_word(self, interaction: discord.Interaction, button: Button):
        await self.generate()
        await interaction.response.edit_message(embed=self.pages[0], view=self)
    
    @discord.ui.button(label="➡ Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index + 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

# ---------------------------
# Prefix Command: !word
# ---------------------------
@bot.command(name="word")
async def prefix_word(ctx):
    view = WordView()
    await view.generate()
    await ctx.send(embed=view.pages[0], view=view)

# ---------------------------
# Slash Command: /word
# ---------------------------
@tree.command(name="word", description="Discover a random word")
async def slash_word(interaction: discord.Interaction):
    view = WordView()
    await view.generate()
    await interaction.response.send_message(embed=view.pages[0], view=view)

# ---------------------------
# Prefix Command: !sl
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

# ---------------------------
# Slash Command: /sl
# ---------------------------
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
# Prefix Command: !weird
# ---------------------------
@bot.command(name="weird")
async def prefix_weird(ctx):
    laws_list = list(WEIRD_LAWS.values())
    if not laws_list:
        await ctx.send("Weird laws database is empty.")
        return
    view = WeirdLawView(laws_list)
    await ctx.send(embed=view.create_embed(), view=view)

# ---------------------------
# Slash Command: /weird
# ---------------------------
@tree.command(name="weird", description="Random weird law", guild=discord.Object(id=GUILD_ID))
async def slash_weird(interaction: discord.Interaction):
    laws_list = list(WEIRD_LAWS.values())
    if not laws_list:
        await interaction.response.send_message("Weird laws database is empty.", ephemeral=True)
        return
    view = WeirdLawView(laws_list)
    await interaction.response.send_message(embed=view.create_embed(), view=view)

# ---------------------------
# Prefix Command: !quote
# ---------------------------
@bot.command(name="quote")
async def prefix_quote(ctx):
    view = ZenQuoteView()
    await view.fetch_new_quote()  # Fetch the quote first
    await ctx.send(embed=view.create_embed(), view=view)

# ---------------------------
# Slash Command: /quote
# ---------------------------
@tree.command(name="quote", description="Random inspirational quote", guild=discord.Object(id=GUILD_ID))
async def slash_quote(interaction: discord.Interaction):
    view = ZenQuoteView()
    await view.fetch_new_quote()  # Fetch quote before sending
    await interaction.response.send_message(embed=view.create_embed(), view=view)

# ---------------------------
# Bot Events
# ---------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await tree.sync()
    print("Commands synced.")

bot.run(TOKEN)
