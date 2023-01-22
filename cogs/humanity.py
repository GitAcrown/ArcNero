# pyright: reportGeneralTypeIssues=false

import asyncio
import logging
import random
import time
import json
import os
import yaml
import glob
from datetime import datetime
from typing import Optional, List, Callable

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands
from tabulate import tabulate
from minigames import MiniGames

from common.utils import pretty
from common.dataio import get_package_path, get_sqlite_database

logger = logging.getLogger('arcnero.Humanity')


class PacksSelectMenu(discord.ui.Select):
    def __init__(self, original_interaction: discord.Interaction, cog: 'Humanity'):
        super().__init__(
            placeholder='Sélectionnez les packs à utiliser',
            min_values=1,
            max_values=len(cog.PACKS.keys()),
            row=0
        )
        self.original_interaction = original_interaction
        self._cog = cog
        self.__fill_options()
        self.choices : List[str] = []

    def __fill_options(self) -> None:
        for pack in self._cog.PACKS:
            self.add_option(label=self._cog.PACKS[pack]['_metadata']['name'], 
                            value=pack, 
                            description=f"{self._cog.PACKS[pack]['_metadata']['description']} · Par {self._cog.PACKS[pack]['_metadata']['author']}",
                            emoji=self._cog.PACKS[pack]['_metadata']['emoji'])

    async def callback(self, interaction: discord.Interaction):
        self.choices = self.values
        await interaction.response.send_message(f"**Vous avez sélectionné les packs suivants :** {', '.join([self._cog.PACKS[p]['_metadata']['name'] for p in self._cog.PACKS if p in self.choices])}", ephemeral=True)

class JoinGameView(discord.ui.View):
    def __init__(self,  cog: 'Humanity', initial_interaction: discord.Interaction, *, timeout: Optional[float] = 90):
        super().__init__(timeout=timeout)
        self._cog = cog
        self.initial_interaction = initial_interaction
        self.embed_message : discord.Message = None
        
    def get_embed(self):
        session = self._cog.get_session(self.initial_interaction.channel)
        players = session['players']
        em = discord.Embed(description=f"**{self.initial_interaction.user}** a lancé une partie de **Humanity** !")
        em.add_field(name="Packs utilisés", value=', '.join([f"`{self._cog.PACKS[p]['_metadata']['name']}`" for p in self._cog.PACKS if p in session['packs']]))
        em.add_field(name="Joueurs", value='\n'.join([f"• {p['user'].mention}" for p in players]))
        return em
        
    async def start(self):
        em = self.get_embed()
        self.embed_message = await self.initial_interaction.channel.send(embed=em, view=self)
        
    @discord.ui.button(label="Rejoindre", style=discord.ButtonStyle.green, row=0)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Rejoindre la partie"""
        session = self._cog.get_session(interaction.channel)
        if interaction.user.id not in session['players'] and len(session['players']) < 6 and session['open']:
            session['players'][interaction.user.id] = {'user': interaction.user, 'interaction': interaction, 'score': 0, 'hand': []}
            await self.embed_message.reply(f"**{interaction.user.name}** a rejoint la partie !", delete_after=20)
            await self.embed_message.edit(embed=self.get_embed())
                
    async def on_timeout(self) -> None:
        await self.initial_interaction.edit_original_response(view=None)
        session = self._cog.get_session(self.initial_interaction.channel)
        session['open'] = False

class BlackCard():
    def __init__(self, text: str, picks: int) -> None:
        self.text = text
        self.picks = picks
        
    def __str__(self) -> str:
        return self.__display()
    
    def __display(self) -> str:
        return self.text.replace('_', u'\_\_\_\_')
    
    def fill(self, white_cards: List[str]) -> str:
        if len(white_cards) != self.picks:
            raise ValueError(f"Nombre de cartes blanches incorrect: {len(white_cards)} au lieu de {self.picks}")
        ftext = self.text.replace('_', '__{}__')
        return ftext.format(*white_cards)
    

class Humanity(commands.Cog):
    """Cards Against Humanity sur Discord"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.PACKS = self._load_packs()
        self.sessions = {}
        self._initialize_database()
        
    def _initialize_database(self):
        for guild in self.bot.guilds:
            conn = get_sqlite_database('humanity', f"g{guild.id}")
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS gamelogs (game_id TEXT PRIMARY KEY, rounds_data TEXT, winner_id INTEGER)")
            conn.commit()
            cursor.close()
            conn.close()

    def _load_packs(self):
        packs = {}
        for filename in glob.glob(os.path.join(get_package_path('humanity'), '*.yaml')):
            with open(os.path.join(os.getcwd(), filename), 'r', encoding='UTF8') as f:
                data = yaml.safe_load(f)
                packs[data['_metadata']['id']] = data
        return packs
    
    def get_session(self, channel: discord.TextChannel) -> dict:
        return self.sessions.get(channel.id, {})
        
    @app_commands.command(name="humanity", description="Jouer à Cards Against Humanity")
    async def _humanity_command(self, interaction: discord.Interaction):
        """Jouer à Cards Against Humanity sur Discord"""
        view = PacksSelectMenu(interaction, self)
        await interaction.response.send_message("Sélectionnez les packs à utiliser", view=view, ephemeral=True)
        await view.wait()
        if not view.choices:
            return await interaction.followup.send("**Partie annulée ·** Vous n'avez sélectionné aucun pack de cartes", ephemeral=True)
        packs = [self.PACKS[p] for p in self.PACKS if p in view.choices]
        
        session = self.get_session(interaction.channel)
        if session.get('playing', False):
            return await interaction.followup.send("**Partie en cours ·** Une partie est déjà en cours dans ce salon", ephemeral=True)
        
        session = {
            'open': True,
            'playing': False,
            'players': {},
            'packs': packs,
            'white_cards': [],
            'black_cards': [],
            'round': 0,
            'czar': None
        }
        session['players'][interaction.user.id] = {'user': interaction.user, 'interaction': interaction, 'score': 0, 'hand': []}
        
        # Permettre aux autres joueurs de rejoindre la partie
        await JoinGameView(interaction, self).start()
        if len(session['players']) < 3:
            return await interaction.followup.send("**Partie annulée ·** Vous n'avez pas assez de joueurs")
        
        session['white_cards'] = [c for p in packs for c in p['white_cards']]
        session['black_cards'] = [BlackCard(c, packs[p]['black_cards'][c]) for p in packs for c in packs[p]['black_cards']]
        
        for player in session['players']:
            player['hand'] = [random.sample(session['white_cards'])]
        
        channel = interaction.channel
        while True:
            session['round'] += 1
            await channel.send(f"**Humanity ·** Début de la manche n°{session['round']}")
            for player in session['players']:
                player['hand'] = []
    
async def setup(bot: commands.Bot):
    bot.add_cog(Humanity(bot))
    