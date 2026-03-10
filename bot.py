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
import aiohttp  # for async quote fetch

# ---------------------------
# Load Environment Variables
# ---------------------------
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))
DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID"))
API_NINJA_RANDOM_WORD_KEY = os.getenv("API_NINJA_RANDOM_WORD_KEY")

# ---------------------------
# Flask Web Server (Railway requirement)
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
# WordView (unchanged)
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
            if isinstance(word, list):
                word = word[0]
            return str(word)
        except:
            return "example"

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
        except:
            pass

        if not defs:
            try:
                r = requests.get(f"https://api.datamuse.com/words?sp={word}&md=d&max=1", timeout=10)
                data = r.json()
                if data and "defs" in data[0]:
                    defs = [d.split("\t")[1] for d in data[0]["defs"]]
            except:
                pass

        return pron, defs[:10], examples[:8]

    async def related_words(self, word):
        try:
            r = requests.get(f"https://api.datamuse.com/words?ml={word}&max=20", timeout=10)
            return [x["word"] for x in r.json()]
        except:
            return []

    async def etymology(self, word):
        try:
            r = requests.get(
                f"https://en.wiktionary.org/w/api.php?action=parse&page={word}&prop=text&format=json",
                timeout=10
            )
            html = r.json()["parse"]["text"]["*"]
            matches = re.findall(r"<h[1-6][^>]*>Etymology.*?</h[1-6]>(.*?)<h[1-6]", html, re.S | re.I)
            paragraphs = []
            for match in matches:
                text = re.sub("<.*?>", "", match).strip()
                if text:
                    paragraphs.append(text)
            if paragraphs:
                return "\n\n".join(paragraphs)[:900]
        except:
            pass
        return "Etymology not found."

    async def generate(self):
        word = await self.fetch_random_word()
        pron, defs, examples = await self.dictionary(word)
        rel = await self.related_words(word)
        ety = await self.etymology(word)

        self.pages = []
        self.page_types = []

        def build_embed(embed_word, title, content):
            embed_word_str = str(embed_word)
            embed = discord.Embed(
                title=embed_word_str.capitalize(),
                url=f"https://www.google.com/search?q=define+{embed_word_str}",
                description=f"Pronunciation: {pron}",
                color=discord.Color.blurple()
            )
            if len(content) > 1024:
                content = content[:1020] + "…"
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
        if ety:
            self.pages.append(build_embed(word, "Etymology", ety))
            self.page_types.append("Etymology")

        self.index = 0
        for i, embed in enumerate(self.pages):
            next_type = self.page_types[i + 1] if i + 1 < len(self.pages) else "End"
            embed.set_footer(text=f"Page {i+1}/{len(self.pages)} | Next: {next_type}")

    @discord.ui.button(label="⬅ Prev", style=discord.ButtonStyle.secondary, custom_id="word_prev")
    async def prev(self, interaction: discord.Interaction, button: Button):
        if not self.pages:
            await self.generate()
        self.index = (self.index - 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="🎲 Random Word", style=discord.ButtonStyle.primary, custom_id="word_random")
    async def new_word(self, interaction: discord.Interaction, button: Button):
        await self.generate()
        await interaction.response.edit_message(embed=self.pages[0], view=self)

    @discord.ui.button(label="➡ Next", style=discord.ButtonStyle.secondary, custom_id="word_next")
    async def next(self, interaction: discord.Interaction, button: Button):
        if not self.pages:
            await self.generate()
        self.index = (self.index + 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

# ---------------------------
# Song.link Helpers (unchanged)
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
        data = r.json()
        return data
    except Exception as e:
        if is_slash:
            await ctx_or_interaction.followup.send(f"Error fetching song data: {e}")
        else:
            await ctx_or_interaction.send(f"Error fetching song data: {e}")
        return None

def get_genius_link(title: str, artist: str):
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
    except Exception:
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
# Quote System
# ---------------------------
QUOTE_GENRES = [
    "wisdom", "inspirational", "success", "life", "motivational",
    "happiness", "hope", "love", "friendship", "humor", "knowledge",
    "change", "courage", "attitude", "art", "beauty", "business",
    "communication", "education", "time", "technology", "famous-quotes",
    "religion", "philosophy"
]

async def fetch_quote(genre=None):
    url = "https://api.quotable.io/random"
    params = {}
    if genre:
        params["tags"] = genre
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as r:
                if r.status != 200:
                    raise Exception(f"Status code {r.status}")
                data = await r.json()
        return {
            "quote": data.get("content", "No quote found."),
            "author": data.get("author", "Unknown"),
            "genre": data.get("tags", [None])[0] if data.get("tags") else None
        }
    except Exception as e:
        print(f"Quote fetch error: {e}")
        return {"quote": "Error fetching quote.", "author": "", "genre": None}

class GenreModal(discord.ui.Modal, title="Set Quote Genre"):
    genre = discord.ui.TextInput(
        label="Enter a genre",
        placeholder="Example: inspirational",
        required=True,
        max_length=50
    )

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.view.genre = self.genre.value.lower()
        quote = await fetch_quote(self.view.genre)
        embed = self.view.build_embed(quote)
        await interaction.response.edit_message(embed=embed, view=self.view)

class QuoteView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.genre = None

    def build_embed(self, quote):
        embed = discord.Embed(
            title="💬 Quote",
            description=f"“{quote['quote']}”\n\n— {quote['author']}",
            color=discord.Color.green()
        )
        genre_text = self.genre if self.genre else "Random"
        embed.set_footer(text=f"Genre: {genre_text}")
        return embed

    async def send_new_quote(self, interaction: discord.Interaction):
        quote = await fetch_quote(self.genre)
        embed = self.build_embed(quote)

        try:
            if interaction.response.is_done():
                await interaction.edit_original_message(embed=embed, view=self)
            else:
                await interaction.response.send_message(embed=embed, view=self)
        except Exception as e:
            print(f"QuoteView send_new_quote error: {e}")
            await interaction.followup.send(embed=embed, view=self, ephemeral=True)

    @discord.ui.button(label="📋 Genres", style=discord.ButtonStyle.secondary, custom_id="quote_genres")
    async def genres(self, interaction: discord.Interaction, button: Button):
        genre_text = "\n".join(QUOTE_GENRES)
        await interaction.response.send_message(f"**Available Genres**\n\n{genre_text}", ephemeral=True)

    @discord.ui.button(label="🔎 Set Genre", style=discord.ButtonStyle.secondary, custom_id="quote_set_genre")
    async def set_genre(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(GenreModal(self))

    @discord.ui.button(label="🎯 Random Genre", style=discord.ButtonStyle.secondary, custom_id="quote_random_genre")
    async def random_genre(self, interaction: discord.Interaction, button: Button):
        self.genre = random.choice(QUOTE_GENRES)
        await self.send_new_quote(interaction)

    @discord.ui.button(label="🧹 Clear Filter", style=discord.ButtonStyle.secondary, custom_id="quote_clear_filter")
    async def clear_filter(self, interaction: discord.Interaction, button: Button):
        self.genre = None
        await self.send_new_quote(interaction)

    @discord.ui.button(label="🎲 New Quote", style=discord.ButtonStyle.primary, custom_id="quote_new")
    async def new_quote(self, interaction: discord.Interaction, button: Button):
        await self.send_new_quote(interaction)

# ---------------------------
# Commands
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
    view = QuoteView()
    quote = await fetch_quote()
    await ctx.send(embed=view.build_embed(quote), view=view)

@tree.command(name="quote", description="Random inspirational quote", guild=discord.Object(id=GUILD_ID))
async def slash_quote(interaction: discord.Interaction):
    view = QuoteView()
    quote = await fetch_quote()
    await interaction.response.send_message(embed=view.build_embed(quote), view=view)

@bot.command(name="sl")
async def songlink_prefix(ctx, *, query: str):
    if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return
    song_data = await fetch_song_links(query, ctx, is_slash=False)
    if not song_data:
        await ctx.send("Could not find links for that song.")
        return
    await send_songlink_embed(ctx, song_data, is_slash=False)

@tree.command(name="sl", description="Get song links", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link")
async def songlink_slash(interaction: discord.Interaction, query: str):
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
# Bot Event: on_ready with persistent views
# ---------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    if not any(isinstance(v, WordView) for v in bot.persistent_views):
        bot.add_view(WordView())
    if not any(isinstance(v, QuoteView) for v in bot.persistent_views):
        bot.add_view(QuoteView())
    if not any(isinstance(v, WeirdLawView) for v in bot.persistent_views):
        bot.add_view(WeirdLawView(list(WEIRD_LAWS.values())))

    await tree.sync()
    print("Commands synced.")

bot.run(TOKEN)
