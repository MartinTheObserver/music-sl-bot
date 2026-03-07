import os
import re
import requests
import discord
from discord.ui import View, Button
from discord.ext import commands
from dotenv import load_dotenv
import threading
import asyncio
import json
import random

# Load Environment Variables
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))
DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID"))

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive."

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

with open("weird_laws.json", "r", encoding="utf-8") as f:
    WEIRD_LAWS = json.load(f)

class WeirdLawView(View):
    def __init__(self, laws, index=0):
        super().__init__(timeout=120)
        self.laws = laws
        self.index = index

    def create_embed(self):
        law = self.laws

        embed = discord.Embed(
            title="🌍 Weird Law",
            description=f"**{law}**",
            color=discord.Color.orange()
        )

        embed.add_field(
            name="Location",
            value=f"{law}, {law}",
            inline=False
        )

        embed.add_field(
            name="Explanation",
            value=law,
            inline=False
        )

        embed.set_footer(text=f"Source: {law} | #{self.index+1}/{len(self.laws)}")

        return embed

    @discord.ui.button(label="⬅ Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: Button):

        self.index = (self.index - 1) % len(self.laws)

        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self
        )

    @discord.ui.button(label="🎲 Random", style=discord.ButtonStyle.primary)
    async def random_law(self, interaction: discord.Interaction, button: Button):

        self.index = random.randint(0, len(self.laws) - 1)

        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self
        )

    @discord.ui.button(label="Next ➡", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: Button):

        self.index = (self.index + 1) % len(self.laws)

        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self
        )

@bot.tree.command(name="weird", description="Browse weird laws from around the world")
async def weird(interaction: discord.Interaction):

    laws_list = list(WEIRD_LAWS.values())

    index = random.randint(0, len(laws_list) - 1)

    view = WeirdLawView(laws_list, index)

    await interaction.response.send_message(
        embed=view.create_embed(),
        view=view
    )

# Debug functions and utility functions remain unchanged.

@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")
    asyncio.create_task(validate_genius_key())

bot.run(TOKEN)
