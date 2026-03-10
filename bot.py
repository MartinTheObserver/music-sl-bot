import os
import re
import aiohttp
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
# Fixed WordView Class
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
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as r:
                    data = await r.json()
                    word = data.get("word", "example")
                    if isinstance(word, list):
                        word = word[0]
                    return str(word)
        except:
            return "example"

    async def dictionary(self, word):
        defs, examples, pron = [], [], "N/A"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=10) as r:
                    if r.status == 200:
                        data = await r.json()
                        data = data[0]
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
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"https://api.datamuse.com/words?sp={word}&md=d&max=1", timeout=10) as r:
                        data = await r.json()
                        if data and "defs" in data[0]:
                            defs = [d.split("\t")[1] for d in data[0]["defs"]]
            except:
                pass

        return pron, defs[:10], examples[:8]

    async def related_words(self, word):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.datamuse.com/words?ml={word}&max=20", timeout=10) as r:
                    data = await r.json()
                    return [x["word"] for x in data]
        except:
            return []

    async def etymology(self, word):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://en.wiktionary.org/w/api.php?action=parse&page={word}&prop=text&format=json",
                    timeout=10
                ) as r:
                    html = (await r.json())["parse"]["text"]["*"]
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
# Async Quote Helpers
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

# ---------------------------
# Quote View
# ---------------------------
# ---------------------------
# Quote View (Fixed)
# ---------------------------
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

    async def send_new_quote(self, interaction):
        quote = await fetch_quote(self.genre)
        embed = self.build_embed(quote)
        # FIX: edit the original message directly instead of using response.edit_message
        await interaction.message.edit(embed=embed, view=self)

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
# Song.link Helpers
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

# ---------------------------
# Bot Event: on_ready with persistent views
# ---------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    if not any(isinstance(v, WordView) for v in bot.persistent_views):
        bot.add_view(WordView())
    if not any(isinstance(v, WeirdLawView) for v in bot.persistent_views):
        bot.add_view(WeirdLawView(list(WEIRD_LAWS.values())))
    if not any(isinstance(v, QuoteView) for v in bot.persistent_views):
        bot.add_view(QuoteView())

    await tree.sync()
    print("Commands synced.")

bot.run(TOKEN)