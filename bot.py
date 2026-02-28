import os
import re
import requests
import random
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, ui
from dotenv import load_dotenv
from flask import Flask
import threading
import asyncio

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
# Flask Web Server (Render/RA requirement)
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
# Helper Functions
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
        print(f"[DEBUG ERROR] {e}")

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
        for hit in hits:
            result = hit.get("result", {})
            result_title = result.get("title", "").lower()
            result_artist = result.get("primary_artist", {}).get("name", "").lower()
            if clean_title.lower() in result_title and artist.lower() in result_artist:
                return result.get("url")
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
        msg = "Could not parse song data."
        if is_slash: await ctx_or_interaction.followup.send(msg)
        else: await ctx_or_interaction.send(msg)
        return

    song = song_data["entitiesByUniqueId"][entity_id]
    title = song.get("title", "Unknown Title")
    artist = song.get("artistName", "Unknown Artist")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")
    genius_url = get_genius_link(title, artist, ctx_or_interaction, is_slash, debug_enabled)

    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    platform_links = "\n".join(
        f"[{platform.replace('_',' ').title()}]({data['url']})"
        for platform, data in platforms if isinstance(data, dict) and "url" in data
    )
    chunks = []
    current_chunk = ""
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
            description=f"by {artist}\n\n{chunk}",
            color=0x1DB954
        )
        if thumbnail: embed.set_thumbnail(url=thumbnail)
        if len(chunks) > 1: embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
        
        view = ui.View()
        view.add_item(ui.Button(label="Paste Another Song", style=discord.ButtonStyle.primary, custom_id="paste_song"))

        if is_slash:
            await ctx_or_interaction.followup.send(embed=embed, view=view)
        else:
            await ctx_or_interaction.send(embed=embed, view=view)

# ---------------------------
# Prefix Command
# ---------------------------
@bot.command(name="sl")
@commands.guild_only()
async def songlink(ctx, *, query: str):
    if ctx.channel.id != ALLOWED_CHANNEL_ID: return
    song_data = await fetch_song_links(query, ctx)
    if not song_data:
        await ctx.send("Could not find links for that song.")
        return
    await send_songlink_embed(ctx, song_data)

# ---------------------------
# Slash Command
# ---------------------------
@tree.command(
    name="sl",
    description="Get song links",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(query="Paste Spotify, Apple, or YouTube link")
async def slash_songlink(interaction: discord.Interaction, query: str):
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
# Paste Song Modal
# ---------------------------
class PasteSongModal(ui.Modal, title="Paste a Song Link"):
    song_link = ui.TextInput(label="Song URL", placeholder="Paste Spotify, Apple, YouTube link here")
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        song_data = await fetch_song_links(self.song_link.value, interaction, is_slash=True)
        if not song_data:
            await interaction.followup.send("Could not find links for that song.")
            return
        await send_songlink_embed(interaction, song_data, is_slash=True)

# ---------------------------
# ECM Extra Features
# ---------------------------
def random_hex_color(): 
    return "#{:06X}".format(random.randint(0, 0xFFFFFF))

async def fetch_quote():
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("https://zenquotes.io/api/random") as resp:
                data = await resp.json()
                return f"{data[0]['q']} — {data[0]['a']}" if data else "No quote available."
        except:
            return "No quote available."

class DefineModal(ui.Modal, title="Define a Word"):
    word = ui.TextInput(label="Enter a word", placeholder="Type a word here...")
    async def on_submit(self, interaction: discord.Interaction):
        async with aiohttp.ClientSession() as session:
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{self.word.value}"
            try:
                async with session.get(url) as resp:
                    data = await resp.json()
                    if isinstance(data, list) and data:
                        meaning = data[0]["meanings"][0]["definitions"][0]["definition"]
                        embed = discord.Embed(title=f"Define: {self.word.value}", description=meaning, color=0x00FFFF)
                        await interaction.response.send_message(embed=embed)
                        return
            except:
                pass
        await interaction.response.send_message(f"Could not find definition for '{self.word.value}'.")

class ECMView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ui.Button(label="Fact", style=discord.ButtonStyle.primary, custom_id="fact"))
        self.add_item(ui.Button(label="Useless Fact", style=discord.ButtonStyle.primary, custom_id="useless"))
        self.add_item(ui.Button(label="Color", style=discord.ButtonStyle.secondary, custom_id="color"))
        self.add_item(ui.Button(label="Quote", style=discord.ButtonStyle.success, custom_id="quote"))
        self.add_item(ui.Button(label="Random", style=discord.ButtonStyle.danger, custom_id="random"))
        self.add_item(ui.Button(label="Define", style=discord.ButtonStyle.secondary, custom_id="define"))

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        cid = interaction.data.get("custom_id")
        if not cid: return

        facts = ["Cats sleep 70% of their lives.", "Bananas are berries.", "A group of flamingos is called a flamboyance."]
        useless = ["Oxford University is older than the Aztec Empire.", "You cannot burp in space.", "Sharks existed before trees."]

        if cid == "fact":
            await interaction.response.send_message("Fact: " + random.choice(facts))
        elif cid == "useless":
            await interaction.response.send_message("Useless Fact: " + random.choice(useless))
        elif cid == "color":
            hex_color = random_hex_color()
            embed = discord.Embed(title="Random Color", description=f"The hex code is `{hex_color}`", color=int(hex_color.strip("#"),16))
            await interaction.response.send_message(embed=embed)
        elif cid == "quote":
            await interaction.response.defer()
            q = await fetch_quote()
            embed = discord.Embed(title="Quote", description=q, color=0xFFD700)
            await interaction.followup.send(embed=embed)
        elif cid == "random":
            choice = random.choice(["fact","useless","color","quote"])
            if choice=="fact":
                await interaction.response.send_message("Fact: " + random.choice(facts))
            elif choice=="useless":
                await interaction.response.send_message("Useless Fact: " + random.choice(useless))
            elif choice=="color":
                hex_color = random_hex_color()
                embed = discord.Embed(title="Random Color", description=f"The hex code is `{hex_color}`", color=int(hex_color.strip("#"),16))
                await interaction.response.send_message(embed=embed)
            elif choice=="quote":
                await interaction.response.defer()
                q = await fetch_quote()
                embed = discord.Embed(title="Quote", description=q, color=0xFFD700)
                await interaction.followup.send(embed=embed)
        elif cid == "define":
            await interaction.response.send_modal(DefineModal())
        elif cid == "paste_song":
            await interaction.response.send_modal(PasteSongModal())

# ---------------------------
# Bot Ready Event
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

# ---------------------------
# Run Bot
# ---------------------------
bot.run(TOKEN)
