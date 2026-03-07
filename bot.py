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
        embed.add_field(
            name="Location",
            value=f"{law['region']}, {law['country']}",
            inline=False
        )
        embed.add_field(
            name="Explanation",
            value=law["description"],
            inline=False
        )
        embed.set_footer(
            text=f"Source: {law['source']} | #{self.index+1}/{len(self.laws)}"
        )
        return embed

    @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index - 1) % len(self.laws)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🎲 Random", style=discord.ButtonStyle.primary)
    async def random_law(self, interaction: discord.Interaction, button: Button):
        self.index = random.randint(0, len(self.laws)-1)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Next ➡", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: Button):
        self.index = (self.index + 1) % len(self.laws)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

# ---------------------------
# ZenQuotes Viewer
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
# WORD EXPLORER HELPERS
# ---------------------------

async def random_word():
    r = requests.get("https://random-word-api.herokuapp.com/word", timeout=10)
    return r.json()[0]

async def dictionary(word):
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
            text = re.sub("<.*?>", "", m.group(1))
            return text
    except:
        pass
    return "Etymology not found."

# ---------------------------
# WORD VIEW
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

@bot.command(name="weirdlaw")
async def prefix_weirdlaw(ctx):
    view = WeirdLawView(WEIRD_LAWS)
    await ctx.send(embed=view.create_embed(), view=view)

@bot.command(name="quote")
async def prefix_quote(ctx):
    try:
        r = requests.get("https://zenquotes.io/api/random", timeout=10)
        r.raise_for_status()
        data = r.json()
        quote_text = data[0].get("q", "No quote found")
        author = data[0].get("a", "")
    except:
        quote_text = "Error fetching quote."
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

@tree.command(name="weirdlaw", description="Discover a random weird law")
async def slash_weirdlaw(interaction: discord.Interaction):
    view = WeirdLawView(WEIRD_LAWS)
    await interaction.response.send_message(embed=view.create_embed(), view=view)

@tree.command(name="quote", description="Get a random inspirational quote")
async def slash_quote(interaction: discord.Interaction):
    try:
        r = requests.get("https://zenquotes.io/api/random", timeout=10)
        r.raise_for_status()
        data = r.json()
        quote_text = data[0].get("q", "No quote found")
        author = data[0].get("a", "")
    except:
        quote_text = "Error fetching quote."
        author = ""
    view = ZenQuoteView(quote_text, author)
    await interaction.response.send_message(embed=view.create_embed(), view=view)

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
            print("Genius API key invalid")
        elif r.status_code != 200:
            print(f"Genius API returned {r.status_code}")
        else:
            print("Genius API key validated")
    except Exception as e:
        print("Genius API validation exception:", e)

# ---------------------------
# READY EVENT
# ---------------------------

@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")
    asyncio.create_task(validate_genius_key())

# ---------------------------
# RUN BOT
# ---------------------------

bot.run(TOKEN)
