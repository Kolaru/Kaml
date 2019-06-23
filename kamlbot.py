import discord
import io
import time

from datetime import datetime

from difflib import get_close_matches

from discord import Embed, File, Message, TextChannel
from discord.ext import commands
from discord.ext.commands import Bot

from itertools import chain

from matplotlib import pyplot as plt

from player import PlayerManager, PlayerNotFoundError
from ranking import Ranking
from save_and_load import load_messages, load_ranking_config, load_tokens, parse_matchboard_msg
from utils import callback, connect, locking, logger


tokens = load_tokens()
ROLENAME = "Chamelier"

"""
    Kamlbot()

Main bot class.
"""
class Kamlbot(Bot):
    def __init__(self, *args, **kwargs):
        connect("ranking_updated", self.edit_leaderboard)
        connect("game_registered", self.send_game_result)

        self.player_manager = None
        self.ranking = None
        self.is_ready = False  # Determine if the bot is ready to process commands

        super().__init__(*args, **kwargs)

    """
        async Kamlbot.debug(msg)
    
    Log the given `msg` to the default logger with debug level and also send
    the message to the debug discord chan.
    """
    async def debug(self, msg):
        await self.debug_chan.send(msg)
        logger.debug(msg)
    
    """
        async Kamlbot.edit_leaderboard()
    
    Edit the leaderboard message with the current content.
    """
    async def edit_leaderboard(self):
        msg = await self.leaderboard.fetch_message(588703303932706835)
        await msg.edit(content=self.leaderboard_content(1, 20))
    
    """
        Kamlbot.get_player(*args, **kwargs)
    
    Wraps the `get_player` method of the player manager.
    """
    def get_player(self, *args, **kwargs):
        return self.player_manager.get_player(*args, **kwargs)

    """
        Kamlbot.leaderboard_content(start, stop[, experiment=False])
    
    Generate the string content of a leaderboard message.
    """
    # TODO Make this a method of the raniking object
    def leaderboard_content(self, start, stop, experimental=False):
        # Convert from base 1 indexing for positive ranks
        if start >= 0:
            start -= 1

        if experimental:
            ranking = self.experimental_ranking
        else:
            ranking = self.ranking

        new_content = "\n".join([self.message("leaderboard_line",
                                              player=player)
                                 for player in ranking[start:stop]])
        
        return f"```\n{new_content}\n```"
    
    """
        async Kamlbot.load_all()

    Load everything from files and fetch missing games from the PW matchboard
    channel.

    Erase the current state of the Kamlbot.
    """
    async def load_all(self):
        self.messages = load_messages()

        self.player_manager = PlayerManager()
        await self.player_manager.load_data()
        await self.update_mentions()

        ranking_config = load_ranking_config("base")
        self.ranking = Ranking(self.player_manager,
                               **ranking_config)

        await self.ranking.fetch_data(self.matchboard)

    """
        Kamlbot.message(msg_name, **kwargs)
    
    Return the message of the given `msg_name` using the key word arguments
    to format it.
    """
    # TODO Should not be a method of the Kamlbot class. Maybe a MessageManager
    # class may be useful.
    def message(self, msg_name, **kwargs):
        return self.messages[msg_name].format(**kwargs)

    # Called for every messages sent in any of the server to which the bot
    # has access.
    async def on_message(self, msg):
        # Only read messages if the bot is ready
        if not self.is_ready:
            return

        # Register the new games published in the PW matchboard
        if msg.channel == self.matchboard:
            game = parse_matchboard_msg(msg)
            if game is not None:
                await self.ranking.register_game(game)

        # Only process commands in the KAML server
        elif msg.guild.id == tokens["kaml_server_id"]:
            await self.process_commands(msg)

    # Called when the Bot has finished his initialization. May be called
    # multiple times.
    async def on_ready(self):
        # If the player_manager is set, it means this has already run at least once.
        if self.player_manager is not None:
            print("Too much on_ready")
            return

        # Retrieve special channels
        for chan in self.get_guild(tokens["kaml_server_id"]).channels:
            if chan.name == "debug":
                self.debug_chan = chan
            
            if chan.name == "kamlboard":
                self.kamlboard = chan
            
            if chan.name == "leaderboard":
                self.leaderboard = chan
        
        for chan in self.get_guild(tokens["pw_server_id"]).channels:
            if chan.name == "matchboard":
                self.matchboard = chan

        await self.change_presence(status=discord.Status.online)
        await self.debug("The Kamlbot is logged in.")
        logger.info(f"Kamlbot has logged in.")
        start_time = time.time()

        await self.load_all()

        dt = time.time() - start_time

        logger.info(f"Initialization finished in {dt:0.2f} s.")
        await self.debug(f"Initialization finished in {dt:0.2f} s.")
        self.is_ready = True

    @property
    def players(self):
        return self.player_manager.players
    
    """
        async send_game_result(change)
    
    Create a new message in the KAML matchboard.
    """
    async def send_game_result(self, change):
        msg = self.message("game_result_description",
                           change=change,
                           winner=change.winner,
                           loser=change.loser)

        embed = Embed(color=0xf36541,
                    timestamp=datetime.now(),
                    title=self.message("game_result_title"),
                    description=msg)

        embed.set_footer(text="")
        await self.kamlboard.send(embed=embed)

    """
        async update_mentions([player_manager=None])
    
    Update the string used to identify players for all players.

    Currently fetch the server nickname of every registered players.
    """
    @locking("mentions")
    async def update_mentions(self, player_manager=None):
        if player_manager is None:
            player_manager = self.player_manager

        for player in player_manager.claimed_players:
            user = await self.fetch_user(player.id)
            player.mention = user.display_name
            player_manager.alias_to_id[player.mention] = player.id
            

kamlbot = Kamlbot(command_prefix="!")

JET_ALIASES = ["#LegalizeEdgyMemes", "JetEriksen", "KSR JetEriksen"]

@kamlbot.check
async def check_available(cmd):
    if kamlbot.is_ready and not kamlbot.maintenance_mode:
        return True
    else:
        await cmd.channel.send("Kamlbot not ready, please wait a bit.")
        return False

@kamlbot.command(help="""
Associate in game name(s) to the user's discord profile.

Multiple names can be given at once.
""")
async def alias(cmd, *names):
    user = cmd.author

    logger.info("{0.mention} claims names {1}".format(user, names))

    if user.id == tokens["jet_id"] and any([name not in JET_ALIASES for name in names]):
        msg = kamlbot.message("anti_jet_meme")
        await cmd.channel.send(msg)
        return
    
    if len(names) == 0:
        player = kamlbot.get_player(user.id)
        if len(player.aliases) > 0:
            msg = kamlbot.message("associated_aliases",
                                user=user,
                                aliases="\n".join(player.aliases))
        else:
            msg = kamlbot.message("no_alias_error", user=user)
        
        await cmd.channel.send(msg)
        return
    
    taken = kamlbot.player_manager.extract_claims(names)

    if len(taken) > 0:
        taken_list = [kamlbot.message("taken_alias",
                                      alias=name,
                                      player=player)
                      for name, player in taken.items()]
        msg = kamlbot.message("not_associated_aliases",
                              n=len(taken),
                              taken_aliases="\n".join(taken_list))
        await cmd.channel.send(msg)
        return

    added, not_found = kamlbot.player_manager.associate_aliases(user.id, names)
    player = kamlbot.get_player(user.id)
    await kamlbot.update_mentions()

    if len(player.aliases) > 0:
        msg = kamlbot.message("associated_aliases",
                              user=user,
                              aliases="\n".join(player.aliases))
    else:
        msg = kamlbot.message("no_alias_error", user=user)

    if len(not_found) > 0:
        msg += kamlbot.message("not_found_aliases",
                               aliases="\n".join(not_found))

    await cmd.channel.send(msg)


# TODO bundle the stuff to find a player in a separate function
@kamlbot.command(help="""
Get a lot of info on a player.
""")
async def allinfo(cmd, player_name=None):
    if player_name is None:
        player_name = cmd.author.id

    try:
        player = kamlbot.get_player(player_name,
                                    test_mention=True,
                                    create_missing=False)
    except PlayerNotFoundError:
        msg = kamlbot.message("player_not_found_error",
                              player_name=player_name)
        await cmd.channel.send(msg)
        return

    fig, axes = plt.subplots(2, 2, sharex="col", sharey="row")
    skip = 10  # TODO use global constant MINGAMES
    times = player.times[skip:]
    days = (times - times[0])/(60*60*24)
    scores = player.scores[skip:]
    ranks = player.ranks[skip:]
    ns = range(skip, len(scores) + skip)

    ax = axes[0, 0]
    ax.plot(ns, scores)
    ax.set_ylabel("Score")

    ax = axes[0, 1]
    ax.plot(days, scores)

    ax = axes[1, 0]
    ax.plot(ns, ranks)
    ax.set_ylabel("Rank")
    ax.set_xlabel("Number of games played")

    ax = axes[1, 1]
    ax.plot(days, ranks)
    ax.set_xlabel("Days since first game")
    ax.set_ylim(ax.get_ylim()[::-1])  # ax.invert_yaxis() somehow doesn't work

    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    buf.seek(0)

    await cmd.channel.send(file=File(buf, "ranks.png"))

    buf.close()


@kamlbot.command(help="""
Compare two players, including the probability of win estimated by the Kamlbot.
""")
async def compare(cmd, p1_name, p2_name):
    try:
        p1 = kamlbot.get_player(p1_name,
                                test_mention=True,
                                create_missing=False)

    except PlayerNotFoundError:
        msg = kamlbot.message("player_not_found_error",
                              player_name=p1_name)
        await cmd.channel.send(msg)
        return
    
    try:
        p2 = kamlbot.get_player(p2_name,
                                test_mention=True,
                                create_missing=False)

    except PlayerNotFoundError:
        msg = kamlbot.message("player_not_found_error",
                              player_name=p2_name)
        await cmd.channel.send(msg)
        return

    msg = kamlbot.message("player_rank",
                          player=p1)

    msg += "\n" + kamlbot.message("player_rank",
                                  player=p2)
    
    
    comparison = kamlbot.ranking.comparison(p1, p2)

    if comparison is not None:
        msg += "\n" + kamlbot.message("win_probability",
                                      p1=p1,
                                      p2=p2,
                                      comparison=comparison)
    else:
        msg += "\n" + kamlbot.message("win_probability_blind",
                                      p1=p1,
                                      p2=p2,
                                      win_estimate=100*kamlbot.ranking.win_estimate(p1, p2))
    
    await cmd.channel.send(msg)


@kamlbot.command(help="""
[ADMIN] Create an experimental ranking with custom TS values.
""")
@commands.has_role(ROLENAME)
async def exp_ranking(cmd, mu, sigma, beta, tau):
    t = time.time()
    async with cmd.typing():
        player_manager = PlayerManager()
        await player_manager.load_data()
        await kamlbot.update_mentions(player_manager=player_manager)
        kamlbot.experimental_ranking = Ranking(player_manager,
                                               mu=eval(mu),
                                               sigma=eval(sigma),
                                               beta=eval(beta),
                                               tau=eval(tau))

        await kamlbot.experimental_ranking.fetch_data(kamlbot.matchboard)

        dt = time.time() - t

        await cmd.channel.send(f"Experimental ranking initialized in {dt:.2f} s.")


@kamlbot.command(help="""
[ADMIN] Show the experimental leaderboard.
""")
async def exp_leaderboard(cmd, start, stop):
    try:
        start = int(start)
        stop = int(stop)
    except ValueError:
        await cmd.channel.send("Upper and lower rank should be integers.")
        return
    
    if stop - start > 30:
        await cmd.channel.send("At most 30 line can be displayed at once in leaderboards.")
        return

    await cmd.channel.send(kamlbot.leaderboard_content(start, stop, experimental=True))


@kamlbot.command(help="""
Show the leaderboard between two ranks (maximum 30 lines).
""")
async def leaderboard(cmd, start, stop):
    try:
        start = int(start)
        stop = int(stop)
    except ValueError:
        await cmd.channel.send("Upper and lower rank should be integers.")
        return
    
    if stop - start > 30:
        await cmd.channel.send("At most 30 line can be displayed at once in leaderboards.")
        return
    
    await cmd.channel.send(kamlbot.leaderboard_content(start, stop))


@kamlbot.command(help="""
Return the rank and some additional information about the player.

If used without argument, return the rank of the player associated with the
discord profile of the user.
""")
async def rank(cmd, player_name=None):
    if player_name is None:
        player_name = cmd.author.id

    try:
        player = kamlbot.get_player(player_name,
                                    test_mention=True,
                                    create_missing=False)

    except PlayerNotFoundError:
        msg = kamlbot.message("player_not_found_error",
                              player_name=player_name)
        await cmd.channel.send(msg)
        return

    msg = kamlbot.message("player_rank",
                          player=player)
    await cmd.channel.send(msg)


@kamlbot.command(help="""
[ADMIN] Reload everything from files.
""")
@commands.has_role(ROLENAME)
async def reload(cmd):
    async with cmd.typing():
        t = time.time()
        kamlbot.maintenance_mode = True
        await kamlbot.load_all()
        kamlbot.maintenance_mode = False
        dt = time.time() - t
        await cmd.channel.send(f"Everything was reloaded (took {dt:.2f} s).")


@kamlbot.command(help="""
Search for a player. Optional argument `n` is the maximal number of name returned.
""")
async def search(cmd, name, n=5):
    matches = get_close_matches(name, kamlbot.player_manager.aliases,
                                n=n)
    
    msg = "\n".join(matches)
    await cmd.channel.send(f"```\n{msg}\n```")


@kamlbot.command(help="""
[Admin] Stop the bot.
""")
@commands.has_role(ROLENAME)
async def stop(cmd):
    print("Disconnecting Kamlbot")
    await kamlbot.change_presence(activity=None, status=discord.Status.offline)
    await kamlbot.info("The Kamlbot takes his leave.")
    logger.info("Disconnecting Kamlbot.")
    await kamlbot.close()


@kamlbot.command(help="""
[Admin] Test the bot.
""")
@commands.has_role(ROLENAME)
async def test(cmd):
    logger.info("The Kamlbot is being tested.")
    await cmd.channel.send("The Kamlbot is working.")

kamlbot.run(tokens["bot_token"])
