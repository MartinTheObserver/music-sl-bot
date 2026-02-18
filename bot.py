import os
import requests
import discord
from discord import app_commands
from dotenv import load_dotenv

# Load .env locally (Render ignores this safely)
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def get_song_links(music_url):
    try:
        response = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": music_url, "userCountry": "US"},
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
    except Exception:
        return None, None, None

    links = []
    if "linksByPlatform" in result:
        for platform, data in result["linksByPlatform"].items():
            if isinstance(data, dict) and "url" in data:
                name = platform.replace("_", " ").title()
                links.append(f"[{name}]({data['url']})")

    title = result.get("entityTitle", "")
    artist = ""

    if "entitiesByUniqueId" in result:
        for entity in result["entitiesByUniqueId"].values():
            if entity.get("type") == "song":
                artist = entity.get("artistName", "")
                if not title:
                    title = entity.get("title", "")
                break

    return links, title, artist


def get_genius_link(title, artist):
    if not title or not artist:
        return None

    try:
        response = requests.get(
            "https://api.genius.com/search",
            params={"q": f"{title} {artist}"},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
            timeout=10
        )
        if response.status_code == 200:
            hits = response.json()["response"]["hits"]
            if hits:
                return hits[0]["result"].get("url")
    except Exception:
        pass

    return None


@tree.command(name="sl", description="Convert music link", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(url="Paste a Spotify/Apple/YouTube link")
async def sl(interaction: discord.Interaction, url: str):

    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(
            "Not allowed in this channel.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    links, title, artist = get_song_links(url)

    if not links:
        await interaction.followup.send("Could not fetch links.")
        return

    genius_url = get_genius_link(title, artist)

    embed = discord.Embed(
        title=f"{title} — {artist}",
        color=discord.Color.orange()
    )

    embed.add_field(
        name="Platforms",
        value="\n".join(links[:10]),
        inline=False
    )

    if genius_url:
        embed.add_field(
            name="Lyrics",
            value=f"[Genius]({genius_url})",
            inline=False
        )

    await interaction.followup.send(embed=embed)


@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Synced and logged in as {client.user}")


client.run(TOKEN)
