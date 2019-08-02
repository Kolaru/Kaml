from save_and_load import clean_name
from utils import logger


class AliasTakenError(Exception):
    def __init__(self, taken):
        self.taken = taken

    def __str__(self):
        return f"Aliases {self.taken} are already claimed by other players."


class Identity:
    """Class used to uniquely identify a player.

    Contain all information concerning the player that are independant
    from any ranking.
    """
    discord_id = None
    aliases = None
    _display_name = None

    def __init__(self, discord_id, aliases):
        self.discord_id = discord_id
        self.aliases = set(aliases)

    @property
    def display_name(self):
        if self._display_name is None:
            if len(self.aliases) > 0:
                return list(self.aliases)[0]
            else:
                return "???"

        else:
            return self._display_name

    @display_name.setter
    def display_name(self, name):
        self._display_name = name

    @property
    def is_claimed(self):
        return self.discord_id is not None


class IdentityManager:
    def __init__(self):
        self.alias_to_identity = {}
        self.claimed_aliases = set()
        self.claimed_ids = []
        self.discord_id_to_identity = {}
        self.identities = set()

    def __getitem__(self, searchkey):
        try:
            if isinstance(searchkey, int):
                return self.discord_id_to_identity[searchkey]
            elif isinstance(searchkey, str):
                return self.alias_to_identity[searchkey]
            else:
                raise TypeError("Searchkey for IdentityManager should be "
                                "either int or str.")
        except KeyError:
            raise IdentityNotFoundError(searchkey)

    @property
    def aliases(self):
        return list(self.alias_to_identity.keys())

    def add_identity(self, discord_id=None, aliases=set()):
        identity = Identity(discord_id, aliases)
        self.identities.append(identity)

        for alias in aliases:
            self.alias_to_identity[alias] = identity

        if discord_id is not None:
            self.claimed_aliases.update(aliases)
            self.claimed_ids.append(identity)
            self.discord_id_to_identity[discord_id] = identity

        return identity

    def associate_aliases(self, discord_id, new_aliases):
        taken = set(new_aliases).intersection(self.claimed_aliases)
        if len(taken) > 0:
            raise AliasTakenError(taken)

        found = []
        not_found = []

        for alias in new_aliases:
            if alias in self.aliases:
                found.append(alias)
            else:
                not_found.append(alias)

        identity = self.to_identity(discord_id)
        identity.update(new_aliases)
        self.claimed_aliases.update(new_aliases)
        to_delete = []

        for alias in found:
            past_id = self.alias_to_identity[alias]
            to_delete.append(past_id)

        for alias in new_aliases:
            self.alias_to_identity[alias] = identity

        self.identities -= set(to_delete)
        self.save_data()

        return found, not_found

    def is_claimed(self, alias):
        return alias in self.claimed_aliases

    def load_data(self):
        logger.info("Building PlayerManager.")
        logger.info("PlayerManager - Fetching alias tables.")

        try:
            logger.info("Fetching saved alias table.")
            with open("data/aliases.csv", "r", encoding="utf-8") as file:
                for line in file:
                    discord_id, *aliases = line.split(",")
                    discord_id = int(discord_id)

                    if isinstance(aliases, str):
                        aliases = [aliases]

                    aliases = [alias.strip() for alias in aliases]
                    self.add_identity(discord_id=discord_id, aliases=aliases)

        except FileNotFoundError:
            logger.warning("No saved alias table found.")

    def save_data(self):
        logger.info("Aliases file overriden.")

        with open("data/aliases.csv", "w", encoding="utf-8") as file:
            for discord_id, identity in self.discord_id_to_identity.items():
                aliases = [clean_name(alias) for alias in identity.aliases]
                file.write('{},{}\n'.format(discord_id, ','.join(aliases)))

    def to_identity(self, discord_id):
        if discord_id not in self.discord_id_to_identity:
            self.add_identity(discord_id=discord_id)

        return self.discord_id_to_identity[discord_id]


class IdentityNotFoundError(Exception):
    def __init__(self, searchkey=None):
        self.searchkey = searchkey

    def __str__(self):
        if self.searchkey is None:
            return "Tried to find player without giving an identifier."

        return f"No player found with identifier {self.searchkey}."
