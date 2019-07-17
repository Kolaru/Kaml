from save_and_load import clean_name
from utils import logger

class AliasTakenError(Exception):
    def __init__(self, taken):
        self.taken = taken
    
    def __str__(self):
        return f"Aliases {self.taken} are already claimed by other players."

class AliasManager:
    _alias_to_id = None
    _id_to_aliases = None
    _claimed_aliases = None
    _claimed_ids = None

    def __init__(self):
        self._alias_to_id = {}
        self._id_to_aliases = {}
        self._claimed_aliases = set()
        self._claimed_ids = []

    def __getitem__(self, alias):
        return self._alias_to_id[alias]

    @property
    def aliases(self):
        return list(self._alias_to_id.keys())
    
    @property
    def claimed_aliases(self):
        return self._claimed_aliases

    def associate_aliases(self, player_id, new_aliases):
        taken = set(new_aliases).intersection(self.claimed_aliases)
        if len(taken) > 0:
            raise AliasTakenError(taken)

        if not self.id_exists(player_id):
            self._id_to_aliases[player_id] = set()
            self._claimed_ids.append(player_id)
        
        found = []
        not_found = []

        for alias in new_aliases:
            if alias in self.aliases:
                found.append(alias)
            else:
                not_found.append(alias)
        
        self._id_to_aliases[player_id].update(new_aliases)
        self._claimed_aliases.update(new_aliases)
            
        for alias in found:
            past_id = self._alias_to_id[alias]
            self._id_to_player[past_id].difference([alias])
        
        for alias in aliases:
            self._alias_to_id[alias] = player_id
        
        for key, aliases in self._id_to_aliases.items():
            if len(aliases) == 0:
                del self._id_to_aliases[key]
            
        self.save_data()

        return found, not_found

    def extract_claims(self, aliases):
        return {alias:self.alias_to_player[alias] for alias in aliases
                if self.is_claimed(alias)}

    def id_exists(self, player_id):
        return player_id in self.id_to_player
    
    def is_claimed(self, alias):
        return alias in self._claimed_aliases

    def load_data(self):
        logger.info("Building PlayerManager.")
        logger.info("PlayerManager - Fetching alias tables.")

        try:
            logger.info("Fetching saved alias table.")
            with open("aliases.csv", "r", encoding="utf-8") as file:
                for line in file:
                    player_id, *aliases = line.split(",")
                    player_id = int(player_id)

                    if isinstance(aliases, str):
                        aliases = [aliases]

                    aliases = [alias.strip() for alias in aliases]
                    self._id_to_aliases[player_id] = set(aliases)
                    self._claimed_ids.append(player_id)
                    self._claimed_aliases.update(aliases)

                    for alias in aliases:
                        self._alias_to_id[alias] = player_id

        except FileNotFoundError:
            logger.warning("No saved alias table found.")

        self.id_to_player = dict()

        logger.info(f"PlayerManager - Constructing {len(self.id_to_aliases)} player objects.")

        for player_id, aliases in self.id_to_aliases.items():
            self.id_to_player[player_id] = Player(player_id=player_id,
                                                  aliases=aliases)

    def save_data(self):
        logger.info("Aliases file overriden.")

        with open("aliases.csv", "w", encoding="utf-8") as file:
            for discord_id, aliases in self._id_to_aliases.items():
                aliases = [clean_name(alias) for alias in aliases]
                file.write('{},{}\n'.format(discord_id, ','.join(aliases)))