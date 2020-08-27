import asyncio
import discord
import git
import io
import numpy as np
import pandas as pd
import os
import sys
import time

from datetime import datetime, timedelta

from difflib import get_close_matches

from discord import Embed, File
from discord.ext import commands, tasks
from discord.ext.commands import Bot

from matplotlib import pyplot as plt

from messages import msg_builder
from ranking import ranking_types
from save_and_load import (load_ranking_configs, load_tokens,
                           parse_matchboard_msg, fetch_game_results)
from utils import logger, partition


tokens = load_tokens()
ROLENAME = "Chamelier"


class PlayerNotFound(Exception):
    pass


class Kamlbot(Bot):
    """
    Main bot class.

    Attributes
    ==========
    aliases: pandas.DataFrame, columns=(player_id,), indexed by alias
        Dataframe associating aliases to players.
    games: pandas.DataFrame, columns=(timestamp, winner_id, loser_id), indexed
           by game_id.
        Dataframe of all the games.
    is_ready: bool
        Flag storing whether the bot is ready to process commands.
    on_ready_ran: bool
        Flag storing wether the `on_ready` function has already been called.
        Somehow discord.py API sometimes calls it multiple time, so we use this
        flag to avoid running it multiple times.
    players: pandas.DataFrame, columns=(discord_id, display_name), indexed by
             player_id
        Dataframe of all none players.
    rankings: dict of AbstractRanking
        Dict of all rankings, indexed by their name.
    ranking_configs: dict of dict
        Dict of configuration for the rankings.
    """
    def __init__(self, *args, **kwargs):
        self.rankings = dict()
        self.is_ready = False
        self.on_ready_ran = False

        super().__init__(*args, **kwargs)

        # Set up the daily check by starting the loop at the next noon
        now = datetime.utcnow()  # use UTC timezone for easier standardization across different servers
        nextnoon_date = now + timedelta(days=1)
        nextnoon = nextnoon_date.replace(hour=12, minute=0, second=0,
                                         microsecond=0)
        self.loop.call_at(nextnoon.timestamp(), self.at_noon.start)

    @tasks.loop(hours=24)
    async def at_noon(self):
        """
        Task running every 24 hours.

        Currently only responsible for restarting the weekly ranking.
        """
        today = datetime.utcnow()

        if today.weekday() == 0:  # 0 is for monday
            # Restart weekly ranking

            self.clean_leaderboards()

            for name, config in self.ranking_configs.items():
                chan = discord.utils.get(self.kaml_server.text_channels,
                                         name=config["leaderboard_chan"])

                for leaderboard_msg in config["leaderboard_msgs"]:
                    leaderboard_msg["msg"] = await chan.send(
                        "Temporary message, will be edited with the "
                        "leaderboard once the bot is ready.")

            config = self.ranking_configs["weekly"]
            self.rankings["weekly"] = ranking_types[config["type"]](
                                        name,
                                        self.identity_manager,
                                        **config)

            # TODO check the following:
            #   - timestamp of last monday doesn-t seem to be set
            #   - leaderboard messages are not updated

    @tasks.loop(hours=24)  # common factors for each month total days (28, 29, 30, 31) is 1, so check every day
    async def at_first_month_day(self):
        """
        Task running every beginning of each day.

        Checks to see if it's the beginning of a new month and restarts monthly ranking.
        """
        today = datetime.utcnow()

        if today.day == 1:
            pass  # TODO restart monthly ranking

    async def clean_leaderboards(self):
        """
        Remove all learderboard messages for all rankings.
        """
        channels = set()
        for name, config in self.ranking_configs.items():
            chan = discord.utils.get(self.kaml_server.text_channels,
                                     name=config["leaderboard_chan"])

            channels.add(chan)

        for chan in channels:
            async for msg in chan.history():
                await msg.delete()

    async def update_leaderboards(self):
        """
        Update all leaderboard messages with up to date information.
        """
        for ranking in self.rankings.values():
            await ranking.update_leaderboard()

    def find_names(self, nameparts, n=1):
        """
        Given a list of parts `nameparts` try to construct `n` valid player
        names by combining them with spaces. Return `None` if valid names can
        not be constructed.

        For example for `n = 2` and `nameparts = ["A", "B", "C"]` this function
        checks the database for either players "A B" and "C" or players
        "A" and "B C".
        """
        k = len(nameparts)

        # If there are as much parts as requested aliases, each part must
        # correspond to a single alias.
        # TODO Should the existence of the aliases be checked here ?
        if k == n:
            return nameparts

        aliases = self.aliases.index  # All known aliases

        # Iterate over all possible partition of the name parts
        for ps in partition(k, n):
            s = 0
            names = []
            # Whether all names built with that partition are valid
            allgood = True

            for p in ps:
                # Build the candidate name from the given partition
                name = " ".join(nameparts[s:s+p])
                s += p
                names.append(name)

                if name not in aliases:
                    allgood = False
                    break

            if allgood:
                return names

        return None

    async def get_ids(self, nameparts, cmd=None, n=1):
        # TODO Check if that function is used somewhere
        if isinstance(nameparts, str):
            nameparts = [nameparts]

        if len(nameparts) == 0:
            if cmd is None:
                logger.error("get_ids called without name nor command")
                await msg_builder.send(
                        cmd.channel,
                        "generic_error")

                raise PlayerNotFound()

            player_id = self.id_from_discord_id(cmd.author.id)

            if player_id is None:
                await msg_builder.send(
                        cmd.channel,
                        "no_alias_error")
                raise PlayerNotFound()
            else:
                return (player_id,)

        if len(nameparts) == n:
            names = nameparts
        else:
            names = self.find_names(nameparts, n=n)

        if names is None:
            await msg_builder.send(
                    cmd.channel,
                    "unable_to_build_alias",
                    n=n)

            raise PlayerNotFound()

        player_ids = self.aliases.loc[names]["player_id"]

        for (pid, name) in zip(player_ids, nameparts):
            if np.isnan(pid):
                await msg_builder.send(
                        cmd.channel,
                        "player_not_found_error",
                        player_name=name)

            raise PlayerNotFound()

        return player_ids

    def id_from_alias(self, alias):
        # TODO this needs to be refactored
        # Seem to create a player if the alias is not found but doesn't check
        # discord names
        if alias in self.aliases.index:
            return self.aliases.loc[alias, "player_id"]

        self.players = self.players.append(dict(discord_id=None,
                                                display_name=alias),
                                           ignore_index=True)

        player_id = self.players.iloc[-1].name

        alias_data = pd.DataFrame(dict(player_id=player_id),
                                  index=[alias])
        self.aliases = self.aliases.append(alias_data)
        return player_id

    def id_from_discord_id(self, discord_id):
        indexes = self.players.index[self.players["discord_id"] == discord_id]

        if indexes.empty:
            return None

        return indexes[0]

    def load_dataframes(self):
        import pathlib
        if pathlib.Path("data/games.csv").exists():
            players = pd.DataFrame(
                columns=[
                    "discord_id",
                    "display_name"
                ]
            )

            aliases = pd.DataFrame(
                columns=[
                    "alias",
                    "player_id"
                ]
            )
            aliases.set_index("alias", inplace=True)

            games = pd.read_csv("data/games.csv", index_col="msg_id")
        else:
            players = pd.DataFrame(
                columns=[
                    "discord_id",
                    "display_name"
                ]
            )

            aliases = pd.DataFrame(
                columns=[
                    "alias",
                    "player_id"
                ]
            )
            aliases.set_index("alias", inplace=True)

            games = pd.DataFrame(
                columns=[
                    "msg_id",
                    "timestamp",
                    "winner_id",
                    "loser_id"
                ]
            )
            games.set_index("msg_id", inplace=True)

        return players, aliases, games

    async def load_all(self):
        """
        Load everything from files and fetch missing games from the
        PW matchboard channel.

        Erase the current state of the Kamlbot.
        """
        msg_builder.reload()
        self.ranking_configs = load_ranking_configs()

        # TODO Put this in separate function with logging
        now = datetime.utcnow()
        last_monday_date = now - timedelta(days=now.weekday())
        last_monday = last_monday_date.replace(hour=12, minute=0, second=0,
                                               microsecond=0)
        self.ranking_configs["weekly"]["oldest_timestamp_to_consider"] = last_monday.timestamp()

        await self.clean_leaderboards()

        # TODO put loading from files here
        self.players, self.aliases, self.games = self.load_dataframes()

        for name, config in self.ranking_configs.items():
            chan = discord.utils.get(self.kaml_server.text_channels,
                                     name=config["leaderboard_chan"])

            for leaderboard_msg in config["leaderboard_msgs"]:
                leaderboard_msg["msg"] = await chan.send(
                    "Temporary message, will be edited with the leaderboard "
                    "once the bot is ready.")

            self.rankings[name] = ranking_types[config["type"]](
                                    name,
                                    bot=self,
                                    **config)

        try:
            msg_data = self.games.iloc[-1]
            last_msg = await self.matchboard.fetch_message(msg_data.name)
        except IndexError:
            last_msg = None

        fetched_games = await fetch_game_results(self.matchboard,
                                                 after=last_msg)
        logger.info(f"{len(fetched_games)} new results fetched from matchboard.")

        # new_games = []

        # for game in fetched_games:
        #     if game["winner"] == "" or game["loser"] == "":
        #         continue

        #     if game["winner"] is None or game["loser"] is None:
        #         continue

        self.games = pd.concat(
            [
                self.games, 
                fetched_games.dropna().copy(deep=True)
            ]
        )

        self.games.to_csv("data/games.csv")

        #     game["winner_id"] = self.id_from_alias(game["winner"])
        #     game["loser_id"] = self.id_from_alias(game["loser"])
            # new_games.append(game)

            # self.games.loc[game["msg_id"]] = [
            #     game["timestamp"],
            #     game["winner_id"],
            #     game["loser_id"]
            # ]

        self.games.loc[:,["winner","loser"]] = self.games[["winner", "loser"]].applymap(self.id_from_alias)

        for name, ranking in self.rankings.items():
            logger.info(f"Registering game in ranking {name}")
            # ranking.register_many(new_games) TODO redo that for efficiency ?
            new_games = self.games[(self.games["timestamp"] >= 
                                    self.ranking_configs[name]["oldest_timestamp_to_consider"])]
            # for game in new_games:
            #     ranking.register_game(**game)
            for game in new_games.itertuples():
                print(game)

        await self.update_display_names()
        await self.update_leaderboards()

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
        if self.on_ready_ran:
            logger.info("Ignoring on_ready as one already ran.")
            return
        else:
            self.on_ready_ran = True

        self.kaml_server = self.get_guild(tokens["kaml_server_id"])

        # Retrieve special channels
        # self.debug_chan = discord.utils.get(self.kaml_server.text_channels,
        #                                     name="debug")

        # self.kamlboard = discord.utils.get(self.kaml_server.text_channels,
        #                                    name="kamlboard")

        for _ in range(100):
            # TODO check that this works
            self.matchboard = self.get_channel(tokens["matchboard_channel_id"])
            self.debug_chan = discord.utils.get(self.kaml_server.text_channels,
                                            name="debug")
            self.kamlboard = discord.utils.get(self.kaml_server.text_channels,
                                           name="kamlboard")
            await asyncio.sleep(2)
            if (self.matchboard is not None) & (self.debug_chan is not None) & (self.kamlboard is not None):
                break
            # logger.info("Retrying connection to PW matchboard")
            logger.info("Retrying connection to channels")

        await self.change_presence(status=discord.Status.online)

        # Whether the bot should consider itself to have been restarted
        if "-restart" in sys.argv:
            with open("config/restart_chan.txt", "r") as file:
                chan_id = int(file.readline())
                chan = self.get_channel(chan_id)

            await chan.send("I'm reborn! Initialization now begins.")

        else:
            chan = self.debug_chan
            # await chan.send("The Kamlbot is logged in.")

        async with chan.typing():
            # logger.info(f"Kamlbot has logged in.")
            start_time = time.time()

            await self.load_all()

            dt = time.time() - start_time

            logger.info(f"Initialization finished in {dt:0.2f} s.")
            await chan.send(f"Initialization finished in {dt:0.2f} s.")
            self.is_ready = True

    async def register_game(self, game):
        # TODO unpack game dict directly
        if game["winner"] == "" or game["loser"] == "":
            return None

        if game["winner"] is None or game["loser"] is None:
            return None

        game["winner_id"] = self.id_from_alias(game["winner"])
        game["loser_id"] = self.id_from_alias(game["loser"])

        game_data = pd.DataFrame(
            dict(
                timestamp=game["timestamp"],
                msg_id=game["msg_id"],
                winner_id=game["winner_id"],
                loser_id=game["loser_id"]
            )
        )

        game_data.set_index("msg_id", inplace=True)
        self.games.append(game_data)

        for name, ranking in self.rankings.items():
            ranking.register_game(**game)

        await self.update_leaderboards()
        await self.send_game_result(game)

    async def send_game_result(self, change):
        """Create a new message in the KAML matchboard."""
        return  # TODO make sure this works again

        embed = Embed(title=msg_builder.build("game_result_title"),
                      color=0xf36541,
                      timestamp=datetime.utcnow())
        embed.add_field(name=msg_builder.build(
                            "game_result_winner_name",
                            name=change.winner.display_name),
                        value=msg_builder.build(
                            "game_result_winner_description",
                            change=change),
                        inline=True)
        embed.add_field(name=msg_builder.build(
                            "game_result_loser_name",
                            name=change.loser.display_name),
                        value=msg_builder.build(
                            "game_result_loser_description",
                            change=change),
                        inline=True)
        embed.add_field(name=msg_builder.build("game_result_record_title"),
                        value=msg_builder.build(
                            "game_result_record_description",
                            change=change),
                        inline=False)
        embed.add_field(name=msg_builder.build(
                            "game_result_record_history_title",
                            number="X"),
                        value=msg_builder.build("game_result_record_history_"
                                                "description"),
                        inline=True)

        embed.set_footer(text="")
        await self.kamlboard.send(embed=embed)

    async def update_display_names(self):
        """
        Update the string used to identify players for all players.

        Currently fetch the server nickname of every registered players.
        """
        # TODO This should be called everytime an alias is fetched
        registered_players = self.players[self.players["discord_id"].notna()]

        for player_id, discord_id in zip(registered_players.index,
                                         registered_players["discord_id"]):
            user = await self.fetch_user(discord_id)
            self.players.loc[player_id, "display_name"] = user.display_name


kamlbot = Kamlbot(command_prefix="!")


@kamlbot.check
async def check_available(cmd):
    if kamlbot.is_ready:
        return True
    else:
        await cmd.channel.send("Kamlbot not ready, please wait a bit.")
        return False

@kamlbot.command(help="""
Associate in game name to the user's discord profile.
""")
async def alias(cmd, name=None):
    user = cmd.author

    logger.info("{0.mention} claims names {1}".format(user, name))

    if name is not None and kamlbot.identity_manager.is_claimed(name):
        previous_claimant = kamlbot.identity_manager[name]
        await msg_builder.send(
                cmd.channel,
                "taken_alias",
                alias=name,
                identity=previous_claimant)
        return

    try:
        claimant_identity = kamlbot.identity_manager[user.id]
    except PlayerNotFound:
        claimant_identity = None

    if name is None:
        if claimant_identity is not None:
            await msg_builder.send(
                        cmd.channel,
                        "associated_aliases",
                        identity=claimant_identity)

        else:
            await msg_builder.send(
                        cmd.channel,
                        "no_alias_error")

        return

    try:
        alias_identity = kamlbot.identity_manager[name]

        if claimant_identity is None:
            alias_identity.discord_id = user.id
            kamlbot.identity_manager.discord_id_to_identity[user.id] = alias_identity

            await msg_builder.send(
                        cmd.channel,
                        "association_done",
                        new_alias=name)

        else:
            claimant_identity.aliases.add(name)
            alias_identity.aliases = set()
            kamlbot.identity_manager.alias_to_identity[name] = claimant_identity

            await msg_builder.send(
                        cmd.channel,
                        "alias_added_to_profile",
                        user=user,
                        alias=name)

            await msg_builder.send(
                        cmd.channel,
                        "associated_aliases",
                        identity=claimant_identity)

        kamlbot.identity_manager.save_data()

    except PlayerNotFound:
        await msg_builder.send(
            cmd.channel,
            "alias_not_found",
            alias=name)


@kamlbot.command(help="""
Get a lot of info on a player.
""")
async def allinfo(cmd, *nameparts):
    try:
        identity, = await kamlbot.get_identities(nameparts, cmd=cmd, n=1)
    except PlayerNotFound:
        return

    ranking = kamlbot.rankings["main"]
    player = ranking[identity]

    if player.identity.is_claimed:
        msg = msg_builder.build("associated_aliases",
                                identity=player.identity)
    else:
        msg = msg_builder.build("player_not_claimed",
                                player=player)

    await cmd.channel.send(msg)

    if player.rank is not None:
        fig, axes = plt.subplots(2, 2, sharex="col", sharey="row")
        skip = ranking.mingames
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
    else:
        await cmd.channel.send("Not enough game played to produce graphs.")


@kamlbot.command(help="""
Compare two players, including the probability of win estimated by the Kamlbot.
""")
async def compare(cmd, *nameparts):
    try:
        i1, i2 = await kamlbot.get_identities(nameparts, cmd=cmd, n=2)
    except PlayerNotFound:
        return

    ranking = kamlbot.rankings["main"]

    p1 = ranking[i1]
    p2 = ranking[i2]

    msg = msg_builder.build("player_rank",
                            player=p1)

    msg += "\n" + msg_builder.build("player_rank",
                                    player=p2)

    comparison = ranking.comparison(p1, p2)

    if comparison is not None:
        msg += "\n" + msg_builder.build("win_probability",
                                        p1=p1,
                                        p2=p2,
                                        comparison=comparison)
    else:
        msg += "\n" + msg_builder.build(
                            "win_probability_blind",
                            p1=p1,
                            p2=p2,
                            win_estimate=100*ranking.win_estimate(p1, p2))

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
    except PlayerNotFound:
        return

    player = kamlbot.rankings["main"][identity]

    # get current record of the player
    no_of_games = min(player.total_games, 10)
    wins = player.wins
    losses = player.losses

    current_form = ""
    for t in reversed(player.times[-no_of_games:]):  # get the times of the last games played
        # get record of the current time state
        tstate_wins = player.saved_states[t].wins
        tstate_losses = player.saved_states[t].losses
        if tstate_wins < wins:  # player has won the previous game
            current_form += ":crown:"
        elif tstate_losses < losses:  # player has lost the previous game
            current_form += ":meat_on_bone:"
        # update record for the next iteration
        wins = tstate_wins
        losses = tstate_losses

    msg = msg_builder.build("player_rank",
                            player=player)
    msg += "\n" + msg_builder.build("player_form",
                                    no_of_games=no_of_games,
                                    current_form=current_form)

    await cmd.channel.send(msg)


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

    os.execv(sys.executable, ["python", "src/kamlbot.py", "-restart"])


@kamlbot.command(help="""
Search for a player. Optional argument `n` is the maximal number of name returned.
""")
async def search(cmd, name, n=5):
    matches = get_close_matches(name, kamlbot.identity_manager.aliases,
                                n=n)

    msg = "\n".join(matches)
    await cmd.channel.send(f"```\n{msg}\n```")


@kamlbot.command(help="""
[Admin] Stop the bot.
""")
@commands.has_role(ROLENAME)
async def stop(cmd):
    logger.info("Disconnecting Kamlbot")
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
