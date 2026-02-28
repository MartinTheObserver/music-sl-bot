import discord
from discord.ext import commands
from discord import app_commands
import requests
import random
import json
import os
import traceback

TOKEN = os.getenv("DISCORD_TOKEN")

INTENTS = discord.Intents.default()
INTENTS.message_content = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)
tree = bot.tree

DEBUG = True

def debug(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")

# =========================
# Weird Laws Loader (FIXED)
# =========================
with open("weirdlaws.json", "r", encoding="utf-8") as f:
    WEIRD_LAWS = json.load(f)

def get_weird_law():
    entry = random.choice(WEIRD_LAWS)
    return entry["state"], entry["law"]

# =========================
# Random Hex Color
# =========================
def random_hex():
    return random.randint(0, 0xFFFFFF)

# =========================
# Dictionary API (define)
# =========================
@bot.command()
async def define(ctx, *, word: str):
    try:
        r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=10)
        data = r.json()

        meaning = data[0]["meanings"][0]["definitions"][0]["definition"]

        embed = discord.Embed(
            title=f"📘 Definition: {word}",
            description=meaning,
            color=random_hex()
        )
        await ctx.send(embed=embed)
    except Exception:
        await ctx.send("❌ Definition not found.")

# =========================
# Wikipedia (FIXED)
# =========================
@bot.command()
async def wiki(ctx, *, query: str):
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}"
        r = requests.get(url, timeout=10)

        if r.status_code != 200:
            await ctx.send("❌ No article found.")
            return

        data = r.json()
        extract = data.get("extract", "No summary found.")

        embed = discord.Embed(
            title=f"📚 {data.get('title', query)}",
            description=extract[:3900],
            url=data.get("content_urls", {}).get("desktop", {}).get("page"),
            color=random_hex()
        )

        await ctx.send(embed=embed)

    except Exception as e:
        debug(traceback.format_exc())
        await ctx.send("❌ Wiki lookup failed.")

# =========================
# SongLink Aggregator (Restored Style)
# =========================
@bot.command(name="sl")
async def sl(ctx, *, song: str):
    try:
        url = "https://api.song.link/v1-alpha.1/links"
        params = {"q": song}
        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        links = data.get("linksByPlatform", {})
        if not links:
            await ctx.send("❌ No links found.")
            return

        msg = "**🎵 Song Links:**\n"
        for platform, info in links.items():
            msg += f"**{platform.title()}** → {info['url']}\n"

        await ctx.send(msg)

    except Exception:
        debug(traceback.format_exc())
        await ctx.send("⚠️ SongLink API failed.")

# =========================
# Lyrics (Restored)
# =========================
@bot.command()
async def lyrics(ctx, *, song: str):
    try:
        r = requests.get(f"https://api.lyrics.ovh/v1//{song}", timeout=10)
        data = r.json()

        lyrics = data.get("lyrics")
        if not lyrics:
            await ctx.send("❌ Lyrics not found.")
            return

        chunks = [lyrics[i:i+1900] for i in range(0, len(lyrics), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

    except Exception:
        await ctx.send("❌ Lyrics fetch failed.")

# =========================
# ECM VIEW (Buttons)
# =========================
class ECMView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Weird Law", style=discord.ButtonStyle.danger)
    async def law_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state, law = get_weird_law()
        embed = discord.Embed(
            title=f"⚖️ Weird Law — {state}",
            description=law,
            color=random_hex()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Random Color", style=discord.ButtonStyle.primary)
    async def hex_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        hex_color = f"#{random_hex():06X}"
        embed = discord.Embed(
            title="🎨 Random Hex Color",
            description=hex_color,
            color=int(hex_color.replace("#", ""), 16)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

# =========================
# ECM COMMAND (SLASH)
# =========================
@tree.command(name="ecm", description="Open ECM utility panel")
async def ecm(interaction: discord.Interaction):
    await interaction.response.send_message("🧰 ECM Panel:", view=ECMView(), ephemeral=True)

# =========================
# READY EVENT
# =========================
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

bot.run(TOKEN)
