import os
import re
import json
import base64
import asyncio
import random
import requests
import discord

from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput

from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones
from dotenv import load_dotenv

# ---------------------------
# Load Environment Variables
# ---------------------------

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")
API_NINJA_RANDOM_WORD_KEY = os.getenv("API_NINJA_RANDOM_WORD_KEY")

GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_FILE = os.getenv("GITHUB_FILE", "timezones.json")

# ---------------------------
# Discord Setup
# ---------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------------------
# GitHub Timezone Database
# ---------------------------

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

github_headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

timezones = {}
timezones_sha = None
timezone_dirty = False


async def load_timezones_from_github():

    global timezones_sha

    r = requests.get(GITHUB_API, headers=github_headers)

    if r.status_code != 200:
        print("Failed to fetch timezone database.")
        return {}

    data = r.json()

    timezones_sha = data["sha"]

    decoded = base64.b64decode(data["content"]).decode()

    return json.loads(decoded)


async def push_timezones_to_github():

    global timezone_dirty
    global timezones_sha

    if not timezone_dirty:
        return

    encoded = base64.b64encode(
        json.dumps(timezones, indent=4).encode()
    ).decode()

    payload = {
        "message": "Update timezone database",
        "content": encoded,
        "sha": timezones_sha
    }

    r = requests.put(GITHUB_API, headers=github_headers, json=payload)

    if r.status_code in [200, 201]:

        data = r.json()

        timezones_sha = data["content"]["sha"]

        timezone_dirty = False

        print("Timezone DB synced to GitHub")

    else:
        print("GitHub update failed")


async def timezone_sync_loop():

    await bot.wait_until_ready()

    while not bot.is_closed():

        await asyncio.sleep(300)

        await push_timezones_to_github()

# ---------------------------
# Song.link API
# ---------------------------

async def fetch_song_links(query, ctx, is_slash=False):

    url = f"https://api.song.link/v1-alpha.1/links?url={query}"

    try:
        r = requests.get(url)

        if r.status_code != 200:
            return None

        data = r.json()

        links = {}

        for platform, info in data["linksByPlatform"].items():

            links[platform] = info["url"]

        return {
            "title": data["entityUniqueId"],
            "links": links
        }

    except Exception as e:
        print(e)
        return None


async def send_songlink_embed(ctx, song_data, is_slash=False):

    embed = discord.Embed(
        title="Song Links",
        color=discord.Color.blurple()
    )

    for platform, url in song_data["links"].items():

        embed.add_field(
            name=platform.title(),
            value=f"[Open]({url})",
            inline=True
        )

    if is_slash:
        await ctx.followup.send(embed=embed)
    else:
        await ctx.send(embed=embed)

# ---------------------------
# Load Weird Laws Database
# ---------------------------
with open("weird_laws.json", "r", encoding="utf-8") as f:
    WEIRD_LAWS = json.load(f)

# ---------------------------
# Load Affirmations
# ---------------------------
with open("affirmations.json", "r", encoding="utf-8") as f:
    affirmations = json.load(f)

# ---------------------------
# Load Rel Progress
# ---------------------------
with open("rel_progress.json", "r") as f:
    rel_progress = json.load(f)

# ---------------------------
# Rel Progress Helper
# ---------------------------
def save_rel_progress():
    with open("rel_progress.json", "w") as f:
        json.dump(rel_progress, f)

# ---------------------------
# Affirmations Viewer
# ---------------------------
class AffirmationView(discord.ui.View):
    def __init__(self, affirmations, start_index):
        super().__init__(timeout=300)
        self.affirmations = affirmations
        self.index = start_index

    def get_embed(self):
        embed = discord.Embed(
            title="Much love",
            description=self.affirmations[self.index],
            color=discord.Color.pink()
        )
        embed.set_footer(text=f"{self.index+1}/{len(self.affirmations)}")
        return embed

    @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):

        if self.index > 0:
            self.index -= 1

        rel_progress["index"] = self.index
        save_rel_progress()

        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ➡", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):

        if self.index < len(self.affirmations) - 1:
            self.index += 1

        rel_progress["index"] = self.index
        save_rel_progress()

        await interaction.response.edit_message(embed=self.get_embed(), view=self)

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
# Timezone Modal
# ---------------------------

class TimezoneModal(Modal):

    def __init__(self, user_id):
        super().__init__(title="Set Your Timezone")

        self.user_id = user_id

        self.tz_input = TextInput(
            label="Enter your timezone or city",
            placeholder="America/New_York or New York",
            required=True
        )

        self.add_item(self.tz_input)

    async def on_submit(self, interaction: discord.Interaction):

        global timezone_dirty

        zone = self.tz_input.value.strip()

        if zone in available_timezones():
            tz_name = zone
        else:
            matches = [z for z in available_timezones() if zone.lower() in z.lower()]
            tz_name = matches[0] if matches else None

        if not tz_name:
            await interaction.response.send_message(
                "Could not find a matching timezone.",
                ephemeral=True
            )
            return

        timezones[str(self.user_id)] = tz_name

        timezone_dirty = True

        await interaction.response.send_message(
            f"Timezone saved: **{tz_name}**",
            ephemeral=True
        )


# ---------------------------
# Timezone Embed Builder
# ---------------------------

async def build_timezone_embed(viewer, guild):

    now = datetime.now().astimezone()
    unix_ts = int(now.timestamp())

    embed = discord.Embed(
        title="Server Times",
        description=f"Last refreshed: <t:{unix_ts}:f>",
        color=discord.Color.green()
    )

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

        embed.add_field(
            name=member.display_name,
            value=f"{display}",  # Removed raw tz display
            inline=True
        )

    return embed


# ---------------------------
# Timezone Buttons
# ---------------------------

class TimezoneView(View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Set Your Timezone",
        style=discord.ButtonStyle.primary,
        custom_id="timezone_set"
    )
    async def set_timezone(self, interaction: discord.Interaction, button: Button):

        modal = TimezoneModal(interaction.user.id)

        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Refresh Times",
        style=discord.ButtonStyle.secondary,
        custom_id="timezone_refresh"
    )
    async def refresh(self, interaction: discord.Interaction, button: Button):

        embed = await build_timezone_embed(
            interaction.user,
            interaction.guild
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


# ---------------------------
# Prefix Commands
# ---------------------------

@bot.command(name="time")
async def prefix_time(ctx):

    embed = await build_timezone_embed(
        ctx.author,
        ctx.guild
    )

    await ctx.send(
        embed=embed,
        view=TimezoneView()
    )


@bot.command(name="word")
async def prefix_word(ctx):

    view = WordView()

    await view.generate()

    await ctx.send(
        embed=view.pages[0],
        view=view
    )


@bot.command(name="quote")
async def prefix_quote(ctx):

    view = ZenQuoteView()

    await view.fetch_new_quote()

    await ctx.send(
        embed=view.create_embed(),
        view=view
    )


@bot.command(name="weird")
async def prefix_weird(ctx):

    laws = list(WEIRD_LAWS.values())

    if not laws:
        await ctx.send("Weird laws database empty.")
        return

    view = WeirdLawView(laws)

    await ctx.send(
        embed=view.create_embed(),
        view=view
    )


@bot.command(name="sl")
async def prefix_songlink(ctx, *, query: str):

    if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return

    data = await fetch_song_links(
        query,
        ctx,
        is_slash=False
    )

    if not data:
        await ctx.send("Could not find links.")
        return

    await send_songlink_embed(
        ctx,
        data,
        is_slash=False
    )


@bot.command(name="ecm")
async def ecm(ctx):

    embed = discord.Embed(
        title="Commands",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="!time",
        value="Interactive server timezone viewer",
        inline=False
    )

    embed.add_field(
        name="!word",
        value="Random word",
        inline=False
    )

    embed.add_field(
        name="!quote",
        value="Random quote",
        inline=False
    )

    embed.add_field(
        name="!weird",
        value="Random weird law",
        inline=False
    )

    embed.add_field(
        name="!sl <link>",
        value="Song platform links",
        inline=False
    )

    await ctx.send(embed=embed)

@bot.command()
async def rel(ctx):

    start_index = rel_progress["index"]

    view = AffirmationView(affirmations, start_index)
    embed = view.get_embed()

    await ctx.send(embed=embed, view=view)

    # advance for next command use
    rel_progress["index"] = (start_index + 1) % len(affirmations)
    save_rel_progress()

# ---------------------------
# Slash Commands
# ---------------------------

@tree.command(name="word", description="Random word")
async def slash_word(interaction: discord.Interaction):

    view = WordView()

    await view.generate()

    await interaction.response.send_message(
        embed=view.pages[0],
        view=view
    )


@tree.command(
    name="quote",
    description="Random quote",
    guild=discord.Object(id=GUILD_ID)
)
async def slash_quote(interaction: discord.Interaction):

    view = ZenQuoteView()

    await view.fetch_new_quote()

    await interaction.response.send_message(
        embed=view.create_embed(),
        view=view
    )


@tree.command(
    name="weird",
    description="Random weird law",
    guild=discord.Object(id=GUILD_ID)
)
async def slash_weird(interaction: discord.Interaction):

    laws = list(WEIRD_LAWS.values())

    view = WeirdLawView(laws)

    await interaction.response.send_message(
        embed=view.create_embed(),
        view=view
    )


@tree.command(
    name="sl",
    description="Song platform links",
    guild=discord.Object(id=GUILD_ID)
)
async def slash_songlink(interaction: discord.Interaction, query: str):

    if interaction.channel_id != ALLOWED_CHANNEL_ID:

        await interaction.response.send_message(
            "Not allowed here.",
            ephemeral=True
        )

        return

    await interaction.response.defer()

    data = await fetch_song_links(
        query,
        interaction,
        is_slash=True
    )

    if not data:

        await interaction.followup.send(
            "Could not find links."
        )

        return

    await send_songlink_embed(
        interaction,
        data,
        is_slash=True
    )


# ---------------------------
# Bot Ready Event
# ---------------------------

@bot.event
async def on_ready():

    global timezones

    print(f"Logged in as {bot.user}")

    timezones = await load_timezones_from_github()

    print("Timezone database loaded")

    bot.loop.create_task(timezone_sync_loop())

    bot.add_view(TimezoneView())
    bot.add_view(WordView())
    bot.add_view(ZenQuoteView())
    bot.add_view(WeirdLawView(list(WEIRD_LAWS.values())))

    await tree.sync()

    print("Commands synced")


# ---------------------------
# Start Bot
# ---------------------------

bot.run(TOKEN)
