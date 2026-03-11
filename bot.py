import os
import re
import json
import requests
import discord
import threading
import asyncio
import random

from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones
from flask import Flask

# ---------------------------
# Environment Variables (Railway)
# ---------------------------
TOKEN = os.environ["DISCORD_TOKEN"]
GENIUS_API_KEY = os.environ.get("GENIUS_API_KEY")
API_NINJA_RANDOM_WORD_KEY = os.environ.get("API_NINJA_RANDOM_WORD_KEY")
GUILD_ID = int(os.environ["GUILD_ID"])
ALLOWED_CHANNEL_ID = int(os.environ["ALLOWED_CHANNEL_ID"])
DEBUG_USER_ID = int(os.environ.get("DEBUG_USER_ID", 0))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = os.environ.get("GITHUB_FILE", "timezones.json")

# ---------------------------
# Flask server (Railway requirement)
# ---------------------------
app = Flask(__name__)
@app.route("/")
def home(): return "Bot is alive."
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
threading.Thread(target=run_flask, daemon=True).start()

# ---------------------------
# Discord Bot Setup
# ---------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------------------
# GitHub Timezone DB
# ---------------------------
timezones = {}
timezones_sha = None
timezone_dirty = False
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
github_headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

async def load_timezones_from_github():
    global timezones_sha
    r = requests.get(GITHUB_API, headers=github_headers)
    if r.status_code != 200:
        print("Failed to fetch timezone database.")
        return {}
    data = r.json()
    timezones_sha = data["sha"]
    decoded = json.loads(json.loads(json.dumps(base64.b64decode(data["content"]).decode())))
    return decoded

async def push_timezones_to_github():
    global timezone_dirty, timezones_sha
    if not timezone_dirty: return
    encoded = base64.b64encode(json.dumps(timezones, indent=4).encode()).decode()
    payload = {"message":"Update timezone database","content":encoded,"sha":timezones_sha}
    r = requests.put(GITHUB_API, headers=github_headers, json=payload)
    if r.status_code in [200,201]:
        data = r.json()
        timezones_sha = data["content"]["sha"]
        timezone_dirty = False
        print("Timezone DB synced to GitHub")
    else: print("GitHub update failed")

async def timezone_sync_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(300)
        await push_timezones_to_github()

# ---------------------------
# GeoNames helpers
# ---------------------------
GEONAMES_USER = "martintheobserver"

def search_location(location: str, max_results=10):
    url = f"http://api.geonames.org/searchJSON?q={location}&maxRows={max_results}&username={GEONAMES_USER}"
    res = requests.get(url).json()
    return res.get("geonames", [])

def get_timezone(lat, lng):
    url = f"http://api.geonames.org/timezoneJSON?lat={lat}&lng={lng}&username={GEONAMES_USER}"
    res = requests.get(url).json()
    return res.get("timezoneId")

async def handle_zone(ctx_or_interaction, location: str, is_interaction=False):
    results = search_location(location)
    if not results:
        msg = f"❌ Could not find any matches for `{location}`."
        if is_interaction: await ctx_or_interaction.response.send_message(msg, ephemeral=True)
        else: await ctx_or_interaction.send(msg)
        return

    if len(results) == 1:
        city = results[0]
        tz = get_timezone(city["lat"], city["lng"])
        region = city.get("adminName1")
        region_text = f", {region}" if region else ""
        msg = f"🌍 {city['name']}{region_text}, {city['countryName']} → `{tz}`"
        if is_interaction: await ctx_or_interaction.response.send_message(msg)
        else: await ctx_or_interaction.send(msg)
        return

    if len(location.split(",")) == 1 and len(location) <= 20:
        city = results[0]
        tz = get_timezone(city["lat"], city["lng"])
        region = city.get("adminName1")
        region_text = f", {region}" if region else ""
        msg = f"🌍 Using the most central/major location for `{location}`: {city['name']}{region_text}, {city['countryName']} → `{tz}`"
        if is_interaction: await ctx_or_interaction.response.send_message(msg)
        else: await ctx_or_interaction.send(msg)
        return

    view = ZoneSelect(results)
    if is_interaction:
        await ctx_or_interaction.response.send_message(f"Select the location for `{location}`:", view=view)
    else:
        await ctx_or_interaction.send(f"Select the location for `{location}`:", view=view)

# ---------------------------
# Timezone Modal & View
# ---------------------------
class TimezoneModal(Modal):
    def __init__(self, user_id):
        super().__init__(title="Set Your Timezone")
        self.user_id = user_id
        self.add_item(TextInput(
            label="Enter your timezone or city",
            placeholder="America/New_York or New York",
            required=True
        ))

    async def on_submit(self, interaction: discord.Interaction):
        global timezone_dirty
        zone = self.children[0].value.strip()
        if zone in available_timezones():
            tz_name = zone
        else:
            matches = [z for z in available_timezones() if zone.lower() in z.lower()]
            tz_name = matches[0] if matches else None

        if not tz_name:
            await interaction.response.send_message("Could not find a matching timezone.", ephemeral=True)
            return

        timezones[str(self.user_id)] = tz_name
        timezone_dirty = True
        await interaction.response.send_message(f"Timezone saved: **{tz_name}**", ephemeral=True)

class TimezoneView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Set Your Timezone", style=discord.ButtonStyle.primary, custom_id="timezone_set")
    async def set_timezone(self, interaction: discord.Interaction, button: Button):
        modal = TimezoneModal(interaction.user.id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Refresh Times", style=discord.ButtonStyle.secondary, custom_id="timezone_refresh")
    async def refresh(self, interaction: discord.Interaction, button: Button):
        embed = await build_timezone_embed(interaction.user, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

async def build_timezone_embed(viewer, guild):
    now = datetime.now().astimezone()
    embed = discord.Embed(title="Server Times", description=f"Last refreshed: {now.strftime('%Y-%m-%d %I:%M %p')}", color=discord.Color.green())
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
        embed.add_field(name=member.display_name, value=f"{display}\n`{tz}`", inline=True)
    return embed

# ---------------------------
# Prefix Commands
# ---------------------------
@bot.command(name="zone")
async def prefix_zone(ctx, *, location: str = None):
    if location is None:
        class LocationModal(Modal):
            def __init__(self):
                super().__init__(title="Enter your location")
                self.add_item(TextInput(label="Location", placeholder="City, state, or country", required=True))

            async def on_submit(self, interaction: discord.Interaction):
                await handle_zone(interaction, self.children[0].value, is_interaction=True)

        await ctx.send_modal(LocationModal())
        return
    await handle_zone(ctx, location)

@bot.command(name="time")
async def prefix_time(ctx):
    embed = await build_timezone_embed(ctx.author, ctx.guild)
    await ctx.send(embed=embed, view=TimezoneView())

# ---------------------------
# Word, Quote, Weird, Song.link Commands
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
    view = ZenQuoteView()
    await view.fetch_new_quote()
    await ctx.send(embed=view.create_embed(), view=view)

@tree.command(name="quote", description="Random inspirational quote", guild=discord.Object(id=GUILD_ID))
async def slash_quote(interaction: discord.Interaction):
    view = ZenQuoteView()
    await view.fetch_new_quote()
    await interaction.response.send_message(embed=view.create_embed(), view=view)

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
# Bot on_ready
# ---------------------------
@bot.event
async def on_ready():
    global timezones
    print(f"Logged in as {bot.user}")

    # Load timezone DB from GitHub
    if GITHUB_TOKEN and GITHUB_REPO:
        timezones = await load_timezones_from_github()
        bot.loop.create_task(timezone_sync_loop())

    # Add persistent views
    bot.add_view(WordView())
    bot.add_view(ZenQuoteView())
    bot.add_view(WeirdLawView(list(WEIRD_LAWS.values())))
    bot.add_view(TimezoneView())

    await tree.sync()
    print("Commands synced.")

# ---------------------------
# Run Bot
# ---------------------------
bot.run(TOKEN)