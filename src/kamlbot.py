import discord
import git
import io
import os
import time
import sys
import asyncio

from datetime import datetime, timedelta

from difflib import get_close_matches

from discord import Embed, File
from discord.ext import commands, tasks
from discord.ext.commands import Bot

from matplotlib import pyplot as plt

from data_manager import DataManager
from messages import msg_builder
from ranking import ranking_types
from save_and_load import (load_ranking_configs, load_tokens,
                           parse_matchboard_msg, fetch_game_results)
from utils import connect, emit_signal, logger, partition


tokens = load_tokens()
ROLENAME = "Chamelier"


class Kamlbot(Bot):
    """Main bot class."""
    def __init__(self, *args, **kwargs):
        connect("rankings_updated", self.edit_leaderboard)
        connect("game_registered", self.send_game_result)

        self.db = DataManager()

        self.rankings = dict()
        self.is_ready = False
        self.on_ready_ran = False

        super().__init__(*args, **kwargs)

        now = datetime.now()
        nextnoon_date = now + timedelta(days=1)
        nextnoon = nextnoon_date.replace(hour=12, minute=0, second=0,
                                         microsecond=0)
        self.loop.call_at(nextnoon.timestamp(), self.at_noon.start)

    @tasks.loop(hours=24)
    async def at_noon(self):
        today = datetime.today()

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

        if today.day == 1:
            pass  # TODO restart monthly ranking

    async def clean_leaderboards(self):
        channels = set()
        for name, config in self.ranking_configs.items():
            chan = discord.utils.get(self.kaml_server.text_channels,
                                     name=config["leaderboard_chan"])

            channels.add(chan)

        for chan in channels:
            async for msg in chan.history():
                await msg.delete()

    async def edit_leaderboard(self):
        """Edit the leaderboard messages with the current content."""
        for ranking in self.rankings.values():
            for msg in ranking.leaderboard_messages():
                await msg["msg"].edit(content=msg["content"])

    def find_names(self, nameparts, n=1):
        req = self.db.execute(
            """
            SELECT alias
            FROM aliases
            """)
        aliases = [row[0] for row in req]

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

                if name not in aliases:
                    allgood = False
                    break

            if allgood:
                return names

        return None

    async def get_ids(self, nameparts, cmd=None, n=1):
        if isinstance(nameparts, str):
            nameparts = [nameparts]

        if len(nameparts) == 0:
            if cmd is None:
                logger.error("get_ids called without name nor command")
                await msg_builder.send(
                        cmd.channel,
                        "generic_error")

                raise IdentityNotFoundError()

            player_id = self.db.id_from_discord_id(cmd.author.id)

            if player_id is None:
                await msg_builder.send(
                        cmd.channel,
                        "no_alias_error")
                raise IdentityNotFoundError()
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

            raise IdentityNotFoundError()

        req = self.db.executemany(
            """
            SELECT player_id
            FROM aliases
            WHERE alias=name
            """,
            [(name,) for name in names]
            )

        player_ids = list(zip(*req))[0]

        for (pid, name) in zip(player_ids, nameparts):
            if pid is None:
                await msg_builder.send(
                        cmd.channel,
                        "player_not_found_error",
                        player_name=name)

            raise IdentityNotFoundError()

        return player_ids

    async def load_all(self):
        """Load everything from files and fetch missing games from the
        PW matchboard channel.

        Erase the current state of the Kamlbot.
        """
        msg_builder.reload()

        logger.info("Fetching game results.")

        now = datetime.now()
        last_monday_date = now - timedelta(days=now.weekday())
        last_monday = last_monday_date.replace(hour=12, minute=0, second=0,
                                               microsecond=0)

        self.ranking_configs = load_ranking_configs()
        self.ranking_configs["weekly"]["oldest_timestamp_to_consider"] = last_monday.timestamp()

        await self.clean_leaderboards()

        for name, config in self.ranking_configs.items():
            chan = discord.utils.get(self.kaml_server.text_channels,
                                     name=config["leaderboard_chan"])

            for leaderboard_msg in config["leaderboard_msgs"]:
                leaderboard_msg["msg"] = await chan.send(
                    "Temporary message, will be edited with the leaderboard "
                    "once the bot is ready.")

            self.rankings[name] = ranking_types[config["type"]](
                                    name,
                                    self.db,
                                    **config)

        req = self.db.execute(
            """
            SELECT msg_id
            FROM games
            ORDER BY timestamp DESC
            LIMIT 1
            """
            )

        res = req.fetchone()
        if res is None:
            last_msg = None
        else:
            last_msg = await self.matchboard.fetch_message(res[0])

        fetched_games = await fetch_game_results(self.matchboard,
                                                 after=last_msg)
        logger.info(f"{len(fetched_games)} new results fetched from matchboard.")

        data = []
        games = []
        for game in fetched_games:
            if game["winner"] == "" or game["loser"] == "":
                continue

            if game["winner"] is None or game["loser"] is None:
                continue

            winner_id = self.db.id_from_alias(game["winner"])
            loser_id = self.db.id_from_alias(game["loser"])

            data.append((game["msg_id"], game["timestamp"],
                         winner_id, loser_id))

            game["winner_id"] = winner_id
            game["loser_id"] = loser_id

            games.append(game)

        with self.db:
            self.db.executemany(
                """
                INSERT INTO games (msg_id, timestamp, winner_id, loser_id)
                VALUES (:msg_id, :timestamp, :winner_id, :loser_id)
                """,
                games)

        for name, ranking in self.rankings.items():
            logger.info(f"Registering game in ranking {name}")
            ranking.register_many(games)

        await self.update_display_names()
        await self.edit_leaderboard()

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
            logger.info("Too much on_ready")
            return
        else:
            self.on_ready_ran = True

        self.kaml_server = self.get_guild(tokens["kaml_server_id"])

        # Retrieve special channels
        self.debug_chan = discord.utils.get(self.kaml_server.text_channels,
                                            name="debug")

        self.kamlboard = discord.utils.get(self.kaml_server.text_channels,
                                           name="kamlboard")

        for _ in range(100):
            # TODO check that this works
            self.matchboard = self.get_channel(tokens["matchboard_channel_id"])
            await asyncio.sleep(2)
            if self.matchboard is not None:
                break
            logger.info("Retrying connection to PW matchboard")

        await self.change_presence(status=discord.Status.online)

        # Whether the bot should consider itself to have been restarted
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

    async def register_game(self, game):
        if game["winner"] == "" or game["loser"] == "":
            return None

        if game["winner"] is None or game["loser"] is None:
            return None

        game["winner_id"] = self.db.id_from_alias(game["winner"])
        game["loser_id"] = self.db.id_from_alias(game["loser"])

        with self.db:
            self.db.execute(
                """
                INSERT INTO games (msg_id, timestamp, winner_id, loser_id)
                VALUES (?, ?, ?, ?)
                """,
                (game["msg_id"],
                 game["timestamp"],
                 game["winner_id"],
                 game["loser_id"])
                )

        for name, ranking in self.rankings.items():
            ranking.register_game(game)

        await emit_signal("game_registered", game)
        await emit_signal("rankings_updated")

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
                        value=msg_builder.build("game_result_record_history_description"),
                        inline=True)

        embed.set_footer(text="")
        await self.kamlboard.send(embed=embed)

    async def update_display_names(self):
        """Update the string used to identify players for all players.

        Currently fetch the server nickname of every registered players.
        """

        req = self.db.execute(
            """
            SELECT player_id, discord_id
            FROM players
            WHERE discord_id IS NOT NULL
            """
            )

        new_data = []

        for player_id, discord_id in req:
            user = await self.fetch_user(discord_id)
            new_data.append((player_id, user.display_name))

        with self.db:
            self.db.executemany(
                """
                UPDATE players
                SET display_name=?
                WHERE player_id=?
                """,
                new_data
                )


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
    except IdentityNotFoundError:
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

    except IdentityNotFoundError:
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
    except IdentityNotFoundError:
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
    except IdentityNotFoundError:
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
    except IdentityNotFoundError:
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
