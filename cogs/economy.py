# pyright: reportGeneralTypeIssues=false

import discord
import time
import json
from discord import app_commands
from discord.ext import commands
from common.dataio import get_sqlite_database, get_tinydb_database
from tinydb import TinyDB, Query
from common.utils import pretty, fuzzy
from typing import List, Optional
from datetime import datetime
from tabulate import tabulate
import logging

logger = logging.getLogger('arcnero.Economy')

DEFAULT_SETTINGS = [
    ('defaultBalance', 200),
    ('stringCurrency', '✦'),
    ('dailyAllowance', 100),
    ('limitAllowance', 1000)
]
TRANSACTION_EXPIRATION_DELAY = 604800 # 7 jours
TRANSACTIONS_CLEANUP_DELAY = 3600 # 1 heure

class EconomyError(Exception):
    pass

    class ForbiddenOperation():
        """Soulevée lorsqu'une opération bancaire impossible a été tentée"""
        

class TransactionsHistoryView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, cog: 'Economy', member: discord.Member):
        super().__init__(timeout=120)
        self.initial_interaction = interaction
        self.cog = cog
        self.member = member
        
        self.transactions = cog.get_member_transactions(member)
        self.current_page = 0
        self.pages : List[discord.Embed] = self.create_pages()
        
        self.previous.disabled = True
        if len(self.pages) <= 1:
            self.next.disabled = True
        
        self.message : discord.InteractionMessage = None
        
    async def interaction_check(self, interaction: discord.Interaction):
        is_author = interaction.user.id == self.initial_interaction.user.id
        if not is_author:
            await interaction.response.send_message(
                "L'auteur de la commande est le seul à pouvoir consulter l'historique.",
                ephemeral=True,
            )
        return is_author
    
    async def on_timeout(self) -> None:
        await self.message.edit(view=self.clear_items())
        
    def create_pages(self):
        embeds = []
        tabl = []
        for trs in self.transactions[::-1]:
            if len(tabl) < 20:
                tabl.append((f"{trs.ftime} {trs.fdate}", f"{trs.delta:+}", f"{pretty.troncate_text(trs.message, 50)}"))
            else:
                em = discord.Embed(color=0x2F3136, description=pretty.codeblock(tabulate(tabl, headers=("Date", "Delta", "Message"))))
                em.set_author(name=f"Historique des transactions · {self.member}", icon_url=self.member.display_avatar.url)
                em.set_footer(text=f"{len(self.transactions)} transactions enregistrées dans les {int(TRANSACTION_EXPIRATION_DELAY / 86400)} derniers jours")
                embeds.append(em)
                tabl = []
        
        if tabl:
            em = discord.Embed(color=0x2F3136, description=pretty.codeblock(tabulate(tabl, headers=("Date", "Delta", "Message")))) 
            em.set_author(name=f"Historique des transactions · {self.member}", icon_url=self.member.display_avatar.url)
            em.set_footer(text=f"{len(self.transactions)} transactions enregistrées dans les {int(TRANSACTION_EXPIRATION_DELAY / 86400)} derniers jours")
            embeds.append(em)
            
        return embeds
    
    async def start(self):
        if self.pages:
            await self.initial_interaction.response.send_message(embed=self.pages[self.current_page], view=self)
        else:
            await self.initial_interaction.response.send_message("Votre historique de transactions est vide.")
            self.stop()
            return self.clear_items()
        self.message = await self.initial_interaction.original_response()
        
    async def buttons_logic(self, interaction: discord.Interaction):
        self.previous.disabled = self.current_page == 0
        self.next.disabled = self.current_page + 1 >= len(self.pages)
        await interaction.message.edit(view=self) #type: ignore
        
    @discord.ui.button(label="Précédent", style=discord.ButtonStyle.secondary)
    async def previous(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Previous button"""
        self.current_page = max(0, self.current_page - 1)
        await self.buttons_logic(interaction)
        await interaction.response.edit_message(embed=self.pages[self.current_page])

    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Next button"""
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        await self.buttons_logic(interaction)
        await interaction.response.edit_message(embed=self.pages[self.current_page])
    
    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.primary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Close"""
        self.stop()
        await self.message.delete()


class Account():
    def __init__(self, cog: 'Economy', member: discord.Member) -> None:
        self.cog = cog
        self.member = member
        self.guild = member.guild
        self.__initialize_account()
        
    def __eq__(self, o: object) -> bool:
        return self.member.id == o.member.id
    
    def __str__(self) -> str:
        return f"{pretty.humanize_number(self._get_balance())}{self.cog.guild_currency(self.guild)}"

        
    def __initialize_account(self):
        try:
            conn = get_sqlite_database('economy', 'g' + str(self.guild.id))
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO accounts (member_id, balance) VALUES (?, ?)", (self.member.id, self.cog.get_guild_settings(self.guild)['defaultBalance']))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Erreur dans l'initialisation du compte : {e}", exc_info=True)
        
    # Balance --------------------------------------------
    def _get_balance(self) -> int:
        conn = get_sqlite_database('economy', 'g' + str(self.guild.id))
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM accounts WHERE member_id=?", (self.member.id,))
        balance = cursor.fetchone()
        cursor.close()
        conn.close()
        if balance:
            return balance[0]
        return 0
    
    def _set_balance(self, value: int, message: str, **extras) -> 'Transaction':
        current = self._get_balance()
        
        if value < 0:
            raise EconomyError.ForbiddenOperation("Impossible d'avoir un solde négatif")
        conn = get_sqlite_database('economy', 'g' + str(self.guild.id))
        cursor = conn.cursor()
        cursor.execute("UPDATE accounts SET balance=? WHERE member_id=?", (value, self.member.id))
        conn.commit()
        cursor.close()
        conn.close()
        
        return Transaction(self.cog, self, value - current, message, time.time(), **extras)
        
    @property
    def balance(self):
        """Somme possédée par le membre"""
        return self._get_balance()
    
    def set_credits(self, amount: int, message: str, **extras) -> 'Transaction':
        """Modifier la quantité de crédits possédés par le membre

        :param amount: Nouveau solde du membre
        :param message: Message attaché à la transaction
        :return: Transaction
        """
        return self._set_balance(amount, message, **extras)
        
    def deposit_credits(self, amount: int, message: str, **extras) -> 'Transaction':
        """Déposer des crédits sur le compte

        :param amount: Nombre de crédits à déposer
        :param message: Description de la transaction
        :return: Transaction
        """
        balance = self._get_balance()
        return self._set_balance(balance + abs(amount), message, **extras)
    
    def withdraw_credits(self, amount: int, message: str, **extras) -> 'Transaction':
        """Retirer des crédits du compte

        :param amount: Nombre de crédits à retirer
        :param message: Description de la transaction
        :return: Transaction
        """
        balance = self._get_balance()
        return self._set_balance(balance - abs(amount), message, **extras)
    
    
    def balance_variation(self, since: float = 0.0) -> int:
        """Calcule la variation du solde depuis un timestamp

        :param start: Timestamp depuis lequel calculer la variation du solde, par défaut toutes celles non-expirées
        :return: int 
        """
        trs = self.cog.get_member_transactions(self.member, since)
        return sum((i.delta for i in trs))
    
    # Utils --------------------------------
    def get_embed(self) -> discord.Embed:
        """Génère un Embed représentant le compte du membre

        :return: discord.Embed
        """
        em = discord.Embed(title=f"Compte Bancaire · *{self.member.display_name}*", color=0x2F3136)
        em.add_field(name="Solde", value=pretty.codeblock(self.__str__()))
        
        balance_var = self.balance_variation(time.time() - 86400) # 1 jour
        em.add_field(name="Variation (24h)", value=pretty.codeblock(f'{balance_var:+}', lang='fix' if balance_var < 0 else 'css'))
        
        lb = self.cog.guild_leaderboard(self.guild)
        try:
            lb_rank = lb.index(self) + 1
            em.add_field(name="Rang", value=pretty.codeblock(f"#{lb_rank}"))
        except:
            em.add_field(name="Rang", value=pretty.codeblock(f"#{len(lb) + 1}"))
        
        trs = self.cog.get_member_transactions(self.member)
        if trs:
            txt = '\n'.join([f'{t.delta:+} · {pretty.troncate_text(t.message, 50)}' for t in trs][::-1][:5])
            em.add_field(name="Dernières transactions", value=pretty.codeblock(txt), inline=False)
        
        em.set_thumbnail(url=self.member.display_avatar.url)
        return em
    
    
class Transaction():
    def __init__(self, cog: 'Economy', account: Account, delta: int, message: str, timestamp: float, **extras) -> None:
        self.cog = cog
        self.account = account
        self.delta = delta
        self.message = message
        self.timestamp = timestamp
        self.extras : dict = extras
        
        self.id : str = self.__generate_transaction_id()
        
    def __generate_transaction_id(self) -> str:
        return f"${hex(int(self.timestamp * 100))[2:]}:{self.account.member.id}"
    
    def __str__(self) -> str:
        return f'{self.id} · {self.message}'
    
    def __int__(self) -> int:
        return self.delta
    
    @property
    def fdate(self) -> str:
        """Renvoie le timestamp formatté au format JJ/MM/AAAA

        :return: str
        """
        return datetime.now().fromtimestamp(self.timestamp).strftime('%d/%m/%Y')

    @property
    def ftime(self) -> str:
        """Renvoie le timestamp formatté au format HH:MM

        :return: str
        """
        return datetime.now().fromtimestamp(self.timestamp).strftime('%H:%M')
    
    def save(self):
        """Sauvegarder la transaction dans la base de données"""
        conn = get_sqlite_database('economy', 'g' + str(self.account.guild.id))
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO transactions (id, timestamp, delta, message, member_id, extras) VALUES (?, ?, ?, ?, ?, ?)", 
                       (self.id, self.timestamp, self.delta, self.message, self.account.member.id, json.dumps(self.extras)))
        conn.commit()
        cursor.close()
        conn.close()
        
        # Nettoyage de la BDD
        expire = self.timestamp - TRANSACTION_EXPIRATION_DELAY
        self.cog.cleanup_transactions(self.account.guild, expire)
        
    @classmethod
    def load(cls, cog: 'Economy', guild: discord.Guild, data: dict):
        """Charger un objet Transaction depuis ses données brutes"""
        if not guild.get_member(data['member_id']):
            raise ValueError(f"Impossible d'obtenir le membre USER_ID={data['member_id']}")
        
        account = Account(cog, guild.get_member(data['member_id']))
        return cls(cog, account, data['delta'], data['message'], data['timestamp'], **data['extras'])
    

class Economy(commands.Cog):
    """Gestion de l'économie sur le bot"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_cleanup : float = 0.0
        
        self.context_menu = app_commands.ContextMenu(
            name='Compte Bancaire',
            callback=self.usercommand_account_info
        )
        self.bot.tree.add_command(self.context_menu)
        
    @commands.Cog.listener()
    async def on_ready(self):
        self._initialize_database()
        
    def _initialize_database(self):
        for guild in self.bot.guilds:
            conn = get_sqlite_database('economy', 'g' + str(guild.id))
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS accounts (member_id INTEGER PRIMARY KEY, balance INTEGER CHECK (balance >= 0))")
            cursor.execute("CREATE TABLE IF NOT EXISTS transactions (id TINYTEXT PRIMARY KEY, timestamp INTEGER, delta INTEGER, message TEXT, member_id INTEGER, extras MEDIUMTEXT, FOREIGN KEY (member_id) REFERENCES accounts(member_id))")
            
            cursor.execute("CREATE TABLE IF NOT EXISTS settings (setting_name TINYTEXT PRIMARY KEY, value TEXT)")
            for name, default_value in DEFAULT_SETTINGS:
                cursor.execute("INSERT OR IGNORE INTO settings (setting_name, value) VALUES (?, ?)", (name, json.dumps(default_value)))
            conn.commit()
            cursor.close()
            conn.close()
    
    
    def get_account(self, member: discord.Member) -> Account:
        """Renvoie le compte en banque du membre

        :param member: Membre dont on veut récupérer le compte
        :return: Account
        """
        return Account(self, member)
    
    def get_raw_accounts(self, guild: discord.Member) -> dict:
        """Retourne tous les comptes d'un serveur au format brut (dictionnaire)

        :param guild: Serveur dont on veut obtenir les comptes
        :return: dict
        """
        conn = get_sqlite_database('economy', 'g' + str(guild.id))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts")
        accounts = cursor.fetchall()
        cursor.close()
        conn.close()
        if accounts:
            return {a[0]: a[1] for a in accounts}
        else:
            return {}
        
        
    def get_guild_settings(self, guild: discord.Guild) -> dict:
        """Obtenir les paramètres économiques du serveur

        :param guild: Serveur des paramètres à récupérer
        :return: dict
        """
        conn = get_sqlite_database('economy', 'g' + str(guild.id))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings")
        settings = cursor.fetchall()
        cursor.close()
        conn.close()
        return {s[0] : json.loads(s[1]) for s in settings}
    
    def set_guild_settings(self, guild: discord.Guild, update: dict):
        """Met à jours les paramètres du serveur

        :param guild: Serveur à mettre à jour
        :param update: Paramètres à mettre à jour (toutes les valeurs seront automatiquement sérialisés en JSON)
        """
        conn = get_sqlite_database('economy', 'g' + str(guild.id))
        cursor = conn.cursor()
        for upd in update:
            cursor.execute("UPDATE settings SET value=? WHERE setting_name=?", (json.dumps(update[upd], ensure_ascii=False), upd))
        conn.commit()
        cursor.close()
        conn.close()
        
        
    def guild_currency(self, guild: discord.Guild) -> str:
        """Renvoie le symbole représentant la monnaie du serveur

        :param guild: Serveur de la monnaie voulue
        :return: str
        """
        return self.get_guild_settings(guild)['stringCurrency']
    
    def guild_total_credits(self, guild: discord.Guild) -> int:
        """Renvoie la quantité totale de crédits en circulation sur un serveur

        :param guild: Serveur dont on veut connaître la quantité de crédits
        :return: int
        """
        accounts = self.get_raw_accounts(guild)
        return sum([accounts[a] for a in accounts])
    
    def guild_leaderboard(self, guild: discord.Guild, top_cutoff: int = None) -> List[Account]:
        """Génère le leaderboard des comptes bancaires sur un serveur

        :param guild: Serveur dont on veut obtenir le leaderboard
        :param top_cutoff: Limite de membres renvoyés, par défaut tout le top
        :return: List[Account] ordonné par solde décroissant
        """
        members = self.get_raw_accounts(guild)
        sorted_members = sorted(list(members.items()), key=lambda u: u[1], reverse=True)
        top_accounts = []
        for member_id, _ in sorted_members:
            member = guild.get_member(member_id)
            if member:
                top_accounts.append(Account(self, member))
        return top_accounts[:top_cutoff] if top_cutoff else top_accounts
    
    
    def create_transaction(self, member: discord.Member, amount: int, message: str, **extras) -> Transaction:
        """Créer une nouvelle transaction
        
        Attention, la transaction créée n'est pas automatiquement sauvegardée dans la base de données !
        Utilisez Transaction.save() pour cela.

        :param member: Membre concerné par la transaction
        :param amount: Somme en circulation (-X si négative)
        :param message: Message associé à la transaction
        :param extras: Données supplémentaires à stocker si besoin
        :return: Transaction
        """
        account = self.get_account(member)
        return Transaction(self, account, amount, message, time.time(), extras)
    
    def get_guild_transactions(self, guild: discord.Guild, since: float = 0.0) -> List[Transaction]:
        """Récupère toutes les transactions non-expirées réalisées sur le serveur

        :param guild: Serveur des transactions
        :param since: Timestamp minimal de l'échantillon à récupérer (par défaut, 0.0)
        :return: List[Transaction]
        """
        conn = get_sqlite_database('economy', 'g' + str(guild.id))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE timestamp >=?", (since,))
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        data = [{'id': i[0], 'timestamp': i[1], 'delta': i[2], 'message': i[3], 'member_id': i[4], 'extras': json.loads(i[5])} for i in data]
        
        transactions = []
        for t in data:
            if not guild.get_member(t['member_id']):
                continue
            transactions.append(Transaction.load(self, guild, t))
        return transactions
    
    def get_member_transactions(self, member: discord.Member, since: float = 0.0) -> List[Transaction]:
        """Récupère toutes les transactions non-expirées réalisées par un membre

        :param member: Membre responsable des transactions
        :param since: Timestamp minimal de l'échantillon à récupérer (par défaut, 0.0)
        :return: List[Transaction]
        """
        conn = get_sqlite_database('economy', 'g' + str(member.guild.id))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE member_id=? AND timestamp >=?", (member.id, since))
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        data = [{'id': i[0], 'timestamp': i[1], 'delta': i[2], 'message': i[3], 'member_id': i[4], 'extras': json.loads(i[5])} for i in data]
        
        transactions = []
        for t in data:
            transactions.append(Transaction.load(self, member.guild, t))
        return transactions
    
    def get_transaction(self, guild: discord.Guild, transaction_id: str) -> Transaction:
        """Récupère un objet Transaction à partir de son identifiant unique

        :param guild: Serveur de la transaction
        :param transaction_id: Identifiant unique de la transaction
        :return: Transaction ou None si aucune transaction n'a été trouvée
        """
        transactions = self.get_guild_transactions(guild)
        for t in transactions:
            if t.id == transaction_id:
                return t
        return None
    
    def cleanup_transactions(self, guild: discord.Guild, expire_timestamp: float):
        """Efface toutes les transactions plus vieilles que le timestamp fourni

        :param guild: Serveur où il faut faire le nettoyage
        :param expire_timestamp: Timestamp avant lequel toutes les transactions doivent être supprimées (exclusif)
        """
        if time.time() <= self.last_cleanup + TRANSACTIONS_CLEANUP_DELAY:
            return # On s'assure que le processus de nettoyage se fasse pas trop souvent pour limiter des appels inutiles à la base de données
        conn = get_sqlite_database('economy', 'g' + str(guild.id))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transactions WHERE timestamp < ?", (expire_timestamp,))
        conn.commit()
        cursor.close()
        conn.close()
        self.last_cleanup = time.time()


    # COMMANDES ======================================================================
    
    @app_commands.command(name='account')
    @app_commands.guild_only
    async def account_info(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        """Affiche votre compte bancaire virtuel, ou celui d'un membre si spécifié

        :param member: Membre dont vous voulez consulter le compte
        """
        account = self.get_account(member if member else interaction.user)
        await interaction.response.send_message(embed=account.get_embed())
        
    async def usercommand_account_info(self, interaction: discord.Interaction, member: discord.Member):
        """Menu contextuel permettant l'affichage du compte bancaire virtuel d'un membre

        :param member: Utilisateur visé par la commande
        """
        account = self.get_account(member)
        await interaction.response.send_message(embed=account.get_embed(), ephemeral=True)
        
    @app_commands.command(name='history')
    @app_commands.guild_only
    async def transactions_history(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        """Affiche l'historique de vos dernières transactions, ou celles d'un membre si spécifié

        :param member: Membre dont vous voulez consulter le compte
        """
        member = member if member else interaction.user
        await TransactionsHistoryView(interaction, self, member).start()
        
    @app_commands.command(name='transfer')
    @app_commands.guild_only
    async def transfer_credits(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 0], message: Optional[str] = ''):
        """Réaliser un transfert d'argent à un membre

        :param member: Receveur du transfert
        :param amount: Nombre de crédits à transférer
        :param message: Message qui sera lié à la transaction
        """
        receiver = self.get_account(member)
        sender = self.get_account(interaction.user)
        if receiver == sender:
            return await interaction.response.send_message(f"**Erreur ·** Vous ne pouvez pas vous transférer de l'argent à vous-même !", ephemeral=True)
        
        currency = self.guild_currency(interaction.guild)
        try:
            sender_trs = sender.withdraw_credits(amount, f'Transfert à {receiver.member}')
        except EconomyError.ForbiddenOperation():
            return await interaction.response.send_message(f"**Erreur ·** Vous n'avez pas assez de crédits pour réaliser cette opération.\nVotre solde est actuellement de **{sender}**", ephemeral=True)
        else:
            receiver_trs = receiver.deposit_credits(amount, f"Transfert de {sender.member}" if not message else f"{sender.member} » {message}")
            
            sender_trs.extras['linked_transaction_id'] = receiver_trs.id
            sender_trs.save()
            receiver_trs.extras['linked_transaction_id'] = sender_trs.id
            receiver_trs.save()
            await interaction.response.send_message(f"**Transfert réalisé ·** {member.mention} a reçu {pretty.humanize_number(amount)}{currency} de votre part.")
    
    @app_commands.command(name='daily')
    @app_commands.guild_only
    async def get_daily_income(self, interaction: discord.Interaction):
        """Récupérer son allocation journalière définie par la banque (pour les membres les plus précaires)"""
        settings = self.get_guild_settings(interaction.guild)
        account = self.get_account(interaction.user)
        currency = self.guild_currency(interaction.guild)
        if account.balance >= settings['limitAllowance']:
            return await interaction.response.send_message(f"**Allocation non versée ·** Votre solde est au delà de la limite imposée par la banque ({pretty.humanize_number(settings['limitAllowance'])}{currency}).", ephemeral=True)

        today = datetime.now().strftime('%d/%m/%Y')
        db = get_tinydb_database('economy', 'cooldowns')
        db = db.table(str(interaction.guild.id))
        User = Query()
        cooldown = db.get(User.uid == interaction.user.id)
        if cooldown:
            if cooldown['last_daily'] == today:
                return await interaction.response.send_message(f"**Allocation non versée ·** Vous avez déjà perçu votre allocation pour aujourd'hui.", ephemeral=True)
        
        trs = account.deposit_credits(settings['dailyAllowance'], "Allocation d'aide journalière")
        trs.save()
        db.upsert({'uid': interaction.user.id, 'last_daily': today}, User.uid == interaction.user.id)
        await interaction.response.send_message(f"**Allocation versée ·** Vous avez reçu **{pretty.humanize_number(settings['dailyAllowance'])}{currency}**\nVous avez désormais {account}", ephemeral=True)
        
    @app_commands.command(name='leaderboard')
    @app_commands.guild_only
    async def show_guild_leaderboard(self, interaction: discord.Interaction, top: app_commands.Range[int, 1, 50] = 10):
        """Affiche un leaderboard des comptes bancaires du serveur

        :param top: Nombre de membres à afficher, par défaut 10 (max. 50)
        """
        lb = self.guild_leaderboard(interaction.guild, top)
        currency = self.guild_currency(interaction.guild)
        chunks = []
        rank = 1
        for account in lb:
            chunks.append((rank, account.member.name, account.balance))
            rank += 1
        if not chunks:
            return await interaction.response.send_message(f"**Erreur ·** Il m'est impossible de générer un leaderboard sur ce serveur", ephemeral=True)
        em = discord.Embed(color=0x2F3136, title=f"**Leaderboard** · {interaction.guild.name}", description=pretty.codeblock(tabulate(chunks, headers=('#', 'Membre', 'Solde')), lang='css')) #type: ignore
        em.set_footer(text=f"Crédits en circulation : {pretty.humanize_number(self.guild_total_credits(interaction.guild))}{currency}")
        await interaction.response.send_message(embed=em)
        
        
    @app_commands.command(name="bankset")
    @app_commands.guild_only
    @app_commands.checks.has_permissions(manage_messages=True)
    async def set_bank_settings(self, interaction: discord.Interaction, setting: str, value: str):
        """Modifier les paramètres de la banque (paramètres économiques du serveur)

        :param setting: Nom du paramètre à modifier
        :param value: Valeur à attribuer au paramètre (sera sérialisé en JSON)
        """
        if setting not in [s[0] for s in DEFAULT_SETTINGS]:
            return await interaction.response.send_message(f"**Erreur ·** Le paramètre `{setting}` n'existe pas", ephemeral=True)
        try:
            self.set_guild_settings(interaction.guild, {setting: value})
        except Exception as e:
            logger.error(f"Erreur dans set_bank_settings : {e}", exc_info=True)
            return await interaction.response.send_message(f"**Erreur ·** Il y a eu une erreur lors du réglage du paramètre, remontez cette erreur au propriétaire du bot", ephemeral=True)
        await interaction.response.send_message(f"**Succès ·** Le paramètre `{setting}` a été réglé sur `{value}`", ephemeral=True)
        
    @set_bank_settings.autocomplete('setting')
    async def autocomplete_callback(self, interaction: discord.Interaction, current: str):
        banksettings = tuple(self.get_guild_settings(interaction.guild).items())
        stgs = fuzzy.finder(current, banksettings, key=lambda bs: bs[0])
        return [app_commands.Choice(name=f'{s[0]} ({s[1]})', value=s[0]) for s in stgs]
    
    @app_commands.command(name="setbalance")
    @app_commands.guild_only
    @app_commands.checks.has_permissions(manage_messages=True)
    async def edit_member_balance(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 0], message: Optional[str] = ''):
        """Modifier le solde d'un membre

        :param interaction: _description_
        :param member: Membre dont vous désirez modifier le solde
        :param amount: Nouveau solde du membre
        :param message: Message à attacher à cette modification (pour la transaction)
        """
        maccount = self.get_account(member)
        trs = maccount.set_credits(amount, message if message else f'Modif. du solde par {interaction.user}', manual_edit=True)
        trs.save()
        await interaction.response.send_message(f"**Succès ·** Le nouveau solde de {member.mention} est de {maccount}.")

async def setup(bot):
    await bot.add_cog(Economy(bot))
