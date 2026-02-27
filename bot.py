import os
import re
import json
import random
import asyncio
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, ui
from dotenv import load_dotenv
from flask import Flask
import threading

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
# Helpers
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

# ---------------------------
# Fetch JSON with fail-safe
# ---------------------------
async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=10) as resp:
            resp.raise_for_status()
            return await resp.json()
    except Exception as e:
        print(f"[API ERROR] Could not fetch {url}: {e}")
        return {"error": "Unable to fetch data from API."}

# ---------------------------
# Song.link & Genius
# ---------------------------
async def fetch_song_links(query: str, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    await debug_send(ctx_or_interaction, f"Fetching Song.link data for query: {query}", is_slash=is_slash, debug_enabled=debug_enabled)
    try:
        r = await asyncio.to_thread(lambda: requests.get("https://api.song.link/v1-alpha.1/links", params={"url": query, "userCountry":"US"}, timeout=20))
        r.raise_for_status()
        data = r.json()
        await debug_send(ctx_or_interaction, f"Song.link API returned keys: {list(data.keys())}", is_slash=is_slash, debug_enabled=debug_enabled)
        return data
    except Exception as e:
        await debug_send(ctx_or_interaction, f"Song.link error: {e}", is_slash=is_slash, debug_enabled=debug_enabled)
        return None

def get_genius_link(title, artist, ctx_or_interaction=None, is_slash=False, debug_enabled=True):
    if not title or not GENIUS_API_KEY:
        return None
    clean_title_str = clean_song_title(title)
    query = f"{clean_title_str} {artist}"
    try:
        r = requests.get("https://api.genius.com/search", params={"q": query}, headers={"Authorization": f"Bearer {GENIUS_API_KEY}"}, timeout=20)
        data = r.json()
        hits = data.get("response", {}).get("hits", [])
        for hit in hits:
            res = hit.get("result", {})
            res_title = res.get("title", "").lower()
            res_artist = res.get("primary_artist", {}).get("name", "").lower()
            if clean_title_str.lower() in res_title and artist.lower() in res_artist:
                return res.get("url")
        return hits[0]["result"].get("url") if hits else None
    except Exception as e:
        asyncio.create_task(debug_send(ctx_or_interaction, f"Genius API failed: {e}", is_slash=is_slash, debug_enabled=debug_enabled))
        return None

# ---------------------------
# Song Link Embed
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False, debug_enabled=True):
    entity_id = None
    for uid, entity in song_data.get("entitiesByUniqueId", {}).items():
        if entity.get("type")=="song":
            entity_id = uid
            break
    if not entity_id:
        msg = "Could not parse song data."
        if is_slash:
            await ctx_or_interaction.followup.send(msg)
        else:
            await ctx_or_interaction.send(msg)
        return
    song = song_data["entitiesByUniqueId"][entity_id]
    title = song.get("title","Unknown Title")
    artist = song.get("artistName","Unknown Artist")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")
    genius_url = get_genius_link(title, artist, ctx_or_interaction, is_slash, debug_enabled)
    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    platform_links = "\n".join(f"[{p.replace('_',' ').title()}]({d['url']})" for p,d in platforms if isinstance(d, dict) and "url" in d)
    chunks=[]
    current=""
    for line in platform_links.split("\n"):
        if len(current)+len(line)+1>1000:
            chunks.append(current)
            current=line
        else:
            current += ("\n" if current else "")+line
    if current: chunks.append(current)
    for i,chunk in enumerate(chunks):
        embed=discord.Embed(title=title, url=genius_url, description=f"by {artist}", color=0x1DB954)
        if thumbnail: embed.set_thumbnail(url=thumbnail)
        embed.add_field(name="Listen On", value=chunk, inline=False)
        if len(chunks)>1: embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
        if is_slash:
            await ctx_or_interaction.followup.send(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)
    # Add button to create new song link via modal
    class SongModal(ui.Modal):
        def __init__(self):
            super().__init__(title="Paste Song Link")
            self.link_input = ui.TextInput(label="Song URL", placeholder="Paste link here")
            self.add_item(self.link_input)
        async def on_submit(self, interaction):
            await interaction.response.defer()
            new_data = await fetch_song_links(self.link_input.value, interaction, is_slash=True)
            if new_data: await send_songlink_embed(interaction, new_data, is_slash=True)
    button = ui.Button(label="New Song", style=discord.ButtonStyle.primary)
    async def button_callback(interaction):
        await interaction.response.send_modal(SongModal())
    button.callback=button_callback
    view=ui.View()
    view.add_item(button)
    if is_slash: await ctx_or_interaction.followup.send("🎵 Add another song:", view=view)
    else: await ctx_or_interaction.send("🎵 Add another song:", view=view)

# ---------------------------
# !sl Command
# ---------------------------
@bot.command(name="sl")
@commands.guild_only()
@commands.has_permissions(send_messages=True)
async def songlink(ctx, *, query: str):
    if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return
    song_data = await fetch_song_links(query, ctx)
    if not song_data:
        await ctx.send("Could not find links for that song.")
        return
    await send_songlink_embed(ctx, song_data)

# ---------------------------
# /sl Command
# ---------------------------
@tree.command(name="sl", description="Get song links", guild=discord.Object(id=GUILD_ID))
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
# ECM Menu
# ---------------------------
class WikiModal(ui.Modal):
    def __init__(self):
        super().__init__(title="Define / Wiki")
        self.query = ui.TextInput(label="Enter term")
        self.add_item(self.query)
    async def on_submit(self, interaction):
        async with aiohttp.ClientSession() as session:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{self.query.value}"
            data = await fetch_json(session, url)
            if "error" in data:
                await interaction.response.send_message(f"⚠️ {data['error']}", ephemeral=True)
            else:
                extract = data.get("extract","No summary found.")
                embed = discord.Embed(title=data.get("title",self.query.value), description=extract, color=0x00FFFF)
                await interaction.response.send_message(embed=embed)

class ECMView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ui.Button(label="Fact", style=discord.ButtonStyle.success, custom_id="fact"))
        self.add_item(ui.Button(label="Useless Fact", style=discord.ButtonStyle.success, custom_id="uselessfact"))
        self.add_item(ui.Button(label="Quote", style=discord.ButtonStyle.success, custom_id="quote"))
        self.add_item(ui.Button(label="Color", style=discord.ButtonStyle.primary, custom_id="color"))
        self.add_item(ui.Button(label="Weird Law", style=discord.ButtonStyle.secondary, custom_id="weirdlaw"))
        self.add_item(ui.Button(label="Define", style=discord.ButtonStyle.secondary, custom_id="define"))
        self.add_item(ui.Button(label="Random", style=discord.ButtonStyle.danger, custom_id="random"))

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    cid = interaction.data.get("custom_id")
    async with aiohttp.ClientSession() as session:
        async def fetch_fact(): data = await fetch_json(session,"https://uselessfacts.jsph.pl/random.json?language=en"); return data.get("text","Could not fetch fact.")
        async def fetch_quote(): data = await fetch_json(session,"https://api.quotable.io/random"); return f"{data.get('content')} — {data.get('author')}" if "error" not in data else data["error"]
        async def fetch_color(): c=random.randint(0,0xFFFFFF); return c,f"Hex: #{c:06X}"
        async def fetch_weirdlaw(): 
            with open("weirdlaws.json","r") as f: laws=json.load(f)
            return random.choice(laws)
        if cid=="fact": await interaction.response.send_message(embed=discord.Embed(title="Fact",description=await fetch_fact(),color=0x00FF00))
        elif cid=="uselessfact": await interaction.response.send_message(embed=discord.Embed(title="Useless Fact",description=await fetch_fact(),color=0x00FF00))
        elif cid=="quote": await interaction.response.send_message(embed=discord.Embed(title="Quote",description=await fetch_quote(),color=0xFFD700))
        elif cid=="color":
            col,txt=await fetch_color()
            await interaction.response.send_message(embed=discord.Embed(title="Color",description=txt,color=col))
        elif cid=="weirdlaw": await interaction.response.send_message(embed=discord.Embed(title="Weird Law",description=await fetch_weirdlaw(),color=0x8A2BE2))
        elif cid=="define": await interaction.response.send_modal(WikiModal())
        elif cid=="random":
            choice=random.choice(["fact","uselessfact","quote","color","weirdlaw"])
            interaction.data["custom_id"]=choice
            await on_interaction(interaction)

# ---------------------------
# /ecm Command
# ---------------------------
@tree.command(name="ecm", description="Open ECM menu", guild=discord.Object(id=GUILD_ID))
async def slash_ecm(interaction: discord.Interaction):
    await interaction.response.send_message("Choose an option:", view=ECMView(), ephemeral=True)

# ---------------------------
# Bot Ready
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

# ---------------------------
# Run Bot
# ---------------------------
bot.run(TOKEN)
