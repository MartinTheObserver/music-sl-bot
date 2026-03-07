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
DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID"))

# ---------------------------
# Flask Web Server
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
# Quote Viewer
# ---------------------------
class ZenQuoteView(View):
    def __init__(self, quote_text="", author=""):
        super().__init__(timeout=120)
        self.quote_text = quote_text
        self.author = author

    def create_embed(self):
        embed = discord.Embed(
            title="💬 Random Quote",
            description=f"“{self.quote_text}”\n\n— {self.author}",
            color=discord.Color.green()
        )
        return embed

    @discord.ui.button(label="🎲 New Quote", style=discord.ButtonStyle.primary)
    async def new_quote(self, interaction: discord.Interaction, button: Button):
        r = requests.get("https://zenquotes.io/api/random", timeout=10)
        data = r.json()
        self.quote_text = data[0]["q"]
        self.author = data[0]["a"]
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

# ---------------------------
# WORD EXPLORER API HELPERS
# ---------------------------

async def get_random_word():
    r = requests.get("https://random-word-api.herokuapp.com/word", timeout=10)
    return r.json()[0]

async def get_dictionary_data(word):
    r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=10)
    if r.status_code != 200:
        return "N/A", [], []

    data = r.json()[0]

    pronunciation = "N/A"
    if data.get("phonetics"):
        pronunciation = data["phonetics"][0].get("text", "N/A")

    definitions = []
    examples = []

    for meaning in data.get("meanings", []):
        for d in meaning.get("definitions", []):
            definitions.append(d.get("definition"))
            if d.get("example"):
                examples.append(d.get("example"))

    return pronunciation, definitions[:10], examples[:5]

async def get_related_words(word):
    r = requests.get(f"https://api.datamuse.com/words?ml={word}&max=15", timeout=10)
    data = r.json()
    return [w["word"] for w in data]

async def get_etymology(word):
    try:
        r = requests.get(
            f"https://en.wiktionary.org/w/api.php?action=parse&page={word}&prop=text&format=json",
            timeout=10
        )
        html = r.json()["parse"]["text"]["*"]
        match = re.search(r"Etymology.*?<p>(.*?)</p>", html, re.S)
        if match:
            text = re.sub("<.*?>", "", match.group(1))
            return text
    except:
        pass

    return "Etymology not found."

# ---------------------------
# WORD VIEWER
# ---------------------------
class WordView(View):

    def __init__(self):
        super().__init__(timeout=120)
        self.pages = []
        self.index = 0

    async def generate_word(self):

        word = await get_random_word()

        pronunciation, definitions, examples = await get_dictionary_data(word)
        related = await get_related_words(word)
        etymology = await get_etymology(word)

        pages = []

        def chunk(text_list, size=5):
            for i in range(0, len(text_list), size):
                yield text_list[i:i + size]

        def build_embed(title, content):
            return discord.Embed(
                title=word.capitalize(),
                url=f"https://www.google.com/search?q=define+{word}",
                description=f"Pronunciation: {pronunciation}",
                color=discord.Color.blurple()
            ).add_field(name=title, value=content, inline=False)

        for chunked in chunk(definitions):
            pages.append(build_embed(
                f"[Definitions](https://en.wiktionary.org/wiki/{word})",
                "\n".join(f"• {d}" for d in chunked)
            ))

        for chunked in chunk(examples):
            pages.append(build_embed(
                f"[Examples](https://en.wiktionary.org/wiki/{word})",
                "\n".join(f"• {e}" for e in chunked)
            ))

        for chunked in chunk(related):
            pages.append(build_embed(
                f"[Related Words](https://api.datamuse.com/words?ml={word})",
                ", ".join(chunked)
            ))

        pages.append(build_embed(
            f"[Etymology](https://en.wiktionary.org/wiki/{word}#Etymology)",
            etymology[:900]
        ))

        self.pages = pages
        self.index = 0

    @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index - 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="➡ Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index + 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="🎲 New Word", style=discord.ButtonStyle.primary)
    async def new_word(self, interaction: discord.Interaction, button: Button):
        await self.generate_word()
        await interaction.response.edit_message(embed=self.pages[0], view=self)

# ---------------------------
# WORD COMMANDS
# ---------------------------
@bot.command(name="word")
async def prefix_word(ctx):
    view = WordView()
    await view.generate_word()
    await ctx.send(embed=view.pages[0], view=view)

@tree.command(name="word", description="Discover a random word")
async def slash_word(interaction: discord.Interaction):
    view = WordView()
    await view.generate_word()
    await interaction.response.send_message(embed=view.pages[0], view=view)

# ---------------------------
# BOT READY
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
```
