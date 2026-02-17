import os
import requests
import discord
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")

# 🔒 Put allowed channel IDs here (comma separated in env OR hardcode list)
ALLOWED_CHANNELS = [int(x) for x in os.getenv("ALLOWED_CHANNELS", "").split(",") if x]

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

    song_title = result.get("entityTitle", "")
    artist = ""

    if "entitiesByUniqueId" in result:
        for entity in result["entitiesByUniqueId"].values():
            if entity.get("type") == "song":
                artist = entity.get("artistName", "")
                if not song_title:
                    song_title = entity.get("title", "")
                break

    return links, song_title, artist


def get_genius_link(song_title, artist):
    if not song_title or not artist:
        return None

    try:
        response = requests.get(
            "https://api.genius.com/search",
            params={"q": f"{song_title} {artist}"},
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


@tree.command(name="sl", description="Convert a music link to cross-platform links")
@app_commands.describe(url="Paste a Spotify/Apple/YouTube music link")
async def sl(interaction: discord.Interaction, url: str):

    # 🔒 Channel restriction
    if ALLOWED_CHANNELS and interaction.channel_id not in ALLOWED_CHANNELS:
        await interaction.response.send_message(
            "This command is not allowed in this channel.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    links, title, artist = get_song_links(url)

    if not links:
        await interaction.followup.send("Could not fetch music links.")
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
    await tree.sync()
    print(f"Logged in as {client.user}")


client.run(TOKEN)
