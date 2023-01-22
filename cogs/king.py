# pyright: reportGeneralTypeIssues=false

import asyncio
import logging
import random
import time
import os
import glob
import yaml
import json
from datetime import datetime
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import commands
from tabulate import tabulate

from cogs.economy import Economy, Transaction
from common.utils import pretty
from common.dataio import get_package_path, get_sqlite_database

logger = logging.getLogger('arcnero.King')
PACKS_PATH = get_package_path('king')

DEFAULT_SETTINGS = [
    ('EntryFee', 25)
]

STATUS_TXT = {
    'sick': "Malade",
    'poison': "Empoisonné.e",
    'bleeding': "Saigne",
    'trap': "Immobilisé.e"
}

PERKS = {
    
}

class RegisterView(discord.ui.View):
    def __init__(self, cog: 'King', interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.cog = cog
        self.initial_interaction = interaction
        self.session = cog.get_channel_session(interaction.channel)
        self.guild = interaction.guild
        
        self.guild_settings = cog.get_guild_settings(interaction.guild)
        self.bank : Economy = self.cog.bot.get_cog('Economy')
        self.message : discord.InteractionMessage = None
        
        self.transactions : List[Player, Transaction] = []
        
    async def interaction_check(self, interaction: discord.Interaction):
        is_registered = interaction.user.id in self.session['players']
        if is_registered:
            await interaction.response.send_message(
                "Vous êtes déjà inscrit pour cette partie de KING !",
                ephemeral=True,
            )
        return not is_registered
    
    async def on_timeout(self) -> None:
        await self.message.edit(view=None)
        
    def generate_embed(self):
        chunks = []
        players : List[Player] = self.session['players']
        for p in players:
            chunks.append(f"• {p.member.mention}")
        em = discord.Embed(color=0x2F3136, description="Inscrivez-vous à la partie avec le bouton ci-dessous !\n" + '\n'.join(chunks))
        em.set_footer(text=f"Frais d'inscription : {self.guild_settings['EntreFee']}{self.bank.guild_currency(self.guild)}")
        return em
    
    async def start(self):
        starter_account = self.bank.get_account(self.initial_interaction.user)
        if starter_account.balance < int(self.guild_settings['EntreFee']):
            await self.initial_interaction.response.send_message(f"Vous ne pouvez pas lancer la partie puisque vous n'avez pas assez pour payer les frais d'entrée ({self.guild_settings['EntreFee']}{self.bank.guild_currency(self.guild)}).", ephemeral=True)
            self.stop()
            return self.clear_items()
        else:
            trs = starter_account.withdraw_credits(int(self.guild_settings['EntreFee']), "Frais d'inscription Royale")
        self.message = await self.initial_interaction.original_response()

    @discord.ui.button(label="Rejoindre", style=discord.ButtonStyle.primary)
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Bouton pour rejoindre la partie"""
        self.inv_position = min(len(self.inventory) - 1, self.inv_position + 1)
        await self.buttons_logic(interaction)
        await interaction.response.edit_message(embed=self.embed_quote(self.inv_position))
        

class Player():
    """Représente un joueur de KING"""
    def __init__(self, cog: 'King', member: discord.Member) -> None:
        self.cog = cog
        self.member = member
        self.guild = member.guild
        self.__initialize_player()
        
    def __initialize_player(self):
        try:
            conn = get_sqlite_database('king', 'g' + str(self.guild.id))
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO players (user_id, perks, strengh, intelligence, dexterity) VALUES (?, ?, ?, ?, ?)", (self.member.id, json.dumps([]), 3, 3, 3))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Erreur dans l'initialisation du joueur : {e}", exc_info=True)
            
    
    
class Pack():
    """Représente un pack d'extension Royale"""
    def __init__(self, cog: 'King', pack_data: dict) -> None:
        self.cog = cog
        
        self._metadata : dict = pack_data['_metadata']
        self.id : str = self._metadata['id']
        self.name : str = self._metadata['name']
        self.description : str = self._metadata['description']
        self.author_id : int = self._metadata['author_id']
        self.image_url : str = self._metadata['image_url']
        self.last_update = datetime.now().strptime(self._metadata['last_update'], '%d/%m/%Y')
        

class King(commands.GroupCog, group_name="king", description="Battle Royale sur Discord"):
    """Battle Royale sur Discord"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions = {}
    
    @commands.Cog.listener()
    async def on_ready(self):
        self._initialize_database()
        self.PACKS = self._load_packs()
        
    def _initialize_database(self):
        for guild in self.bot.guilds:
            conn = get_sqlite_database('king', 'g' + str(guild.id))
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS players (user_id INTEGER PRIMARY KEY, perks TEXT, strengh INTEGER, intelligence INTEGER, dexterity INTEGER)")
            cursor.execute("CREATE TABLE IF NOT EXISTS settings (name TINYTEXT PRIMARY KEY, value TEXT)")
            for name, default_value in DEFAULT_SETTINGS:
                cursor.execute("INSERT OR IGNORE INTO settings (name, value) VALUES (?, ?)", (name, json.dumps(default_value)))
                
            conn.commit()
            cursor.close()
            conn.close()
            
    def _load_packs(self):
        packs = []
        for filename in glob.glob(os.path.join(PACKS_PATH, '*.yaml')):
            with open(os.path.join(os.getcwd(), filename), 'r') as f:
                packs.append(yaml.safe_load(f))
        return [p for p in packs if p]
    
    
    def get_pack(self, pack_id: str):
        for pack in self.PACKS:
            if self.PACKS[pack]['_metadata']['id'].lower() == pack_id.lower():
                return Pack(self, self.PACKS[pack])
        return None
    
    
    def get_player(self, member: discord.Member) -> Player:
        return Player(self, member)
    
    
    def get_guild_settings(self, guild: discord.Guild) -> dict:
        """Obtenir les paramètres économiques du serveur

        :param guild: Serveur des paramètres à récupérer
        :return: dict
        """
        conn = get_sqlite_database('king', 'g' + str(guild.id))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings")
        settings = cursor.fetchall()
        cursor.close()
        conn.close()
        
        from_json = {s[0] : json.loads(s[1]) for s in settings}
        return from_json
    
    def set_guild_settings(self, guild: discord.Guild, update: dict):
        """Met à jours les paramètres du serveur

        :param guild: Serveur à mettre à jour
        :param update: Paramètres à mettre à jour (toutes les valeurs seront automatiquement sérialisés en JSON)
        """
        conn = get_sqlite_database('king', 'g' + str(guild.id))
        cursor = conn.cursor()
        for upd in update:
            cursor.execute("UPDATE settings SET value=? WHERE name=?", (json.dumps(update[upd]), upd))
        conn.commit()
        cursor.close()
        conn.close()
    
    def get_channel_session(self, channel: discord.TextChannel) -> dict:
        if not self.sessions.get(channel.id, False):
            self.sessions[channel.id] = {
                'players': []
            }
        return self.sessions[channel.id] 
    
    
    @app_commands.command(name="play")
    async def royale_play(self, interaction: discord.Interaction):
        """Lancer une partie de KING (Battle Royale)"""
        await RegisterView(self, interaction).start()
        
                
async def setup(bot):
    await bot.add_cog(King(bot))
