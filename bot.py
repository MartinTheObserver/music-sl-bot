import os
import re
import json
import random
import aiohttp
import requests
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Modal, TextInput
from dotenv import load_dotenv

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
# Load Weird Laws JSON
# ---------------------------
with open("weirdlaws.json", "r", encoding="utf-8") as f:
    WEIRD_LAWS = json.load(f)

# ---------------------------
# Discord Bot Setup
# ---------------------------
intents = discord.Intents.default()
intents.message_content = True  # REQUIRED for prefix commands
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ============================
# Utility Functions
# ============================

def get_weird_law():
    if not WEIRD_LAWS:
        return "Unknown", "No weird laws loaded."
    state = random.choice(list(WEIRD_LAWS.keys()))
    law = random.choice(WEIRD_LAWS[state])
    return state, law

def random_hex_color():
    return random.randint(0, 0xFFFFFF)

async def get_random_quote():
    async with aiohttp.ClientSession() as session:
        try:
            data = await session.get("https://zenquotes.io/api/random")
            j = await data.json()
            return j[0].get("q", "No quote available.")
        except:
            return "Could not fetch quote."

async def get_wiki_summary(query):
    safe = query.replace(" ", "_")
    async with aiohttp.ClientSession() as session:
        try:
            data = await session.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe}")
            j = await data.json()
            return j.get("extract", "No article found.")
        except:
            return "Could not fetch wiki article."

async def get_definition(word):
    async with aiohttp.ClientSession() as session:
        try:
            data = await session.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}")
            j = await data.json()
            meaning = j[0]["meanings"][0]["definitions"][0]["definition"]
            return meaning
        except:
            return "No definition found."

# ============================
# ECM Buttons
# ============================

class ECMView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Weird Law", style=discord.ButtonStyle.danger)
    async def weirdlaw_button(self, interaction, button):
        state, law = get_weird_law()
        embed = discord.Embed(
            title=f"Weird Law — {state}",
            description=law,
            color=random_hex_color()
        )
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Wiki", style=discord.ButtonStyle.primary)
    async def wiki_button(self, interaction, button):
        class WikiModal(Modal, title="Wikipedia Search"):
            query = TextInput(label="Topic")

            async def on_submit(self, modal_interaction):
                summary = await get_wiki_summary(self.query.value)
                embed = discord.Embed(
                    title=f"Wikipedia: {self.query.value}",
                    description=summary,
                    color=random_hex_color()
                )
                await modal_interaction.response.send_message(embed=embed)

        await interaction.response.send_modal(WikiModal())

    @discord.ui.button(label="Define", style=discord.ButtonStyle.secondary)
    async def define_button(self, interaction, button):
        class DefineModal(Modal, title="Define Word"):
            term = TextInput(label="Word")

            async def on_submit(self, modal_interaction):
                meaning = await get_definition(self.term.value)
                embed = discord.Embed(
                    title=f"Definition — {self.term.value}",
                    description=meaning,
                    color=random_hex_color()
                )
                await modal_interaction.response.send_message(embed=embed)

        await interaction.response.send_modal(DefineModal())

    @discord.ui.button(label="Quote", style=discord.ButtonStyle.success)
    async def quote_button(self, interaction, button):
        text = await get_random_quote()
        embed = discord.Embed(
            title="Quote",
            description=text,
            color=random_hex_color()
        )
        await interaction.response.send_message(embed=embed)

# ============================
# /ecm Slash Command
# ============================

@tree.command(
    name="ecm",
    description="Open ECM Entertainment menu",
    guild=discord.Object(id=GUILD_ID)
)
async def ecm(interaction: discord.Interaction):
    view = ECMView()
    await interaction.response.send_message("Select an option:", view=view)

# ============================
# Original Music Bot Code
# Integrated from your GitHub
# ============================

def clean_song_title(title: str) -> str:
    if not title:
        return ""
    title = re.sub(r"\(feat\.?.*?\)|\[feat\.?.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\(.*?Remix.*?\)|\[.*?Remix.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[\[\]\(\)]", "", title)
    title = re.sub(r"[^\w\s&'-]", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()

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
    except:
        return None

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
        return hits[0]["result"].get("url") if hits else None
    except:
        return None

async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False, debug_enabled=True):
    entity_id = None
    for uid, entity in song_data.get("entitiesByUniqueId", {}).items():
        if entity.get("type") == "song":
            entity_id = uid
            break
    if not entity_id:
        return
    song = song_data["entitiesByUniqueId"][entity_id]
    title = song.get("title", "Unknown Title")
    artist = song.get("artistName", "Unknown Artist")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")
    genius_url = get_genius_link(title, artist, ctx_or_interaction, is_slash, debug_enabled)
    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    platform_links = "\n".join(
        f"[{platform.replace('_',' ').title()}]({data['url']})"
        for platform, data in platforms if "url" in data
    )
    embed = discord.Embed(
        title=title,
        url=genius_url,
        description=f"by {artist}\n\n{platform_links}",
        color=random_hex_color()
    )
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    if is_slash:
        await ctx_or_interaction.followup.send(embed=embed)
    else:
        await ctx_or_interaction.send(embed=embed)

@bot.command(name="sl")
async def songlink(ctx, *, query: str):
    if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return
    data = await fetch_song_links(query, ctx, is_slash=False)
    if not data:
        await ctx.send("Could not find links.")
        return
    await send_songlink_embed(ctx, data)

@tree.command(name="sl", description="Get song links", guild=discord.Object(id=GUILD_ID))
async def slash_songlink(interaction: discord.Interaction, query: str):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        return await interaction.response.send_message("Not allowed here.", ephemeral=True)
    await interaction.response.defer()
    data = await fetch_song_links(query, interaction, is_slash=True)
    if not data:
        return await interaction.followup.send("Could not find links.")
    await send_songlink_embed(interaction, data, is_slash=True)

# ============================
# Ready Event
# ============================

@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

# ============================
# Run Bot
# ============================

bot.run(TOKEN)
