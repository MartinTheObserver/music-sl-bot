import os
import json
import random
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Weird Laws ----------
with open("weirdlaws.json", "r", encoding="utf-8") as f:
    WEIRD_LAWS = json.load(f)

def get_weird_law():
    state = random.choice(list(WEIRD_LAWS.keys()))
    law = random.choice(WEIRD_LAWS[state])
    return state, law

# ---------- Utilities ----------
async def fetch_json(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
    except Exception:
        return None

def random_hex():
    hex_code = "#{:06X}".format(random.randint(0, 0xFFFFFF))
    return hex_code, int(hex_code.replace("#", ""), 16)

# ---------- Songlink ----------
SONGLINK_API = "https://api.song.link/v1-alpha.1/links?url="

@bot.command(name="sl")
async def sl_prefix(ctx, *, url: str):
    data = await fetch_json(f"{SONGLINK_API}{url}")
    if not data:
        return await ctx.reply("⚠️ Unable to fetch Songlink.")
    await ctx.reply(f"🔗 {data.get('pageUrl', url)}")

@app_commands.command(name="sl", description="Generate Songlink")
async def sl_slash(interaction: discord.Interaction, url: str):
    await interaction.response.defer(thinking=True)
    data = await fetch_json(f"{SONGLINK_API}{url}")
    if not data:
        return await interaction.followup.send("⚠️ Unable to fetch Songlink.")
    await interaction.followup.send(f"🔗 {data.get('pageUrl', url)}")

bot.tree.add_command(sl_slash)

# ---------- APIs ----------
async def define_word(term):
    data = await fetch_json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{term}")
    try:
        return data[0]["meanings"][0]["definitions"][0]["definition"]
    except Exception:
        return None

async def wiki_lookup(query):
    data = await fetch_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{query}")
    if not data:
        return None
    return data.get("extract")

async def get_quote():
    data = await fetch_json("https://zenquotes.io/api/random")
    if not data:
        return None
    return f"{data[0]['q']} — {data[0]['a']}"

async def get_fact():
    data = await fetch_json("https://uselessfacts.jsph.pl/api/v2/facts/random")
    return data.get("text") if data else None

# ---------- Modals ----------
class DefineModal(discord.ui.Modal, title="Define a word"):
    word = discord.ui.TextInput(label="Word", placeholder="example")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        definition = await define_word(self.word.value)
        if not definition:
            return await interaction.followup.send("❌ No definition found.")
        embed = discord.Embed(title=self.word.value, description=definition, color=0x3498DB)
        await interaction.followup.send(embed=embed)

class WikiModal(discord.ui.Modal, title="Wikipedia Lookup"):
    query = discord.ui.TextInput(label="Search Term", placeholder="example")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        extract = await wiki_lookup(self.query.value)
        if not extract:
            return await interaction.followup.send("❌ No article found.")
        embed = discord.Embed(title=self.query.value, description=extract[:4000], color=0xAAAAAA)
        await interaction.followup.send(embed=embed)

# ---------- ECM Panel ----------
class ECMView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Define", style=discord.ButtonStyle.primary)
    async def define_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DefineModal())

    @discord.ui.button(label="Wiki", style=discord.ButtonStyle.secondary)
    async def wiki_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WikiModal())

    @discord.ui.button(label="Quote", style=discord.ButtonStyle.success)
    async def quote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        q = await get_quote()
        if not q:
            return await interaction.followup.send("⚠️ Quote API down.")
        await interaction.followup.send(embed=discord.Embed(title="Quote", description=q, color=0xFFD700))

    @discord.ui.button(label="Weird Law", style=discord.ButtonStyle.danger)
    async def law_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        state, law = get_weird_law()
        embed = discord.Embed(title=f"Weird Law – {state}", description=law, color=0x8B0000)
        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="Hex Color", style=discord.ButtonStyle.secondary)
    async def hex_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        hex_code, color_int = random_hex()
        embed = discord.Embed(title="Random Hex Color", description=f"`{hex_code}`", color=color_int)
        await interaction.followup.send(embed=embed)

# ---------- ECM Command ----------
@app_commands.command(name="ecm", description="Open ECM control panel")
async def ecm(interaction: discord.Interaction):
    await interaction.response.send_message("🧩 ECM Panel", view=ECMView())

bot.tree.add_command(ecm)

# ---------- Ready ----------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
