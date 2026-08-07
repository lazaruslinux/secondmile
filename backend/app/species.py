"""What a seed grows into: twelve species, and the one nothing explains.

Static Python rather than database rows, for the same reason the catalogue it
replaces was: this is authored content, so a release changes it and a migration
never has to. The database keeps only what each player is holding and growing.

Ids are the stable part. They appear in satchel_items and plantings, and the
art files are named after them, so renaming one orphans whatever is planted.

Four of each rarity, twelve in all. The numbers are the shape of the thing and
are never explained anywhere.

The mustard tree is the exception in every way but one. It comes out of the
first chest an account ever opens and nowhere else, it never matures at all but
levels instead, and the reveal explains that single mechanical fact and nothing
more: why it is the one seed like that stays unsaid.
"""

from dataclasses import dataclass

RARITIES = ("common", "uncommon", "rare")

# Converted Miles one level of a levelling species costs.
MUSTARD_LEVEL_MI = 100.0

# The one line the game explains about itself, said at the reveal and nowhere
# else. What it means is still never said.
MUSTARD_REVEAL = "You will only ever receive one."


@dataclass(frozen=True)
class Species:
    id: str
    name: str
    # Which slot of a chest roll drops this seed. The mustard tree is a rare
    # for this purpose so that nothing about it reads as unusual; it is never
    # actually rolled.
    rarity: str
    # Converted Miles of growth this species needs to come to maturity. Zero
    # means it never matures, which is the mustard tree and only it.
    maturity_mi: float
    # What it bears once it is grown. Fruit is the word for the category
    # everywhere in the game; this is what this one species calls its own
    # harvest. Nothing bears anything this round, so nothing reads it yet.
    produce: str
    # Converted Miles per level for a species that levels instead of maturing.
    # Zero for everything that simply grows up and stops.
    level_mi: float = 0.0
    # Said once, when the seed comes out of the chest. Empty for every species
    # that has nothing about it to explain, which is all but one.
    reveal: str = ""


_CATALOG: tuple[Species, ...] = (
    # Common: small plants and quick growers, modest fruit.
    Species("strawberry", "Strawberry bush", "common", 15.0, "strawberries"),
    Species("banana", "Banana tree", "common", 15.0, "bananas"),
    Species("raspberry", "Raspberry bush", "common", 15.0, "raspberries"),
    Species("blueberry", "Blueberry bush", "common", 15.0, "blueberries"),
    # Uncommon: bushes and vines.
    Species("blackberry", "Blackberry bush", "uncommon", 40.0, "blackberries"),
    Species("mango", "Mango tree", "uncommon", 40.0, "mangoes"),
    Species("grapevine", "Grapevine", "uncommon", 40.0, "grapes"),
    Species("fig_bush", "Fig bush", "uncommon", 40.0, "figs"),
    # Rare: trees, slow, and the best of it.
    Species("olive", "Olives", "rare", 100.0, "olives"),
    Species("dates", "Dates", "rare", 100.0, "dates"),
    Species("coffee", "Coffee", "rare", 100.0, "coffee cherries"),
    Species("pomegranate", "Pomegranate", "rare", 100.0, "pomegranates"),
    # The first chest, and only the first chest. It has no maturity: it levels,
    # a hundred Miles at a time, for as long as the miles keep coming.
    Species(
        "mustard",
        "Mustard",
        "rare",
        0.0,
        "mustard seed",
        level_mi=MUSTARD_LEVEL_MI,
        reveal=MUSTARD_REVEAL,
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
