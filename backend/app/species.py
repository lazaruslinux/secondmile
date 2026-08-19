"""What a seed grows into: twelve species, and the one nothing explains.

Static Python rather than database rows, for the same reason the catalogue it
replaces was: this is authored content, so a release changes it and a migration
never has to. The database keeps only what each player is holding and growing.

Ids are the stable part. They appear in satchel_items and plantings, and the
art files are named after them, so renaming one orphans whatever is planted.

Four of each rarity, twelve in all. The numbers are the shape of the thing and
are never explained anywhere.

Everything planted levels, and the miles are the only thing that levels it. One
level costs what that species used to cost to come of age: a common bush fifteen
Miles, an uncommon forty, a rare a hundred. Level one is maturity. Level
thirty three is as far as anything goes, and there it is gilded and finished.

The mustard tree is the exception in every way but one. It comes out of the
first chest an account ever opens and nowhere else, and the reveal states two
mechanical facts, that gift and the twelve left to find, and nothing more: why
it is the one seed like that stays unsaid.
"""

from dataclasses import dataclass

RARITIES = ("common", "uncommon", "rare")

# The whole rarity ladder, in order, low to high. The first three are the
# rarities a seed can be; the two above them belong to items only, because there
# is nothing rarer to grow than a rare and the ladder still has to climb past it.
RARITY_LADDER = (*RARITIES, "epic", "legendary")

# What a wish is called wherever it is shown. Not a species; no catalogue row.
WISH_NAME = "Unmarked seed"

# Converted Miles one level costs, by rarity. What each species once needed to
# come to maturity it now needs for every level it puts on.
LEVEL_MI: dict[str, float] = {"common": 15.0, "uncommon": 40.0, "rare": 100.0}

# The level a plant is grown at, and the last level there is. Both numbers are
# structural and neither is explained anywhere in the app.
MATURE_LEVEL = 1
MAX_LEVEL = 33

# The one line the game explains about itself, said at the reveal and nowhere
# else. What it means is still never said.
MUSTARD_REVEAL = "Everyone's first chest holds a mustard seed. There are 12 more seeds to find."


@dataclass(frozen=True)
class Species:
    id: str
    # What the seed is called, in the satchel and at the reveal, and what the
    # grown thing is called, in the plot and on the band. Two names because they
    # are two things: you are given an olive seed and you plant an olive tree.
    seed_name: str
    plant_name: str
    # Which slot of a chest roll drops this seed. The mustard tree is a rare
    # for this purpose so that nothing about it reads as unusual; it is never
    # actually rolled.
    rarity: str
    # Converted Miles one level of this species costs. Always its rarity's step.
    level_mi: float
    # What it bears once it is grown, in both numbers. Fruit is the word for
    # the category everywhere in the game; these are what this one species calls
    # its own harvest. Two forms because a rare tree bears exactly one of them
    # and "1 olives" is not a thing anybody wrote.
    produce: str
    produce_one: str
    # Said once, when the seed comes out of the chest. Empty for every species
    # that has nothing about it to explain, which is all but one.
    reveal: str = ""


_CATALOG: tuple[Species, ...] = (
    # Common: small plants and quick growers, modest fruit.
    Species("strawberry", "Strawberry seed", "Strawberry bush", "common", 15.0, "strawberries", "strawberry"),
    Species("banana", "Banana seed", "Banana tree", "common", 15.0, "bananas", "banana"),
    Species("raspberry", "Raspberry seed", "Raspberry bush", "common", 15.0, "raspberries", "raspberry"),
    Species("blueberry", "Blueberry seed", "Blueberry bush", "common", 15.0, "blueberries", "blueberry"),
    # Uncommon: bushes and vines.
    Species("blackberry", "Blackberry seed", "Blackberry bush", "uncommon", 40.0, "blackberries", "blackberry"),
    Species("mango", "Mango seed", "Mango tree", "uncommon", 40.0, "mangoes", "mango"),
    Species("grapevine", "Grape seed", "Grapevine", "uncommon", 40.0, "grapes", "grape"),
    Species("fig_bush", "Fig seed", "Fig bush", "uncommon", 40.0, "figs", "fig"),
    # Rare: trees, slow, and the best of it.
    Species("olive", "Olive seed", "Olive tree", "rare", 100.0, "olives", "olive"),
    Species("dates", "Date seed", "Date palm", "rare", 100.0, "dates", "date"),
    Species("coffee", "Coffee seed", "Coffee plant", "rare", 100.0, "coffee cherries", "coffee cherry"),
    Species("pomegranate", "Pomegranate seed", "Pomegranate tree", "rare", 100.0, "pomegranates", "pomegranate"),
    # The first chest, and only the first chest. It levels like everything else
    # and the only thing said about it is that there is one of it.
    Species(
        "mustard",
        "Mustard seed",
        "Mustard",
        "rare",
        100.0,
        "mustard seeds",
        "mustard seed",
        MUSTARD_REVEAL,
    ),
)

BY_ID: dict[str, Species] = {row.id: row for row in _CATALOG}

# The first chest an account opens carries this instead of whatever it rolled.
FIRST_CHEST_SPECIES = "mustard"

# What each rarity slot may actually drop. The mustard tree is left out: it is
# given, never rolled.
BY_RARITY: dict[str, tuple[Species, ...]] = {
    rarity: tuple(
        row for row in _CATALOG if row.rarity == rarity and row.id != FIRST_CHEST_SPECIES
    )
    for rarity in RARITIES
}

# Everything a chest or a wish may hand over: the twelve, and never the mustard
# tree, which is given once and is in no bag anything reaches into.
ROLLABLE: tuple[str, ...] = tuple(
    row.id for rarity in RARITIES for row in BY_RARITY[rarity]
)


def missing(held: frozenset[str] | set[str]) -> list[str]:
    """Which of the twelve an account has neither growing nor waiting.

    In catalogue order, so the same plot always answers the same way.
    """
    return [species_id for species_id in ROLLABLE if species_id not in held]
