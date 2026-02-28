import os
import json
import random
import string
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Utilities ----------

async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except Exception:
        return None

def random_hex():
    return "#{:06X}".format(random.randint(0, 0xFFFFFF))

def hex_to_int(hex_color: str) -> int:
    return int(hex_color.replace("#", ""), 16)

# ---------- Weird Laws ----------

with open("weirdlaws.json", "r", encoding="utf-8") as f:
    WEIRD_LAWS = json.load(f)

def get_weird_law():
    state = random.choice(list(WEIRD_LAWS.keys()))
    law = random.choice(WEIRD_LAWS[state])
    return state, law

# ---------- Songlink ----------

SONGLINK_API = "https://api.song.link/v1-alpha.1/links?url="

async def fetch_songlink(url):
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, f"{SONGLINK_API}{url}")
        return data

@bot.command(name="sl")
async def songlink_prefix(ctx, *, url: str):
    data = await fetch_songlink(url)
    if not data:
        return await ctx.reply("⚠️ Unable to fetch data from Songlink API.")
    page_url = data.get("pageUrl", url)
    await ctx.reply(f"🔗 {page_url}")

@app_commands.command(name="sl", description="Generate a Songlink for a song URL")
async def songlink_slash(interaction: discord.Interaction, url: str):
    await interaction.response.defer(thinking=True)
    data = await fetch_songlink(url)
    if not data:
        return await interaction.followup.send("⚠️ Unable to fetch data from Songlink API.")
    page_url = data.get("pageUrl", url)
    await interaction.followup.send(f"🔗 {page_url}")

bot.tree.add_command(songlink_slash)

# ---------- Define ----------

async def fetch_define(term):
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, f"https://api.dictionaryapi.dev/api/v2/entries/en/{term}")
        if not data:
            return None
        try:
            return data[0]["meanings"][0]["definitions"][0]["definition"]
        except Exception:
            return None

# ---------- Quote ----------

async def fetch_quote():
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, "https://zenquotes.io/api/random")
        if not data:
            return None
        return f"{data[0]['q']} — {data[0]['a']}"

# ---------- Facts ----------

async def fetch_fact():
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, "https://uselessfacts.jsph.pl/api/v2/facts/random")
        if not data:
            return None
        return data.get("text")

# ---------- Wiki ----------

async def fetch_wiki(query):
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, f"https://en.wikipedia.org/api/rest_v1/page/summary/{query}")
        if not data:
            return None
        return data.get("extract")

# ---------- ECM PANEL ----------

class ECMView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Define", style=discord.ButtonStyle.primary, custom_id="define")
    async def define_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("Use: `/define <word>`")

    @discord.ui.button(label="Wiki", style=discord.ButtonStyle.secondary, custom_id="wiki")
    async def wiki_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("Use: `/wiki <query>`")

    @discord.ui.button(label="Quote", style=discord.ButtonStyle.success, custom_id="quote")
    async def quote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        quote = await fetch_quote()
        if not quote:
            return await interaction.followup.send("⚠️ Quote API is down.")
        await interaction.followup.send(embed=discord.Embed(title="Quote", description=quote, color=0xFFD700))

    @discord.ui.button(label="Weird Law", style=discord.ButtonStyle.danger, custom_id="weirdlaw")
    async def weirdlaw_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        state, law = get_weird_law()
        await interaction.followup.send(embed=discord.Embed(title=f"Weird Law – {state}", description=law, color=0x8B0000))

    @discord.ui.button(label="Random Hex", style=discord.ButtonStyle.secondary, custom_id="hex")
    async def hex_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        hex_code = random_hex()
        embed = discord.Embed(
            title="Random Hex Color",
            description=f"Hex Code: `{hex_code}`",
            color=hex_to_int(hex_code)
        )
        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="Random", style=discord.ButtonStyle.secondary, custom_id="random")
    async def random_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        choice = random.choice(["quote", "fact", "hex"])
        if choice == "quote":
            q = await fetch_quote()
            return await interaction.followup.send(q or "Quote API down.")
        if choice == "fact":
            f = await fetch_fact()
            return await interaction.followup.send(f or "Fact API down.")
        if choice == "hex":
            h = random_hex()
            return await interaction.followup.send(h)

# ---------- Slash Commands ----------

@app_commands.command(name="define", description="Define a word")
async def define_cmd(interaction: discord.Interaction, word: str):
    await interaction.response.defer(thinking=True)
    definition = await fetch_define(word)
    if not definition:
        return await interaction.followup.send("❌ No definition found.")
    await interaction.followup.send(embed=discord.Embed(title=word, description=definition, color=0x00AAFF))

@app_commands.command(name="wiki", description="Search Wikipedia")
async def wiki_cmd(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)
    extract = await fetch_wiki(query)
    if not extract:
        return await interaction.followup.send("❌ No article found.")
    await interaction.followup.send(embed=discord.Embed(title=query, description=extract[:4000], color=0xCCCCCC))

@app_commands.command(name="ecm", description="Open the control panel")
async def ecm_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("🧩 ECM Control Panel", view=ECMView())

bot.tree.add_command(define_cmd)
bot.tree.add_command(wiki_cmd)
bot.tree.add_command(ecm_cmd)

# ---------- Ready ----------

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
