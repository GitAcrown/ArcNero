# pyright: reportGeneralTypeIssues=false

import asyncio
import logging
import random
import time
from datetime import datetime
from typing import List

import discord
from discord import app_commands
from discord.ext import commands

from cogs.economy import Economy
from cogs.achievements import Achievements, Achievement
from common.utils import pretty

logger = logging.getLogger('arcnero.MiniGames')

RUSSIAN_KILL_COM = [
    "Finalement {0} en avait dans la cervelle !",
    "Maintenant que {0} est parti·e on peut arrêter de jouer ! Non ? D'accord, très bien !",
    "NOOON. Pas {0} !",
    "Sa veste est à moi... Quoi, trop tôt ?",
    "Bien, je crois que {0} et moi ne pourront plus jouer à la roulette ensemble...",
    "Ci-gît {0}. Un gros nul.",
    "RIP {0}.",
    "Qui est mort ? Hein, {0} ? Ah on s'en fout alors.",
    "Qui est mort ? Hein, {0} ? NON ? NOOOOOOOOOOOOON",
    "J'aimais pas {0} de toute manière.",
    "Hey {0} ! Je suis revenu avec la bouffe ! Oh...",
    "Wow {0}, c'est presque de l'art moderne !",
    "Wow {0}, c'était joli ! RIP quand même.",
    "Sérieux ? C'est {0} qui est mort·e ? Ok, aucun suspens. Suivant.",
    "Est-ce que ça veut dire que je n'ai pas rendre le livre que {0} m'a prêté ?",
    "Mais non ! Il y a le sang de {0} partout sur le salon !",
    "Je ne t'oublierai jamais {0}...",
    "Au moins {0} ne fera plus chier personne.",
    "Ne me regardez pas comme ça, c'est vous qui allez nettoyer.",
    "Non je pleure pas, c'est vous qui pleurez. *snif*",
    "YES {0} ! JE SAVAIS QUE TU POUVAIS LE FAIRE !",
    "A jamais, {0}.",
    "Génial. On se retrouve qu'avec les gens chiant.",
    "Dommage, je t'aimais bien {0}. Maintenant va falloir que je stalk quelqu'un d'autre...",
    "Ouais. Encore un qu'il va falloir remplacer par un bot...",
    "Super, maintenant il ne reste que les ringards.",
    "Je crois que j'en ai un peu sur moi. Dégueulasse.",
    "J'ai même pas eu le temps d'aller chercher le popcorn. Vous êtes méchant.",
    "Bordel, {0} a eu le temps de chier dans son froc avant de tirer.",
    "Mince, je n'avais pas prévu un trou aussi large...",
    "10/10 j'ai adoré voir {0} s'exploser le crâne, c'était GRANDIOSE.",
    "J'espère que {0} avait une assurance vie...",
    "Oups, bye {0} ! Tu ne nous manquera pas !",
    "Au moins une chose de bien faite dans sa vie misérable...",
    "Y'a pas que ton compte en banque que t'as vidé, {0} !",
    "Je ne sais pas comment, mais {1} a sûrement triché.",
    "{0} disait qu'il voulait avoir une mort digne. Loupé.",
    "Bon arrête de pleurer {1}. {0} sait parfaitement ce qu'il fait c'est un PROFESSIONNEL.",
    "Donc c'est à ça vous ressemblez à l'intérieur !",
    "Mes condoléances {1}. Je sais que tu étais *très* proche de {0}.",
    "NON, DÎTES MOI QUE CE N'EST PAS VRAI ??? OSEF.",
    "Heure de mort {2}. Origine : la stupidité.",
    "Ne fais pas genre, tu as adoré {1} !",
    "Mince, j'aurais préféré que ce soit {1} !",
    "GE-NI-AL, {0} crève et {1} est toujours en vie ? Super...",
    "Est-ce que tu manges ? T'as aucun respect {1} ! {0} vient de se tirer une balle dans le crâne !",
    "Aya, ça a giclé partout, c'est un peu gore.",
    "Yes, Le diner est servi !",
    "Une fin beaucoup trop moche pour {0}, il méritait bien mieux...",
    "Une belle fin pour {0}, il servira d'engrais !",
    "MAIS ??? T'es sérieux de crever maintenant {0} ? Et notre serveur Minecraft ???",
    "MAIS ??? T'es sérieux de crever maintenant {0} ? Et notre guilde sur WoW ???",
    "Super l'ambiance, il est que {2} hein...",
    "Paix à {0}, mort aujourd'hui à {2} pile.",
    "Euh {1}, pourquoi t'as pris une photo des pieds ?",
    "T'es vraiment louche {1}, pourquoi tu regardes le cadavre de {0} comme ça gros dégénéré ?",
    "Je veux pas dire, mais c'était seulement du paintball et {0} est quand même mort.",
    "Yes, merci {0} de contribuer à la baisse du chômage !",
    "Mort en faisant ce qu'il aime, tirer des coups !",
    "Ne t'inquiète pas, j'irais chercher tes allocs à ta place.",
    "Je suis sûr que {0} a fait un pacte avec le diable."
    ]

class MiniGames(commands.GroupCog, group_name="minigame", description="Mini-jeux exploitant l'économie du bot"):
    """Mini-jeux divers et variés"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._achievements : List[Achievement] = [
            Achievement(self, 'masochist', 'Masochiste', "Jouer à 10 parties de roulette russe", 20, lambda tracker: int(tracker.status) >= 10, lambda tracker: f"{tracker.status}/10", 0),
            Achievement(self, 'firstdeath', 'Première mort', "Se faire tuer pour la première fois", 5, lambda tracker: int(tracker.status) >= 1, lambda tracker: f"{tracker.status}/1", 0),
            Achievement(self, 'unlucky', 'Malchanceux', "Se faire tuer au début d'un round", 10, lambda tracker: int(tracker.status) >= 1, lambda tracker: f"{tracker.status}/1", 0),
            Achievement(self, 'victory', 'Vainqueur', "Gagner une partie de roulette russe", 20, lambda tracker: int(tracker.status) >= 1, lambda tracker: f"{tracker.status}/1", 0),
            Achievement(self, 'champion', 'Grand champion', "Gagner 10 parties de roulette russe", 50, lambda tracker: int(tracker.status) >= 10, lambda tracker: f"{tracker.status}/10", 0),
            Achievement(self, 'crimeboss', 'Patron du crime', "Gagner 1000 crédits en jouant à la roulette russe", 30, lambda tracker: int(tracker.status) >= 1000, lambda tracker: f"{tracker.status}/1000", 0),
            Achievement(self, 'slotmaster', 'Maître de la machine', "Gagner 1000 crédits en jouant à la machine à sous", 30, lambda tracker: int(tracker.status) >= 1000, lambda tracker: f"{tracker.status}/1000", 0),
        ]
        self.roulette = {}
        
    @app_commands.command(name="slot")
    @app_commands.checks.cooldown(5, 60)
    async def slot_machine(self, interaction: discord.Interaction, bet: app_commands.Range[int, 0, 100]):
        """Jouer à la machine à sous

        :param bet: Montant mis en jeu (compris entre 1 et 100), 0 = tableau des gains
        """
        member = interaction.user
        bank : Economy = self.bot.get_cog('Economy')
        achv : Achievements = self.bot.get_cog('Achievements')
        currency = bank.guild_currency(interaction.guild)
        if not bet:
            em = discord.Embed(title="Tableau des gains", description="```Fruit = Offre + 100{}\nTrèfle = Offre + 3x Offre\nPièce = Offre + 5x Offre```".format(currency), color=0x2F3136)
            em.set_footer(text="Vous êtes toujours remboursé lorsque vous gagnez.")
            return await interaction.response.send_message(embed=em)
        
        account = bank.get_account(member)
        if account.balance < bet:
            return await interaction.response.send_message(f"**Solde insuffisant ·** Vous n'avez pas {bet}{currency} sur votre compte")
        
        await interaction.response.defer()
        await asyncio.sleep(1)
        symbols = ['🍎', '🍊', '🪙', '🍇', '🍀']
        wheel = ['🍀', '🍎', '🍊', '🪙', '🍇', '🍀', '🍎']
        def _column(previous_center=None):
            if previous_center:
                pv_index = wheel.index(previous_center)
                center = random.choice([wheel[pv_index - 1], wheel[pv_index], wheel[pv_index + 1]])
            else:
                center = random.choice(symbols)
            top, bottom = wheel[symbols.index(center) + 2], wheel[symbols.index(center)]
            return top, center, bottom
        
        cola = _column()
        colb = _column(cola[1])
        colc = _column(colb[1])
        columns = [cola, colb, colc]
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
            account.deposit_credits(credits, "Gain à la machine à sous").save()
            a_slotmaster = achv.get_achievement(self, 'slotmaster').get_tracker(member)
            a_slotmaster.eval(a_slotmaster.status + credits)
        else:
            em.set_footer(text=f"Vous perdez votre mise ({pretty.humanize_number(bet)}{currency})")
            account.withdraw_credits(bet, "Perte à la machine à sous").save()
        await interaction.followup.send(embed=em)
        
    @app_commands.command(name="russian")
    async def russian_roulette(self, interaction: discord.Interaction, bet: app_commands.Range[int, 20, 100]):
        """Jouer à la roulette russe (jusqu'à 6 joueurs)

        :param bet: Montant mis en jeu (compris entre 20 et 100)
        """
        channel : discord.TextChannel = interaction.channel
        guild : discord.Guild = interaction.guild
        bank : Economy = self.bot.get_cog('Economy')
        achv : Achievements = self.bot.get_cog('Achievements')
        currency = bank.guild_currency(guild)
        default_cache = {
            'open': False,
            'playing': False,
            'players': {},
            'minimal_bet': 20
            }
        if not self.roulette.get(channel.id, {}):
            self.roulette[channel.id] = default_cache
            
        if self.roulette[channel.id]['playing']:
            return await interaction.response.send_message(f"**Partie en cours ·** Il y a déjà une partie en cours sur ce salon, attendez qu'elle se termine !", ephemeral=True)
        
        user_account = bank.get_account(interaction.user)
        if not self.roulette[channel.id]['open']:
            if user_account.balance < bet:
                return await interaction.response.send_message(f"**Solde insuffisant ·** Vous n'avez pas {bet}{currency} sur votre compte !", ephemeral=True)
            try:
                first_trs = user_account.withdraw_credits(bet, 'Mise roulette russe')
                first_trs.save()
            except:
                return await interaction.response.send_message(f"**Transaction impossible ·** Il y a eu un problème lors du retrait de votre mise de votre compte.", ephemeral=True)
            self.roulette[channel.id]['minimal_bet'] = bet
            self.roulette[channel.id]['players'][interaction.user.id] = {'bet': bet, 'alive': True}
            self.roulette[channel.id]['open'] = True
            await interaction.response.send_message(f"**Roulette russe ·** Un lobby a été ouvert par **{interaction.user.name}** avec une mise minimale de **{bet}**{currency}\nRejoignez vite la partie avec `/minigame russian` ! (max. 6 joueurs)")
            
            timeout = int(time.time() + 60)
            while time.time() < timeout and len(list(self.roulette[channel.id]['players'].keys())) < 6:
                await asyncio.sleep(0.5)
            self.roulette[channel.id]['open'] = False
            if len(self.roulette[channel.id]['players'].keys()) < 2:
                user_account.cancel_transaction(first_trs, "Remboursement mise roulette russe").save()
                return await channel.send(f"**Roulette russe annulée ·** Partie annulée en raison du manque de joueurs\n{interaction.user.mention} a été remboursé de sa mise.")
            await channel.send(f"**Fermeture du lobby ·** La partie va bientôt commencer !")
            
        else:
            if len(self.roulette[channel.id]['players'].keys()) >= 6:
                return await interaction.response.send_message(f"**Lobby plein ·** Il y a déjà 6 joueurs dans le lobby !", ephemeral=True)
            if bet < self.roulette[channel.id]['minimal_bet']:
                return await interaction.response.send_message(f"**Mise insuffisante ·** Vous ne pouvez pas miser moins que le créateur du lobby, c'est-à-dire {self.roulette[interaction.channel_id]['minimal_bet']}{currency} !", ephemeral=True)
            if user_account.balance < bet:
                return await interaction.response.send_message(f"**Solde insuffisant ·** Vous n'avez pas {bet}{currency} sur votre compte !", ephemeral=True)
            try:
                user_account.withdraw_credits(bet, 'Mise roulette russe').save()
            except:
                return await interaction.response.send_message(f"**Transaction impossible ·** Il y a eu un problème lors du retrait de votre mise de votre compte", ephemeral=True)
            self.roulette[channel.id]['players'][interaction.user.id] = {'bet': bet, 'alive': True}
            return await interaction.response.send_message(f"**Nouveau joueur ·** ***{interaction.user.name}*** a rejoint la partie avec une mise de **{bet}**{currency} !")
        
        steps = [
            'Je vais mettre une balle dans ce revolver...',
            '...puis faire tourner le barrilet un coup...',
            '...et vous vous le passerez à tour de rôle...',
            f"...jusqu'à que l'un de vous s'explose {random.choice(['le crâne', 'la tête', 'la caboche'])} !",
            'Soyez le dernier en vie, et vous remporterez la mise.',
            'Bonne chance !'
        ]
        msg = None
        for i in range(6):
            em = discord.Embed(description=f'**Préparation... ({i+1}/6) ·** *{steps[i]}*', color=0x2F3136)
            em.set_footer(text='•' * min(i + 1, len(self.roulette[interaction.channel_id]['players'].keys())))
            if msg:
                await msg.edit(embed=em)
            else:
                msg = await channel.send(embed=em)
            await asyncio.sleep(2)
            
        for p_id in self.roulette[channel.id]['players']:
            p = guild.get_member(p_id)
            a_maso = achv.get_achievement(self, 'masochist').get_tracker(p)
            a_maso.eval(a_maso.status + 1)
        
        round = 1
        while len([p for p in self.roulette[interaction.channel_id]['players'] if self.roulette[interaction.channel_id]['players'][p]['alive']]) > 1:
            if round > 1:
                round_msg = random.choice((f"***{self.bot.user.name}*** remet en ordre le révolver...", 
                    f"***{self.bot.user.name}*** remet une balle dans le barillet...", 
                    f"***{self.bot.user.name}*** nettoie le révolver avant de le recharger d'une balle..."))
            else:
                round_msg = f"***{self.bot.user.name}*** charge le révolver..."
            await channel.send(round_msg)
            await asyncio.sleep(1.5)
            
            await channel.send(f"**~~────~~ Round {round} ~~────~~**")
            chamber = 6
            circle = list([p for p in self.roulette[interaction.channel_id]['players'] if self.roulette[interaction.channel_id]['players'][p]['alive']])[:]
            random.shuffle(circle)
            circle = circle * 3
            turn_count = 0
            while chamber:
                turn_count += 1
                shot = random.randint(1, chamber) == 1 
                player = guild.get_member(circle[0])
                player_txt = random.choice(("**{}** presse le révolver à sa tempe et appuie doucement sur la détente...",
                                            "**{}** dirige le révolver vers son crâne et pose son doigt sur la détente...",
                                            "**{}** place le révolver sous sa machoire et s'apprête à appuyer sur la détente..."))
                await channel.send(player_txt.format(player.name))
                if shot:
                    await asyncio.sleep(random.uniform(3.0, 4.0))
                    await channel.send(f"` 💥 ` **BANG ·** **{player.name}** {random.choice(['est mort.e', 'est décédé.e', 'est inanimé.e', 'a crevé.e', 'est inerte'])}")
                    self.roulette[interaction.channel_id]['players'][player.id]['alive'] = False
                    
                    com_player = random.choice([guild.get_member(p).name for p in self.roulette[interaction.channel_id]['players'] if self.roulette[interaction.channel_id]['players'][p]['alive']])
                    death_time = datetime.now().strftime('%H:%M:%S')
                    com_msg = random.choice(RUSSIAN_KILL_COM).format(player.name, com_player, death_time)
                    await asyncio.sleep(random.uniform(2.5, 3.5))
                    await channel.send(com_msg)
                    
                    if turn_count == 1:
                        a_unlucky = achv.get_achievement(self, 'unlucky').get_tracker(player)
                        a_unlucky.eval(a_unlucky.status + 1)
                    
                    a_firstdeath = achv.get_achievement(self, 'firstdeath').get_tracker(player)
                    a_firstdeath.eval(a_firstdeath.status + 1)
                    break
                else:
                    await asyncio.sleep(random.uniform(2.0, 3.0))
                    rdm = random.choice(["est sauvé.e", "a survécu.e", "n'a rien eu", "est sain et sauf"])
                    emoji = random.choice(['` 🍀 `', '` 😳 `', '` 💯 `', '` 🙏 `', '` 🤞 `'])
                    await channel.send(f"{emoji} **CLICK ·** **{player.name}** {rdm}")
                    circle.remove(circle[0])
                    chamber -= 1
                    await asyncio.sleep(2)
            round += 1
        
        await asyncio.sleep(2)
        endmsg = await channel.send(f"**PARTIE TERMINÉE ·** Nous avons un.e gagnant.e !")
        await asyncio.sleep(2)
        winner = guild.get_member([p for p in self.roulette[interaction.channel_id]['players'] if self.roulette[interaction.channel_id]['players'][p]['alive']][0])
        total_bet = sum([self.roulette[interaction.channel_id]['players'][p]['bet'] for p in self.roulette[interaction.channel_id]['players']])

        winner_account = bank.get_account(winner)
        winner_account.deposit_credits(total_bet, "Gain roulette russe").save()
        
        a_victory = achv.get_achievement(self, 'victory').get_tracker(winner)
        a_victory.eval(a_victory.status + 1)
        
        a_champion = achv.get_achievement(self, 'champion').get_tracker(winner)
        a_champion.eval(a_champion.status + 1)
        
        a_crimeboss = achv.get_achievement(self, 'crimeboss').get_tracker(winner)
        a_crimeboss.eval(a_crimeboss.status + total_bet)
        
        em = discord.Embed(description=f"Bravo {winner.mention}, tu es la dernière personne en vie !\nTu remportes la totalité des mises, c'est-à-dire **{pretty.humanize_number(total_bet)}**{currency}.", color=0x2F3136)
        await endmsg.edit(embed=em)
        
        self.roulette[channel.id] = default_cache
                
                
async def setup(bot):
    await bot.add_cog(MiniGames(bot))
