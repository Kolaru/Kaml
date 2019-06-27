import csv
import json
import re

from collections import OrderedDict
from os.path import isfile

from utils import emit_signal, locking, logger

## Parsing

WIN_PATTERN = re.compile(r":crown: \*\*(.+)\*\* \(.+\) vs \*\*(.+)\*\* \(.+\)")
LOSS_PATTERN = re.compile(r"\*\*(.+)\*\* \(.+\) vs :crown: \*\*(.+)\*\* \(.+\)")
HALF_WIN_PATTERN = re.compile(r":crown: \*\*(.+)\*\* \(.+\) has won a match!")
HALF_LOSS_PATTERN = re.compile(r"\*\*(.+)\*\* \(.+\) has lost a match.")
MENTION_PATTERN = re.compile(r"<@(.+)>")


def clean_name(s):
    if s is None:
        return None
    return s.strip().replace(",", "_").replace("\n", " ")


"""
    parse_matchboard_msg(msg)

Parse a message on the matchboard, return the result as the tuple `winner, loser` or `None`
if winner and loser can not be determined (e.g. messages with only one name).
"""
def parse_matchboard_msg(msg):
    if len(msg.embeds) == 0:
        return None

    logger.debug(msg.embeds[0].to_dict())
    winner, loser = None, None

    result = msg.embeds[0].description
    m = re.match(WIN_PATTERN, result)
    if m is not None:
        winner, loser = m.group(1, 2)
    else:
        m = re.match(LOSS_PATTERN, result)
        if m is not None:
            winner, loser = m.group(2, 1)
    
    if winner is None:
        m = re.match(HALF_WIN_PATTERN, result)
        if m is not None:
            winner = m.group(1)
    
    if loser is None:
        m = re.match(HALF_LOSS_PATTERN, result)
        if m is not None:
            loser = m.group(1)

    # Strip comma from game names to avoid messing the csv
    winner = clean_name(winner)
    loser = clean_name(loser)
    
    return OrderedDict(timestamp=msg.created_at.timestamp(),
                       id=msg.id,
                       winner=winner,
                       loser=loser)


def parse_mention_to_id(mention):
    m = re.match(MENTION_PATTERN, mention)
    
    if m is None:
        return None
    
    return int(m.group(1))


## File reading/writing

async def fetch_game_results(matchboard, after=None):
    game_results = []
    history = matchboard.history(oldest_first=True,
                                 after=after,
                                 limit=None)
    
    async for msg in history:
        game = parse_matchboard_msg(msg)

        if game is None:
            continue

        game_results.append(game)
    
    return game_results


async def get_game_results(matchboard):
    # First retrieve saved games.
    loaded_results = await load_game_results()

    if len(loaded_results) > 0:
        last_id = int(loaded_results[-1]["id"])
        last_message = await matchboard.fetch_message(last_id)
    else:
        last_message = None

    # Second fetch messages not yet saved from the matchboard.
    # New results are directly saved.
    logger.info("Fetching missing results from matchboard.")

    fetched_game_results = await fetch_game_results(matchboard, after=last_message)

    logger.info(f"{len(fetched_game_results)} new results fetched from matchboard.")

    await save_games(fetched_game_results)

    return loaded_results + fetched_game_results


"""
    game_results_writer(file)

Return a `Writer` for game results for a given file.

Using this ensure consistent formatting of the results.
"""
def game_results_writer(file):
    return csv.DictWriter(file, fieldnames=["timestamp", "id", "winner", "loser"])


@locking("alias.txt")
async def load_alias_tables():
    alias_to_id = dict()
    id_to_aliases = dict()

    try:
        logger.info("Fetching saved alias table.")
        with open("aliases.csv", "r", encoding="utf-8") as file:
            for line in file:
                player_id, *aliases = line.split(",")
                player_id = int(player_id)

                if isinstance(aliases, str):
                    aliases = [aliases]

                aliases = [alias.strip() for alias in aliases]
                id_to_aliases[player_id] = set(aliases)

                for alias in aliases:
                    alias_to_id[alias] = player_id

    except FileNotFoundError:
        logger.warning("No saved alias table found.")
        return dict(), dict()
    
    return alias_to_id, id_to_aliases


@locking("raw_results.csv")
async def load_game_results():
    try:
        logger.info("Retrieving saved games.")
        with open("raw_results.csv", "r", encoding="utf-8", newline="") as file:
            game_results = list(csv.DictReader(file))

            logger.info( f"{len(game_results)} game results retrieved from save.")

    except FileNotFoundError:
        logger.warning("File `raw_results.csv` not found, creating a new one.")

        with open("raw_results.csv", "w", encoding="utf-8", newline="") as file:
            writer = game_results_writer(file)
            writer.writeheader()
            game_results = []
            last_message = None
    
    return game_results


def load_ranking_config(config_name):
    with open("ranking_config.json", "r", encoding="utf-8") as file:
        configs = json.load(file)
    return configs[config_name]


def load_tokens():
    with open("tokens.json", "r", encoding="utf-8") as file:
        d = json.load(file)
    return d


def save_aliases(id_to_aliases):
    logger.info("Aliases file overriden.")

    with open("aliases.csv", "w", encoding="utf-8") as file:
        for discord_id, aliases in id_to_aliases.items():
            aliases = [clean_name(aliase) for aliase in aliases]
            file.write('{},{}\n'.format(discord_id, ','.join(aliases)))


@locking("raw_results.csv")
async def save_games(games):
    with open("raw_results.csv", "a",
              encoding="utf-8", newline="") as file:
        writer = game_results_writer(file)

        for game in games:
            writer.writerow(game)


@locking("raw_results.csv")
async def save_single_game(game):
    with open("raw_results.csv", "a",
              encoding="utf-8", newline="") as file:
        writer = game_results_writer(file)
        writer.writerow(game)
