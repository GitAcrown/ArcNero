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

logger = logging.getLogger('arcnero.Saga')
PACKAGE_PATH = get_package_path('saga')

DEFAULT_SETTINGS = [
    ()
]

class Player():
    def __init__(self, cog: 'Saga', member: discord.Member) -> None:
        self._cog = cog
        self.member = member
        self.guild = member.guild
        
        self.__initialize_player()
        
    def __initialize_player(self):
        try:
            conn = get_sqlite_database('saga', f'g{self.guild.id}')
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO players (user_id) VALUES (?, )", (self.member.id, ))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Erreur dans l'initialisation du joueur : {e}", exc_info=True)
    
    
class BaseItem():
    def __init__(self, cog: 'Saga', id: str) -> None:
        self._cog = cog
        self.id = id
        
    

class Saga(commands.Cog):
    """Système central de jeu"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @commands.Cog.listener()
    async def on_ready(self):
        self._initialize_database()
        self.PACKS = self._load_packs()
        
    @commands.COg.listener()
    async def on_guild_join(self, _: discord.Guild):
        self._initialize_database()
        
    def _initialize_database(self):
        for guild in self.bot.guilds:
            conn = get_sqlite_database('saga', f'g{guild.id}')
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS players (user_id INTEGER PRIMARY KEY)")
            cursor.execute("CREATE TABLE IF NOT EXISTS settings (name TINYTEXT PRIMARY KEY, value TEXT)")
            for name, default_value in DEFAULT_SETTINGS:
                cursor.execute("INSERT OR IGNORE INTO settings (name, value) VALUES (?, ?)", (name, json.dumps(default_value)))
                
            conn.commit()
            cursor.close()
            conn.close()
    
    def _load_package_files(self):
        with open(os.path.join(PACKAGE_PATH, 'items.yaml'), 'r') as f:
            self.ITEMS = yaml.safe_load(f)
            
        with open(os.path.join(PACKAGE_PATH, 'effects.yaml'), 'r') as f:
            self.EFFECTS = yaml.safe_load(f)
        
        logger.info("Données de jeu chargées")
        
    
                
async def setup(bot):
    await bot.add_cog(Saga(bot))
