import os
import re
import json
import random
import asyncio
import threading
import requests
import discord

from dotenv import load_dotenv
from flask import Flask
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button

# ---------------------------
# ENVIRONMENT
# ---------------------------

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")

GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))
DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID"))

# ---------------------------
# FLASK KEEP ALIVE
# ---------------------------

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot alive"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ---------------------------
# DISCORD SETUP
# ---------------------------

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------------------
# LOAD WEIRD LAWS
# ---------------------------

with open("weird_laws.json", "r", encoding="utf-8") as f:
    WEIRD_LAWS = json.load(f)

# ---------------------------
# CHANNEL CHECK
# ---------------------------

def allowed(ctx_or_interaction):

    if isinstance(ctx_or_interaction, commands.Context):
        if ctx_or_interaction.author.id == DEBUG_USER_ID:
            return True
        return ctx_or_interaction.channel.id == ALLOWED_CHANNEL_ID

    else:
        if ctx_or_interaction.user.id == DEBUG_USER_ID:
            return True
        return ctx_or_interaction.channel.id == ALLOWED_CHANNEL_ID

# ---------------------------
# SONG LINK COMMAND
# ---------------------------

async def get_song_links(url):

    r = requests.get(
        f"https://api.song.link/v1-alpha.1/links?url={url}",
        timeout=10
    )

    if r.status_code != 200:
        return None

    data = r.json()

    links = {}

    for platform, obj in data.get("linksByPlatform", {}).items():
        links[platform] = obj.get("url")

    return links


async def send_song_embed(ctx_or_interaction, url):

    links = await get_song_links(url)

    if not links:
        msg = "Could not resolve that music link."

        if isinstance(ctx_or_interaction, commands.Context):
            await ctx_or_interaction.send(msg)
        else:
            await ctx_or_interaction.response.send_message(msg)
        return

    embed = discord.Embed(
        title="🎵 Music Link Aggregator",
        description="Platform links",
        color=discord.Color.purple()
    )

    for k, v in links.items():
        embed.add_field(name=k.capitalize(), value=f"[Open]({v})")

    if isinstance(ctx_or_interaction, commands.Context):
        await ctx_or_interaction.send(embed=embed)
    else:
        await ctx_or_interaction.response.send_message(embed=embed)

# ---------------------------
# QUOTES
# ---------------------------

class ZenQuoteView(View):

    def __init__(self, quote="", author=""):
        super().__init__(timeout=120)
        self.quote = quote
        self.author = author

    def embed(self):

        return discord.Embed(
            title="💬 Quote",
            description=f"“{self.quote}”\n\n— {self.author}",
            color=discord.Color.green()
        )

    @discord.ui.button(label="🎲 New Quote", style=discord.ButtonStyle.primary)
    async def new_quote(self, interaction: discord.Interaction, button: Button):

        r = requests.get("https://zenquotes.io/api/random", timeout=10)
        data = r.json()[0]

        self.quote = data["q"]
        self.author = data["a"]

        await interaction.response.edit_message(embed=self.embed(), view=self)

# ---------------------------
# WEIRD LAWS VIEWER
# ---------------------------

class WeirdLawView(View):

    def __init__(self, laws, index=0):
        super().__init__(timeout=120)

        self.laws = laws
        self.index = index

    def embed(self):

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
            text=f"{self.index+1}/{len(self.laws)} | Source: {law['source']}"
        )

        return embed

    @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: Button):

        self.index = (self.index - 1) % len(self.laws)

        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="🎲 Random", style=discord.ButtonStyle.primary)
    async def rand(self, interaction: discord.Interaction, button: Button):

        self.index = random.randint(0, len(self.laws)-1)

        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="➡ Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: Button):

        self.index = (self.index + 1) % len(self.laws)

        await interaction.response.edit_message(embed=self.embed(), view=self)

# ---------------------------
# WORD DATA
# ---------------------------

async def random_word():

    r = requests.get("https://random-word-api.herokuapp.com/word")

    return r.json()[0]


async def dictionary(word):

    r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}")

    if r.status_code != 200:
        return "N/A", [], []

    data = r.json()[0]

    pronunciation = "N/A"

    if data.get("phonetics"):
        pronunciation = data["phonetics"][0].get("text","N/A")

    defs = []
    ex = []

    for meaning in data.get("meanings",[]):
        for d in meaning["definitions"]:
            defs.append(d["definition"])

            if "example" in d:
                ex.append(d["example"])

    return pronunciation, defs, ex


async def related(word):

    r = requests.get(f"https://api.datamuse.com/words?ml={word}&max=20")

    return [x["word"] for x in r.json()]


async def etymology(word):

    try:

        r = requests.get(
            f"https://en.wiktionary.org/w/api.php?action=parse&page={word}&prop=text&format=json"
        )

        html = r.json()["parse"]["text"]["*"]

        m = re.search(r"Etymology.*?<p>(.*?)</p>", html, re.S)

        if m:
            text = re.sub("<.*?>","",m.group(1))
            return text

    except:
        pass

    return "Not found."

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

        pron, defs, ex, = await dictionary(word)

        rel = await related(word)

        ety = await etymology(word)

        self.pages = []

        def chunk(lst,n):
            for i in range(0,len(lst),n):
                yield lst[i:i+n]

        def embed(title,text):

            e = discord.Embed(
                title=word.capitalize(),
                url=f"https://www.google.com/search?q=define+{word}",
                description=f"Pronunciation: {pron}",
                color=discord.Color.blurple()
            )

            e.add_field(name=title,value=text,inline=False)

            return e

        for c in chunk(defs,5):

            self.pages.append(
                embed(
                    f"[Definitions](https://en.wiktionary.org/wiki/{word})",
                    "\n".join(f"• {x}" for x in c)
                )
            )

        for c in chunk(ex,4):

            self.pages.append(
                embed(
                    f"[Examples](https://en.wiktionary.org/wiki/{word})",
                    "\n".join(f"• {x}" for x in c)
                )
            )

        for c in chunk(rel,8):

            self.pages.append(
                embed(
                    f"[Related Words](https://api.datamuse.com/words?ml={word})",
                    ", ".join(c)
                )
            )

        self.pages.append(
            embed(
                f"[Etymology](https://en.wiktionary.org/wiki/{word}#Etymology)",
                ety[:900]
            )
        )

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
    async def new(self, interaction: discord.Interaction, button: Button):

        await self.generate()

        await interaction.response.edit_message(embed=self.pages[0], view=self)

# ---------------------------
# COMMANDS
# ---------------------------

@bot.command()
async def song(ctx, url):

    if not allowed(ctx):
        return

    await send_song_embed(ctx, url)


@bot.command()
async def quote(ctx):

    if not allowed(ctx):
        return

    r = requests.get("https://zenquotes.io/api/random")

    q = r.json()[0]

    view = ZenQuoteView(q["q"], q["a"])

    await ctx.send(embed=view.embed(), view=view)


@bot.command()
async def law(ctx):

    if not allowed(ctx):
        return

    view = WeirdLawView(WEIRD_LAWS)

    await ctx.send(embed=view.embed(), view=view)


@bot.command()
async def word(ctx):

    if not allowed(ctx):
        return

    view = WordView()

    await view.generate()

    await ctx.send(embed=view.pages[0], view=view)

# ---------------------------
# READY
# ---------------------------

@bot.event
async def on_ready():

    await tree.sync(guild=discord.Object(id=GUILD_ID))

    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
