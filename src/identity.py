from wcwidth import wcswidth, wcwidth

from itertools import chain

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

    def __repr__(self):
        return f"Identity associated to aliases {self.aliases}"

    @property
    def display_aliases(self):
        return "\n".join(self.aliases)

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
    def leaderboard_name(self):
        text = self.display_name
        text_len = wcswidth(self.display_name)

        is_asian = False
        for char in text:  # checks each character to see if anyone of it is Asian-width characters
            is_asian = False
            if wcwidth(char) == 2:
                is_asian = True
                break

        width_size = 20
        if is_asian:  # must be 22 width (width_size + 2)
            if text_len > (width_size + 2):  # add characters until 22
                current_len = 0
                formatted_text = u""
                for char in text:
                    formatted_text += char
                    current_len += wcwidth(char)
                    if current_len == (width_size + 2):
                        break
                    elif current_len == (width_size + 3):
                        formatted_text = formatted_text[:-1] + u" "
                        break
                return formatted_text
            elif text_len < (width_size + 2):  # add ideographic space (　) until 22 or 21
                current_len = text_len
                formatted_text = text
                while current_len != (width_size + 2):
                    formatted_text += u"　"
                    current_len += 2
                    if current_len == (width_size + 3):
                        formatted_text = formatted_text[:-1] + u" "
                        break
                return formatted_text
        elif not is_asian:  # must be 20 width
            if text_len > width_size:
                return text[:width_size]
            elif text_len < width_size:
                return text + u" " * (width_size - text_len)
            else:
                return text

    @property
    def is_claimed(self):
        return self.discord_id is not None


class IdentityManager:
    def __init__(self):
        self.alias_to_identity = {}
        self.discord_id_to_identity = {}
        self.identities = set()

    def __getitem__(self, searchkey):
        try:
            if isinstance(searchkey, int):
                return self.discord_id_to_identity[searchkey]
            elif isinstance(searchkey, str):
                try:
                    return self.alias_to_identity[searchkey]
                except KeyError:
                    return self.discord_name_to_identity[searchkey]
            else:
                raise TypeError(f"Searchkey for IdentityManager should be "
                                f"either int or str not {type(searchkey)}.")
        except KeyError:
            raise IdentityNotFoundError(searchkey)

    def __iter__(self):
        return iter(self.identities)

    @property
    def aliases(self):
        return list(self.alias_to_identity.keys())

    def add_identity(self, discord_id=None, aliases=set()):
        identity = Identity(discord_id, aliases)
        self.identities.add(identity)

        for alias in aliases:
            self.alias_to_identity[alias] = identity

        if discord_id is not None:
            self.discord_id_to_identity[discord_id] = identity

        return identity

    @property
    def claimed_aliases(self):
        return list(chain.from_iterable([identity.aliases for identity
                                         in self.claimed_identities]))

    @property
    def claimed_identities(self):
        return [identity for identity in self.identities if identity.is_claimed]

    @property
    def discord_name_to_identity(self):
        return {iden.display_name: iden for iden in self.claimed_identities}

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


class IdentityNotFoundError(Exception):
    def __init__(self, searchkey=None):
        self.searchkey = searchkey

    def __str__(self):
        if self.searchkey is None:
            return "Tried to find player without giving an identifier."

        return f"No player found with identifier {self.searchkey}."
