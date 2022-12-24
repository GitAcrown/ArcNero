# pyright: reportGeneralTypeIssues=false

import discord
from discord import app_commands
from discord.ext import commands
from tabulate import tabulate
import logging
import random
import asyncio
from common.utils import pretty
from cogs.economy import Economy
from typing import Optional

logger = logging.getLogger('arcnero.MiniGames')

class MiniGames(commands.GroupCog, group_name="minigame", description="Mini-jeux exploitant l'économie du bot"):
    """Mini-jeux divers et variés"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @app_commands.command(name="slot")
    @app_commands.checks.cooldown(5, 60)
    async def slot_machine(self, interaction: discord.Interaction, bet: Optional[app_commands.Range[int, 1, 100]] = 0):
        """Jouer à la machine à sous

        :param bet: Montant mis en jeu (max. 100), ne rien mettre permet de consulter le tableau des gains
        """
        member = interaction.user
        bank : Economy = self.bot.get_cog('Economy')
        currency = bank.guild_currency(interaction.guild)
        if not bet:
            em = discord.Embed(title="Tableau des gains", description="```Fruit = Offre + 100{}\nTrèfle = Offre + 3x Offre\nPièce = Offre + 5x Offre```".format(currency), color=0x2F3136)
            em.set_footer(text="Vous êtes toujours remboursé lorsque vous gagnez.")
            return await interaction.response.send_message(embed=em)
        
        account = bank.get_account(member)
        if account.balance < bet:
            return await interaction.response.send_message(f"**Erreur ·** Vous n'avez pas {bet}{currency} sur votre compte")
        
        await interaction.response.defer()
        await asyncio.sleep(1.5)
        symbols = ['🍎', '🍊', '🪙', '🍇', '🍀']
        wheel = ['🍀', '🍎', '🍊', '🪙', '🍇', '🍀', '🍎']
        def _column():
            center = random.choice(symbols)
            top, bottom = wheel[symbols.index(center) + 2], wheel[symbols.index(center)]
            return top, center, bottom
        
        columns = [_column(), _column(), _column()]
        center_row = [columns[0][1], columns[1][1], columns[2][1]]
        if center_row[0] == center_row[1] == center_row[2]:
            if center_row[0] in ['🍎', '🍊', '🍇', ]:
                credits = bet + 100
                wintxt = "3x Fruit !"
            elif center_row[0] == '🍀':
                credits = bet + (bet * 3)
                wintxt = "3x Trèfle !"
            else:
                credits = bet + (bet * 5)
                wintxt = "3x Pièce d'or !"
        else:
            credits = 0
            wintxt = ''
        
        txt = f"┇{columns[0][0]}┋{columns[1][0]}┋{columns[2][0]}┇\n"
        txt += f"▸{columns[0][1]}▪{columns[1][1]}▪{columns[2][1]}◂\n"
        txt += f"┇{columns[0][2]}┋{columns[1][2]}┋{columns[2][2]}┇"
        em = discord.Embed(color=0x2F3136, description=pretty.codeblock(txt, 'fix'), title=f'**Machine à sous** | `Mise : {bet}{currency}`')
        if credits:
            em.set_footer(text=f"{wintxt}\nVous gagnez {pretty.humanize_number(credits)}{currency}")
            trs = account.deposit_credits(credits, "Gain à la machine à sous")
        else:
            em.set_footer(text=f"Vous perdez votre mise ({pretty.humanize_number(bet)}{currency})")
            trs = account.withdraw_credits(bet, "Perte à la machine à sous")
        trs.save()
        await interaction.followup.send(embed=em)
    
async def setup(bot):
    await bot.add_cog(MiniGames(bot))
