import discord
from discord.ext import commands

class MusicBot(commands.Bot):

    def __init__(self):
        super().__init__(command_prefix='!')

    async def sl(self, ctx):
        embed = discord.Embed(title='Music Bot')
        embed.add_field(name='Platforms', value='You can find me on Spotify, Apple Music, and YouTube.')
        await ctx.send(embed=embed)