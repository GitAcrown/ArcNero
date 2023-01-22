# pyright: reportGeneralTypeIssues=false

import asyncio
import logging
import random
import time
import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Callable, Any

import discord
from discord import app_commands
from discord.ext import commands
from tabulate import tabulate

from common.utils import pretty, fuzzy
from common.dataio import get_package_path, get_sqlite_database

logger = logging.getLogger('arcnero.Gold')
DEFAULT_SETTINGS = [
    ()
]

class AchievementsError(Exception):
    pass

class AchievementNotFound(AchievementsError):
    pass

class AchievementNavView(discord.ui.View):
    def __init__(self, member: discord.Member, trackers: List['Tracker'], *, timeout: Optional[float] = 180):
        super().__init__(timeout=timeout)
        self.member = member
        self.trackers = trackers
        self.pages = self._build_pages()
        self.current_page = 0
        self.message : discord.Message = None
    
    def _build_pages(self) -> discord.Embed:
        pages = []
        n = 0
        for t_index in range(0, len(self.trackers), 20):
            n += 1
            trackers = self.trackers[t_index:t_index + 20]
            embed = discord.Embed(title=f"**Liste des Succès** · {self.member.display_name}", color=0x2F3136)
            chunks = [(t.achievement.name, pretty.troncate_text(t.achievement.description, 50), t.progress_text()) for t in trackers]
            embed.description = '\n'.join([f"• **{chunk[0]} :** *{chunk[1]}* `{chunk[2]}`" for chunk in chunks])
            embed.set_footer(text=f"Page {n}/{len(self.trackers) // 20 + 1}")
            pages.append(embed)
        return pages
    
    async def start(self, interaction: discord.Interaction):
        if self.pages:
            self.message = await interaction.response.send_message(embed=self.pages[self.current_page], view=self)
        else:
            await interaction.response.send_message("Vous n'avez aucun succès en cours de complétion.", ephemeral=True)
            self.stop()
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Vous n'êtes pas autorisé à utiliser ces boutons.", ephemeral=True)
            return False
        return True
    
    @discord.ui.button(label="Précédent", style=discord.ButtonStyle.grey, disabled=True)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page == 0:
            return
        self.current_page -= 1
        self.button_logic()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
        
    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.grey)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page == len(self.pages) - 1:
            return
        self.current_page += 1
        self.button_logic()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
        
    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.red)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=None)
        self.stop()
        await interaction.delete_original_response()
        
    def button_logic(self):
        if self.current_page == 0:
            self.previous.disabled = True
        else:
            self.previous.disabled = False
        if self.current_page == len(self.pages) - 1:
            self.next.disabled = True
        else:
            self.next.disabled = False
    
    async def on_timeout(self) -> None:
        return await self.message.delete()


class Achievement():
    def __init__(self, 
                 cog: commands.Cog, 
                 local_id: str, 
                 name: str, 
                 description: str, 
                 prestige: int,
                 check_func: Callable[['Tracker'], bool], 
                 progress_func: Callable[['Tracker'], str], 
                 default_status: Any) -> None:
        self._cog = cog
        self.local_id = local_id
        self.full_id = f"{cog.qualified_name}.{local_id}"
        self.name = name.capitalize()
        self.description = description
        self.prestige = prestige
        self.check_func = check_func
        self.completion_func = progress_func
        self.default_status = default_status
        
    def __str__(self) -> str:
        return f"Achievement@{self.full_id}"
    
    def __eq__(self, __o: object) -> bool:
        if isinstance(__o, Achievement):
            return self.full_id == __o.full_id
        return False
    
    def _check(self, tracker: 'Tracker') -> bool:
        """Vérifie si l'objectif est atteint pour le tracker donné.

        :param tracker: Le tracker à vérifier
        :return: True si l'objectif est atteint, False sinon
        """
        return self.check_func(tracker)

    def _completion(self, tracker: 'Tracker') -> str:
        """Retourne un texte représentant l'avancement de l'objectif pour le tracker donné.

        :param tracker: Le tracker à vérifier
        :return: String représentant la progression de l'objectif
        """
        return self.completion_func(tracker)
    
    def get_tracker(self, member: discord.Member) -> 'Tracker':
        """Renvoie le tracker associé à l'utilisateur donné.

        :param member: L'utilisateur à tracker
        :return: Le tracker associé à l'utilisateur
        """
        return Tracker(self, member)
    

class Tracker():
    def __init__(self, achievement: Achievement, member: discord.Member) -> None:
        self.achievement = achievement
        self.member = member
        self.guild = member.guild
        self.id = f"{self.achievement.full_id}:{self.member.id}"
        
        self.__initialize_tracker()
        
    def __eq__(self, __o: object) -> bool:
        if isinstance(__o, Tracker):
            return self.id == __o.id
        return False
    
    def __str__(self) -> str:
        return f"Tracker@{self.id}"
    
    def __initialize_tracker(self):
        conn = get_sqlite_database('achievements', f"g{self.guild.id}")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO trackers (tracker_id, achievement_id, member_id, status, completed) VALUES (?, ?, ?, ?, ?)", (self.id, self.achievement.full_id, self.member.id, json.dumps(self.achievement.default_status), 0))
        conn.commit()
        cursor.close()
        conn.close()
        
    
    # Status du tracker
    def _get_status(self) -> dict:
        conn = get_sqlite_database('achievements', f"g{self.guild.id}")
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM trackers WHERE tracker_id = ?", (self.id,))
        status = json.loads(cursor.fetchone()[0])
        cursor.close()
        conn.close()
        return status
    
    def _set_status(self, status: Any):
        conn = get_sqlite_database('achievements', f"g{self.guild.id}")
        cursor = conn.cursor()
        cursor.execute("UPDATE trackers SET status = ? WHERE tracker_id = ?", (json.dumps(status), self.id))
        conn.commit()
        cursor.close()
        conn.close()
        
    @property
    def status(self) -> Any:
        """Retourne les paramètres du tracker.

        :return: Any
        """
        return self._get_status()
    
    @status.setter
    def status(self, status: Any):
        """Définit les paramètres du tracker.

        :param status: Any
        """
        self._set_status(status)
        
    # Complétion du tracker
    def _is_completed(self) -> bool:
        conn = get_sqlite_database('achievements', f"g{self.guild.id}")
        cursor = conn.cursor()
        cursor.execute("SELECT completed FROM trackers WHERE tracker_id = ?", (self.id,))
        completed = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return bool(completed)
    
    def _set_completed(self, status: bool):
        conn = get_sqlite_database('achievements', f"g{self.guild.id}")
        cursor = conn.cursor()
        cursor.execute("UPDATE trackers SET completed = ? WHERE tracker_id = ?", (int(status), self.id))
        conn.commit()
        cursor.close()
        conn.close()
    
    @property
    def completed(self) -> bool:
        """Retourne si l'objectif est atteint.

        :return: bool
        """
        return self._is_completed()
    
    def unlock(self) -> discord.Embed:
        """Marque le succès comme complété."""
        self._set_completed(True)
        
    def check(self, mark_as_completed: bool = True) -> bool:
        """Vérifie si l'objectif est atteint.

        :return: bool
        """
        s = self.achievement._check(self)
        if mark_as_completed and s:
            self.unlock()
        return s
    
    def eval(self, status: Any, mark_as_completed: bool = True) -> bool:
        """Vérifie si l'objectif est atteint avec les paramètres donnés

        :param status: Nouveau status du tracker
        :param mark_as_completed: Marquer le succès comme complété si atteint
        :return: bool
        """
        self.status = status
        return self.check(mark_as_completed)
    
    def progress_text(self) -> str:
        """Retourne un texte représentant l'avancement de l'objectif.

        :return: str
        """
        return self.achievement._completion(self)
    

class Achievements(commands.Cog):
    """Système centralisé d'obtention de succès"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        self.context_menu = app_commands.ContextMenu(
            name='Prestige',
            callback=self.usercommand_prestige,
        )
        self.bot.tree.add_command(self.context_menu)
        
    @commands.Cog.listener()
    async def on_ready(self):
        self._initialize_database()
        
    def _initialize_database(self):
        for guild in self.bot.guilds:
            conn = get_sqlite_database('achievements', f"g{guild.id}")
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS trackers (tracker_id TEXT PRIMARY KEY, achievement_id TEXT, member_id INTEGER, status MEDIUMTEXT, completed BOOLEAN CHECK (completed IN (0, 1)))")
            
            cursor.execute("CREATE TABLE IF NOT EXISTS settings (setting_name TINYTEXT PRIMARY KEY, value TEXT)")
            # for name, default_value in DEFAULT_SETTINGS:
            #     cursor.execute("INSERT OR IGNORE INTO settings (setting_name, value) VALUES (?, ?)", (name, json.dumps(default_value)))
            conn.commit()
            cursor.close()
            conn.close()
    
    def get_all_achievements(self, cog: commands.Cog = None) -> List[Achievement]:
        """Retourne la liste de tous les succès disponibles"""
        achievements = []
        cogs = [cog] if cog else self.bot.cogs.values()
        for c in cogs:
            if hasattr(c, '_achievements'):
                achievements.extend(c._achievements)
        return achievements
    
    def get_achievement(self, cog: commands.Cog, local_id: str) -> Achievement:
        """Retourne le succès correspondant à l'identifiant local donné.

        :param cog: Le cog contenant le succès
        :param local_id: L'identifiant local du succès
        :return: Achievement
        """
        full_id = f"{cog.qualified_name}.{local_id}"
        cog_achievements : List[Achievement] = getattr(cog, '_achievements', [])
        if full_id in [a.full_id for a in cog_achievements]:
            return cog_achievements[[a.full_id for a in cog_achievements].index(full_id)]
        raise AchievementNotFound(f"Le succès '{full_id}' n'existe pas dans le cog {cog.qualified_name}")
    
    def get_raw_achievement(self, full_id: str) -> Achievement:
        """Retourne le succès correspondant à l'identifiant global donné.

        :param global_id: L'identifiant global du succès
        :return: Achievement
        """
        cog_name, local_id = full_id.split('.')
        cog = self.bot.get_cog(cog_name)
        if cog is None:
            raise AchievementNotFound(f"Le succès '{full_id}' n'existe pas")
        return self.get_achievement(cog, local_id)

    
    def members_trackers(self, member: discord.Member) -> List[Tracker]:
        """Retourne la liste des trackers du membre donné.

        :param member: Membre dont on veut les trackers
        :return: List[Tracker]
        """
        conn = get_sqlite_database('achievements', f"g{member.guild.id}")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trackers WHERE member_id = ?", (member.id,))
        trackers = [Tracker(self.get_raw_achievement(dict(row)['achievement_id']), member) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return trackers
    
    def get_tracker(self, member: discord.Member, tracker_id: str) -> Tracker:
        """Retourne le tracker du succès donné pour le membre donné.

        :param member: Membre dont on veut le tracker
        :return: Tracker
        """
        trackers = self.members_trackers(member)
        for tracker in trackers:
            if tracker.id == tracker_id:
                return tracker
        return None
    
    def member_completed_achievements(self, member: discord.Member) -> List[Achievement]:
        """Retourne la liste des succès obtenus par le membre donné.

        :param member: Membre dont on veut les succès
        :return: List[Achievement]
        """
        return [t.achievement for t in self.members_trackers(member) if t.completed]
    
    def get_member_prestige(self, member: discord.Member) -> int:
        """Retourne le prestige total du membre donné.

        :param member: Membre dont on veut le prestige
        :return: int
        """
        if self.member_completed_achievements(member):
            return sum([a.prestige for a in self.member_completed_achievements(member)])
        return 0
    
    def get_prestige_embed(self, member: discord.Member) -> discord.Embed:
        """Retourne l'embed de prestige du membre donné.

        :param member: Membre dont on veut l'embed de prestige
        :return: discord.Embed
        """
        em = discord.Embed(title=f"**Prestige** · {member.display_name}", color=0x2F3136)
        em.add_field(name="Prestige", value=pretty.codeblock(f'{self.get_member_prestige(member)}', lang='css'))
        em.add_field(name="Succès débloqués", value=pretty.codeblock(f'{len(self.member_completed_achievements(member))}', lang='fix'))
        em.set_thumbnail(url=member.display_avatar.url)
        return em
        
        
    @app_commands.command(name="achievements")
    async def show_achievements(self, interaction: discord.Interaction, member: Optional[discord.Member] = None, tracker_id: Optional[str] = None):
        """Affiche la liste des succès obtenus par le membre donné

        :param member: Membre dont on veut les succès si spécifié
        :param tracker_id: Tracker du succès dont on veut les informations si spécifié
        """
        user = member if member else interaction.user
        if tracker_id:
            tracker = self.get_tracker(user, tracker_id)
            em = discord.Embed(title=f"**Succès** · {tracker.achievement.name} `{tracker.achievement}`", description=f"*{tracker.achievement.description}*", color=discord.Color.green() if tracker.completed else discord.Color.red())
            em.add_field(name="Progression", value=pretty.codeblock(tracker.progress_text() + f"{' (Obtenu)' if tracker.completed else ''}", lang='css' if tracker.completed else 'fix'))
            em.add_field(name="Prestige", value=pretty.codeblock(f'+{tracker.achievement.prestige}', lang='diff'))
            em.set_footer(text=f"{user.display_name}", icon_url=user.display_avatar.url)
            return await interaction.response.send_message(embed=em)
        
        await AchievementNavView(user, self.members_trackers(user)).start(interaction)
        
    @show_achievements.autocomplete('tracker_id')
    async def show_achievements_callback(self, interaction: discord.Interaction, current: str):
        trackers = self.members_trackers(interaction.user)
        if trackers:
            trackers = fuzzy.finder(current, [(t.achievement.name, t.id) for t in trackers], key=lambda s: s[0])
            return [app_commands.Choice(name=t[0], value=t[1]) for t in trackers]
        else:
            return []
    
    @app_commands.command(name="prestige")
    async def prestige_leaderboard(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        """Affiche le top des membres du serveur en fonction de leur prestige, ou le prestige du membre donné si spécifié

        :param member: Membre dont on veut le prestige
        """
        if member:
            return await interaction.response.send_message(embed=self.get_prestige_embed(member))

        members = [(m.name, self.get_member_prestige(m)) for m in interaction.guild.members]
        sorted_members = sorted(members, key=lambda m: m[1], reverse=True)
        em = discord.Embed(title=f"**Prestige** · Top 20 sur *{interaction.guild.name}*", description=pretty.codeblock(tabulate(sorted_members[:20], headers=('Membre', 'Prestige'))), color=0x2F3136)
        await interaction.response.send_message(embed=em)
        
    async def usercommand_prestige(self, interaction: discord.Interaction, member: discord.Member):
        """Menu contextuel permettant l'affichage du prestige d'un membre

        :param member: Utilisateur visé par la commande
        """
        return await interaction.response.send_message(embed=self.get_prestige_embed(member), ephemeral=True)
        
async def setup(bot: commands.Bot):
    await bot.add_cog(Achievements(bot))
