import discord
import git
import io
import os
from tqdm import tqdm
import time
import sys
import asyncio

from datetime import datetime, timedelta

from difflib import get_close_matches

from discord import Embed, File
from discord.ext import commands, tasks
from discord.ext.commands import Bot

from matplotlib import pyplot as plt

from identity import IdentityManager, IdentityNotFoundError
from messages import msg_builder
from ranking import ranking_types
from save_and_load import (load_ranking_configs, load_tokens,
                           parse_matchboard_msg, get_game_results,
                           save_single_game, get_current_form)
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
        nextnoon_date = now + timedelta(days=1)
        nextnoon = nextnoon_date.replace(hour=12, minute=0, second=0, microsecond=0)
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
                        "Temporary message, will be edited with the leaderboard "
                        "once the bot is ready.")

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

    async def debug(self, msg):
        """Log the given `msg` to the default logger with debug level and
        also send the message to the debug discord chan.
        """
        await self.debug_chan.send(msg)
        logger.debug(msg)

    async def edit_leaderboard(self):
        """Edit the leaderboard messages with the current content."""
        for ranking in self.rankings.values():
            for msg in ranking.leaderboard_messages():
                await msg["msg"].edit(content=msg["content"])

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
                logger.error("get_identities called without name nor command")
                await msg_builder.send(
                        cmd.channel,
                        "generic_error")

                raise IdentityNotFoundError()

            try:
                identity = self.identity_manager[cmd.author.id]
                return (identity,)
            except IdentityNotFoundError:
                await msg_builder.send(
                        cmd.channel,
                        "no_alias_error")

                raise

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

        logger.info("Fetching game results.")

        now = datetime.now()
        last_monday_date = now - timedelta(days=now.weekday())
        last_monday = last_monday_date.replace(hour=12, minute=0, second=0, microsecond=0)

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
                                    self.identity_manager,
                                    **config)

        game_results = await get_game_results(self.matchboard)
        for game in tqdm(game_results):
            await self.register_game(game, save=False, signal_update=False)

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
        # If the manager is set, it means this has already run at least once.
        if self.identity_manager is not None:
            print("Too much on_ready")
            return

        self.kaml_server = self.get_guild(tokens["kaml_server_id"])

        # Retrieve special channels
        self.debug_chan = discord.utils.get(self.kaml_server.text_channels,
                                            name="debug")

        self.kamlboard = discord.utils.get(self.kaml_server.text_channels,
                                           name="kamlboard")

        for _ in range(100):
            self.matchboard = self.get_guild(tokens["pw_server_id"]).get_channel(377280549192073216)
            await asyncio.sleep(2)
            if self.matchboard is not None:
                break
            print("Retrying connection to PW matchboard")

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

        if game["winner"] is None or game["loser"] is None:
            return None

        if save:
            save_single_game(game)

        for name, ranking in self.rankings.items():
            change = ranking.register_game(game)

            if signal_update and name == "main":
                await emit_signal("game_registered", change)

        if signal_update:
            await emit_signal("rankings_updated")

    async def send_game_result(self, change):
        """Create a new message in the KAML matchboard."""

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
                            number=change.h2h_history_len),
                        value=msg_builder.build("game_result_record_history_description",
                                                history=change.h2h_history),
                        inline=True)

        embed.set_footer(text="")
        await self.kamlboard.send(embed=embed)

    async def update_display_names(self):
        """Update the string used to identify players for all players.

        Currently fetch the server nickname of every registered players.
        """

        for identity in self.identity_manager.claimed_identities:
            user = await self.fetch_user(identity.discord_id)
            identity.display_name = user.display_name


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

    # Obtaining Rivals info
    rivals_dict = {key: (player.games_against[key], player.win_percents[key]) for key in player.win_percents}
    rivals_dict = {k: (v[0], v[1]) for k, v in rivals_dict.items() if v[0] > 8}  # only include 9 or more games played against
    rivals_dict = {k: (v[0], v[1]) for k, v in rivals_dict.items() if 0.4 < v[1] < 0.6}  # only include within 40-60% win rate

    # Building Rivals message
    if not rivals_dict:
        rivals_msg = "None yet, play more!"
    elif rivals_dict:
        # Sorts by games played, then by closest to 50% win rate
        sorted_rivals_list = sorted(rivals_dict.items(), key=lambda a: (-a[1][0], abs(0.5-a[1][1])))

        sorted_rivals_list = sorted_rivals_list[:5]
        rivals_msg = ""
        for opponent in sorted_rivals_list:
            opponent = opponent[0]
            opp_name = opponent.display_name
            h2h_record = str(ranking.wins[(player, opponent)]) + " – " + str(ranking.wins[(opponent, player)])
            rivals_msg += "**" + opp_name + "**\t" + h2h_record + " (" + '{:.2f}'.format(rivals_dict[opponent][1]*100) + "%)\n"

    # Obtain and Build Peak message
    compare_rank = 0
    peak_rank = len(ranking.rank_to_player)
    for timestamp, drank in list(player.delta_ranks.items()):
        compare_rank += drank
        if compare_rank < peak_rank:
            peak_rank = compare_rank
            peak_rank_time = time.strftime("%d %b %Y", time.gmtime(timestamp))
    peak_rank = str(peak_rank)

    peak_score = max(player.scores)
    for timestamp, tsstate in list(player.states.items()):
        if tsstate.score == peak_score:
            peak_score_timestamp = timestamp
            peak_score_sigma = tsstate.sigma
            break
    peak_score_time = time.strftime("%d %b %Y", time.gmtime(peak_score_timestamp))
    
    peak_msg = ":military_medal: **{}** (on {})\n:camel: **{:.2f} (±{:.2f})** (on {})".format(peak_rank,
                                                                                         peak_rank_time,
                                                                                         peak_score,
                                                                                         peak_score_sigma,
                                                                                         peak_score_time)

    # Obtain and Build Cool Stats message
    first_game_date = time.strftime("%d %b %Y", time.gmtime(list(player.saved_states.items())[0][0]))
    last_game_date = time.strftime("%d %b %Y", time.gmtime(list(player.saved_states.items())[-1][0]))
    coolstats_msg = "First Game: **" + first_game_date + "**\n"
    coolstats_msg += "Last Game: **" + last_game_date + "**\n"
    coolstats_msg += "Longest Win Streak: **" + str(player.longest_win_streak) + "**\n"
    coolstats_msg += "Longest Lose Streak: **" + str(player.longest_lose_streak) + "**"

    embed = Embed(title=player.display_name, color=0xf36541)
    embed.add_field(name="Statistics",
                    value=msg_builder.build(
                          "allinfo_statistics",
                          player=player),
                    inline=True)
    embed.add_field(name="Peak",
                    value=peak_msg,
                    inline=True)
    embed.add_field(name="Rivals",
                    value=rivals_msg,
                    inline=True)
    embed.add_field(name="Cool Stats",
                    value=coolstats_msg,
                    inline=True)
    
    await cmd.channel.send(embed=embed)

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

    current_form, no_of_games = get_current_form(player, 15)

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
