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
from discord.ui import Select, View, Button, Modal, TextInput

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
# GeoNames Helpers
# ---------------------------

GEONAMES_USER = "martintheobserver"

def search_location(location: str, max_results=10):
    """Search GeoNames for top matching locations."""
    url = f"http://api.geonames.org/searchJSON?q={location}&maxRows={max_results}&username={GEONAMES_USER}"
    res = requests.get(url).json()
    if not res.get("geonames"):
        return []
    return res["geonames"]

def get_timezone(lat, lng):
    """Get IANA timezone for given coordinates."""
    url = f"http://api.geonames.org/timezoneJSON?lat={lat}&lng={lng}&username={GEONAMES_USER}"
    res = requests.get(url).json()
    return res.get("timezoneId")

# ---------------------------
# GeoNames Command Logic
# ---------------------------

async def handle_zone(ctx_or_interaction, location: str, is_interaction=False):
    results = search_location(location)

    if not results:
        msg = f"❌ Could not find any matches for `{location}`."
        if is_interaction:
            await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_interaction.send(msg)
        return

    # Single exact match
    if len(results) == 1:
        city = results[0]
        tz = get_timezone(city["lat"], city["lng"])
        city_name = city["name"]
        region = city.get("adminName1")
        country = city["countryName"]
        region_text = f", {region}" if region else ""
        msg = f"🌍 {city_name}{region_text}, {country} → `{tz}`"
        if is_interaction:
            await ctx_or_interaction.response.send_message(msg)
        else:
            await ctx_or_interaction.send(msg)
        return

    # Fallback for vague country/continent
    if len(location.split(",")) == 1 and len(location) <= 20:
        city = results[0]  # pick major/central
        tz = get_timezone(city["lat"], city["lng"])
        city_name = city["name"]
        region = city.get("adminName1")
        country = city["countryName"]
        region_text = f", {region}" if region else ""
        msg = f"🌍 Using the most central/major location for `{location}`: {city_name}{region_text}, {country} → `{tz}`"
        if is_interaction:
            await ctx_or_interaction.response.send_message(msg)
        else:
            await ctx_or_interaction.send(msg)
        return

    # Otherwise show dropdown
    view = ZoneSelect(results)
    if is_interaction:
        await ctx_or_interaction.response.send_message(f"Select the location for `{location}`:", view=view)
    else:
        await ctx_or_interaction.send(f"Select the location for `{location}`:", view=view)

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
# Random Word System
# ---------------------------

class WordView(View):

    def __init__(self):
        super().__init__(timeout=None)
        self.pages = []

    async def generate(self):

        headers = {"X-Api-Key": API_NINJA_RANDOM_WORD_KEY}

        r = requests.get(
            "https://api.api-ninjas.com/v1/randomword",
            headers=headers
        )

        word = r.json()["word"]

        embed = discord.Embed(
            title=f"Word: {word}",
            color=discord.Color.green()
        )

        self.pages = [embed]

    @discord.ui.button(label="New Word", style=discord.ButtonStyle.primary, custom_id="word_new")
    async def new_word(self, interaction: discord.Interaction, button: Button):

        await self.generate()

        await interaction.response.edit_message(
            embed=self.pages[0],
            view=self
        )

# ---------------------------
# Quote System
# ---------------------------

class ZenQuoteView(View):

    def __init__(self):
        super().__init__(timeout=None)
        self.quote = None

    async def fetch_new_quote(self):

        r = requests.get("https://zenquotes.io/api/random")

        data = r.json()[0]

        self.quote = f'"{data["q"]}"\n— {data["a"]}'

    def create_embed(self):

        return discord.Embed(
            title="Quote",
            description=self.quote,
            color=discord.Color.gold()
        )

    @discord.ui.button(label="New Quote", style=discord.ButtonStyle.secondary, custom_id="quote_new")
    async def new_quote(self, interaction: discord.Interaction, button: Button):

        await self.fetch_new_quote()

        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self
        )

# ---------------------------
# Weird Laws Loader
# ---------------------------

with open("weird_laws.json", "r", encoding="utf8") as f:
    WEIRD_LAWS = json.load(f)


class WeirdLawView(View):

    def __init__(self, laws, index=0):
        super().__init__(timeout=None)
        self.laws = laws
        self.index = index

    def create_embed(self):

        law = self.laws[self.index]

        return discord.Embed(
            title="Weird Law",
            description=law,
            color=discord.Color.orange()
        )

# ---------------------------
# Weird Law Button
# ---------------------------

    @discord.ui.button(label="Next Law", style=discord.ButtonStyle.primary, custom_id="law_next")
    async def next_law(self, interaction: discord.Interaction, button: Button):

        self.index += 1

        if self.index >= len(self.laws):
            self.index = 0

        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self
        )


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

    embed = discord.Embed(
        title=f"Server Times",
        description=f"Last refreshed: {now.strftime('%Y-%m-%d %I:%M %p')}",
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
            value=f"{display}\n`{tz}`",
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

    embed.add_field(
        name="!zone <link>",
        value="Discover your timezone",
        inline=False
    )

    await ctx.send(embed=embed)

@bot.command(name="zone")
async def zone(ctx, *, location: str = None):
    if location is None:
        # Show a modal to ask for location
        class LocationModal(Modal):
            def __init__(self):
                super().__init__(title="Enter your location")
                self.add_item(TextInput(
                    label="Location",
                    placeholder="City, state, or country",
                    required=True
                ))

            async def on_submit(self, interaction: discord.Interaction):
                await handle_zone(interaction, self.children[0].value, is_interaction=True)

        await ctx.send_modal(LocationModal())
        return

    await handle_zone(ctx, location)

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
