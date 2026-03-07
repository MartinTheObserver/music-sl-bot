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
API_NINJAS_KEY = os.getenv("API_NINJAS_KEY")  # Random word API key
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
# Random Word API (API Ninjas)
# ---------------------------
async def random_word():
    try:
        r = requests.get(
            "https://api.api-ninjas.com/v1/randomword",
            headers={"X-Api-Key": API_NINJAS_KEY},
            timeout=10
        )
        r.raise_for_status()
        return r.json().get("word", "word")
    except Exception as e:
        print(f"[Random Word API Error] {e}")
        return "word"

# ---------------------------
# Dictionary, Related, Etymology Helpers
# ---------------------------
async def dictionary(word):
    try:
        r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=10)
        if r.status_code != 200:
            return "N/A", [], []
        data = r.json()[0]
        pronunciation = data.get("phonetics", [{}])[0].get("text", "N/A")
        definitions = []
        examples = []
        for meaning in data.get("meanings", []):
            for d in meaning.get("definitions", []):
                definitions.append(d.get("definition"))
                if d.get("example"):
                    examples.append(d.get("example"))
        return pronunciation, definitions[:10], examples[:6]
    except Exception:
        return "N/A", [], []

async def related(word):
    try:
        r = requests.get(f"https://api.datamuse.com/words?ml={word}&max=20", timeout=10)
        return [x["word"] for x in r.json()]
    except Exception:
        return []

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
# Word Viewer
# ---------------------------
class WordView(View):
    def __init__(self):
        super().__init__(timeout=120)
        self.pages = []
        self.index = 0

    async def generate(self):
        word_str = await random_word()
        pron, defs, examples = await dictionary(word_str)
        rel = await related(word_str)
        ety = await etymology(word_str)
        self.pages = []

        def chunk(lst, n):
            for i in range(0, len(lst), n):
                yield lst[i:i+n]

        def build_embed(embed_word, title, content):
            embed = discord.Embed(
                title=embed_word.capitalize(),
                url=f"https://www.google.com/search?q=define+{embed_word}",
                description=f"Pronunciation: {pron}",
                color=discord.Color.blurple()
            )
            embed.add_field(name=title, value=content, inline=False)
            return embed

        # Definitions
        for c in chunk(defs, 5):
            self.pages.append(build_embed(word_str, f"[Definitions](https://en.wiktionary.org/wiki/{word_str})", "\n".join(f"• {d}" for d in c)))

        # Examples
        for c in chunk(examples, 4):
            self.pages.append(build_embed(word_str, f"[Examples](https://en.wiktionary.org/wiki/{word_str})", "\n".join(f"• {e}" for e in c)))

        # Related words
        for c in chunk(rel, 8):
            self.pages.append(build_embed(word_str, f"[Related Words](https://api.datamuse.com/words?ml={word_str})", ", ".join(c)))

        # Etymology
        self.pages.append(build_embed(word_str, f"[Etymology](https://en.wiktionary.org/wiki/{word_str}#Etymology)", ety[:900]))
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
# Prefix and Slash Commands
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

# ---------------------------
# Keep all your previous !sl, !quote, !weird commands here
# (They remain unchanged from your last working bot.py)
# ---------------------------

# ---------------------------
# Genius API Test
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
# Bot Ready
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
