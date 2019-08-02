import discord
import git
import io
import os
import time
import sys

from datetime import datetime

from difflib import get_close_matches

from discord import Embed, File
from discord.ext import commands, tasks
from discord.ext.commands import Bot

from matplotlib import pyplot as plt

from identity import IdentityManager, IdentityNotFoundError
from messages import msg_builder
from ranking import ranking_types
from save_and_load import (load_ranking_configs, load_tokens,
                            parse_matchboard_msg, get_game_results)
from utils import connect, emit_signal, logger, partition


tokens = load_tokens()
ROLENAME = "Chamelier"


class Kamlbot(Bot):
    """Main bot class."""
    def __init__(self, *args, **kwargs):
        connect("rankings_updated", self.edit_leaderboard)
        connect("game_registered", self.send_game_result)

        self.identity_manager = None
        self.rankings = dict()
        self.is_ready = False

        super().__init__(*args, **kwargs)

        now = datetime.now()
        nextnoon = now.replace(day=now.day + 1, hour=12, minute=0,
                               second=0, microsecond=0)
        self.loop.call_at(nextnoon.timestamp(), self.at_noon.start)

    @tasks.loop(hours=24)
    async def at_noon(self):
        today = datetime.today()

        if today.weekday() == 0:  # 0 is for monday
            pass  # TODO restart weekly ranking

        if today.day == 1:
            pass  # TODO restart monthly ranking

    async def debug(self, msg):
        """Log the given `msg` to the default logger with debug level and
        also send the message to the debug discord chan.
        """
        await self.debug_chan.send(msg)
        logger.debug(msg)

    async def edit_leaderboard(self):
        """Edit the leaderboard messages with the current content."""
        for ranking in self.rankings.values():
            for msg in ranking.leaderboard_messages:
                try:
                    message = await self.fetch_message(msg["id"])
                    await message.edit(content=msg["content"])
                except discord.errors.NotFound:
                    logger.warning("Leaderboard message not found.")

    def find_names(self, nameparts, n=1):
        k = len(nameparts)

        if k == n:
            return nameparts

        for ps in partition(k, n):
            s = 0
            allgood = True
            names = []

            for p in ps:
                name = " ".join(nameparts[s:s+p])
                s += p
                names.append(name)

                if name not in self.identity_manager.aliases:
                    allgood = False
                    break

            if allgood:
                return names

        return None

    async def get_identities(self, nameparts, cmd=None, n=1):
        if isinstance(nameparts, str):
            nameparts = [nameparts]

        if len(nameparts) == 0:
            if cmd is None:
                logger.error("get_players called without any name nor command")
                await msg_builder.send(
                        cmd.channel,
                        "generic_error")

                raise IdentityNotFoundError()
                await msg_builder.send(
                        cmd.channel,
                        "no_alias_error",
                        user=cmd.author)

            identity = self.identity_manager[cmd.author.id]
            return (identity,)

        if len(nameparts) == n:
            try:
                return [self.identity_manager[name] for name in nameparts]
            except IdentityNotFoundError as err:
                await msg_builder.send(
                        cmd.channel,
                        "player_not_found_error",
                        player_name=err.searchkey)

                raise

        names = self.find_names(nameparts, n=n)

        if names is None:
            await msg_builder.send(
                    cmd.channel,
                    "unable_to_build_alias",
                    n=n)

            raise IdentityNotFoundError(" ".join(nameparts))

        else:
            return [self.identity_manager[name] for name in names]

    async def load_all(self):
        """Load everything from files and fetch missing games from the
        PW matchboard channel.

        Erase the current state of the Kamlbot.
        """
        msg_builder.reload()
        self.identity_manager = IdentityManager()
        self.identity_manager.load_data()

        logger.info("{Fetching game results.")

        ranking_configs = load_ranking_configs()

        for name, config in ranking_configs.items():
            self.rankings[name] = ranking_types[config["type"]](
                                    name,
                                    self.identity_manager,
                                    **config)

        game_results = await get_game_results(self.matchboard)
        for game in game_results:
            await self.register_game(game, save=False, signal_update=False)

        await self.update_mentions()
        await emit_signal("rankings_updated")

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
                await self.register_game(game)

        # Only process commands in the KAML server
        elif msg.guild.id == tokens["kaml_server_id"]:
            await self.process_commands(msg)

    # Called when the Bot has finished his initialization. May be called
    # multiple times (I have no idea why though)
    async def on_ready(self):
        # If the manager is set, it means this has already run at least once.
        if self.identity_manager is not None:
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

        if "-restart" in sys.argv:
            with open("config/restart_chan.txt", "r") as file:
                chan_id = int(file.readline())
                chan = self.get_channel(chan_id)

            await chan.send("I'm reborn! Initialization now begins.")

        else:
            chan = self.debug_chan
            await chan.send("The Kamlbot is logged in.")

        async with chan.typing():
            logger.info(f"Kamlbot has logged in.")
            start_time = time.time()

            await self.load_all()

            dt = time.time() - start_time

            logger.info(f"Initialization finished in {dt:0.2f} s.")
            await chan.send(f"Initialization finished in {dt:0.2f} s.")
            self.is_ready = True

    async def register_game(self, game, save=True, signal_update=True):
        if game["winner"] == "" or game["loser"] == "":
            return None

        for name, ranking in self.rankings.items():
            change = ranking.register_game(game, save=save)

            if name == "main":
                await emit_signal("game_registered", change)

        if signal_update:
            await emit_signal("rankings_updated")

    async def send_game_result(self, change):
        """Create a new message in the KAML matchboard."""
        msg = msg_builder.build("game_result_description",
                                change=change,
                                winner=change.winner,
                                loser=change.loser)

        embed = Embed(color=0xf36541,
                      timestamp=datetime.now(),
                      title=msg_builder.build("game_result_title"),
                      description=msg)

        embed.set_footer(text="")
        await self.kamlboard.send(embed=embed)

    async def update_display_names(self):
        """Update the string used to identify players for all players.

        Currently fetch the server nickname of every registered players.
        """

        for player_id in self.identity_manager.claimed_ids:
            user = await self.fetch_user(player_id)
            self.identity_manager[player_id].display_name = user.display_name


kamlbot = Kamlbot(command_prefix="!")


@kamlbot.check
async def check_available(cmd):
    if kamlbot.is_ready:
        return True
    else:
        await cmd.channel.send("Kamlbot not ready, please wait a bit.")
        return False

@kamlbot.command(help="""
Associate in game name(s) to the user's discord profile.

Multiple names can be given at once.
""")
async def alias(cmd, *names):
    # TODO Fix command
    await cmd.channel.send("Alias command is sadly currently broken. However, <@314190533301895178> can make the association manually.")
    return
    user = cmd.author

    logger.info("{0.mention} claims names {1}".format(user, names))

    try:
        player = await kamlbot.identity_manager[user.id]
    except IdentityNotFoundError:
        if len(names) > 0:
            player = kamlbot.identity_manager.add_player(player_id=user.id, aliases=[])
        else:
            await msg_builder.send(cmd.channel, "no_alias_error", user=user)
            return

    if len(names) == 0:
        if len(player.aliases) > 0:
            msg = msg_builder.build("associated_aliases",
                                    player=player,
                                    aliases="\n".join(player.aliases))
        else:
            msg = msg_builder.build("no_alias_error", user=user)

        await cmd.channel.send(msg)
        return

    taken = kamlbot.identity_manager.extract_claims(names)

    if len(taken) > 0:
        taken_list = [msg_builder.build("taken_alias",
                                        alias=name,
                                        player=player)
                      for name, player in taken.items()]
        await msg_builder.send("not_associated_aliases",
                               n=len(taken),
                               taken_aliases="\n".join(taken_list))
        return

    added, not_found = kamlbot.identity_manager.associate_aliases(user.id, names)
    await kamlbot.update_mentions()

    msg = msg_builder.build("associated_aliases",
                            player=player,
                            aliases="\n".join(player.aliases))

    if len(not_found) > 0:
        msg += msg_builder.build("not_found_aliases",
                                 aliases="\n".join(not_found))

    await cmd.channel.send(msg)


@kamlbot.command(help="""
Get a lot of info on a player.
""")
async def allinfo(cmd, *nameparts):
    try:
        identity, = await kamlbot.get_identities(nameparts, cmd=cmd, n=1)
    except IdentityNotFoundError:
        return

    player = kamlbot.rankings["main"][identity]

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

    if player.claimed:
        msg = msg_builder.build("associated_aliases",
                                player=player,
                                aliases="\n".join(player.aliases))
    else:
        msg = msg_builder.build("player_not_claimed",
                                player=player)

    await cmd.channel.send(msg)
    await cmd.channel.send(file=File(buf, "ranks.png"))

    buf.close()


@kamlbot.command(help="""
Compare two players, including the probability of win estimated by the Kamlbot.
""")
async def compare(cmd, *nameparts):
    try:
        i1, i2 = await kamlbot.get_identities(nameparts, cmd=cmd, n=2)
    except IdentityNotFoundError:
        return

    p1 = kamlbot.rankings["main"][i1]
    p2 = kamlbot.rankings["main"][i2]

    msg = msg_builder.build("player_rank",
                            player=p1)

    msg += "\n" + msg_builder.build("player_rank",
                                    player=p2)

    comparison = kamlbot.ranking.comparison(p1, p2)

    if comparison is not None:
        msg += "\n" + msg_builder.build("win_probability",
                                        p1=p1,
                                        p2=p2,
                                        comparison=comparison)
    else:
        msg += "\n" + msg_builder.build("win_probability_blind",
                                        p1=p1,
                                        p2=p2,
                                        win_estimate=100*kamlbot.ranking.win_estimate(p1, p2))

    await cmd.channel.send(msg)

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
        await cmd.channel.send("At most 30 line can be displayed at once in leaderboard.")
        return

    await cmd.channel.send(kamlbot.rankings["main"].leaderboard(start, stop))


@kamlbot.command(help="""
[Admin] Make the bot send `n` dummy messages.
""")
@commands.has_role(ROLENAME)
async def msg(cmd, n=1):
    for k in range(n):
        await cmd.channel.send(f"Dummy message {k+1}/{n}")


@kamlbot.command(help="""
Return the rank and some additional information about the player.

If used without argument, return the rank of the player associated with the
discord profile of the user.
""")
async def rank(cmd, *nameparts):
    try:
        identity, = await kamlbot.get_identities(nameparts, cmd=cmd, n=1)
    except IdentityNotFoundError:
        return

    player = kamlbot.rankings["main"][identity]

    await msg_builder.send(
            cmd.channel,
            "player_rank",
            player=player)


@kamlbot.command(help="""
[ADMIN] Reload everything from files.
""")
@commands.has_role(ROLENAME)
async def reload(cmd):
    async with cmd.typing():
        t = time.time()
        await kamlbot.load_all()
        dt = time.time() - t
        await cmd.channel.send(f"Everything was reloaded (took {dt:.2f} s).")


@kamlbot.command(help="""
[ADMIN] Restart the bot.
""")
@commands.has_role(ROLENAME)
async def restart(cmd, param=None):
    if param is not None:
        if param == "pull":
            await cmd.channel.send("Pulling changes from GitHub.")
            repo = git.Repo(os.getcwd())
            repo.remotes.origin.pull()
        else:
            await cmd.channel.send(f"Unknown parameter `{param}`.")
            
    await cmd.channel.send("I will now die and be replaced.")

    with open("config/restart_chan.txt", "w") as file:
        file.write(str(cmd.channel.id))

    os.execv(sys.executable, ["python", "kamlbot.py", "-restart"])


@kamlbot.command(help="""
Search for a player. Optional argument `n` is the maximal number of name returned.
""")
async def search(cmd, name, n=5):
    matches = get_close_matches(name, kamlbot.identity_manager.get_playerses,
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
    await cmd.channel.send("The Kamlbot takes his leave.")
    logger.info("Disconnecting Kamlbot.")
    await kamlbot.close()


@kamlbot.command(help="""
[Admin] Test the bot.
""")
@commands.has_role(ROLENAME)
async def test(cmd):
    logger.info("The Kamlbot is being tested.")
    await cmd.channel.send("The Kamlbot is working, working hard even.")

kamlbot.run(tokens["bot_token"])
