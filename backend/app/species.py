"""What a seed grows into: nine species, and the one nothing explains.

Static Python rather than database rows, for the same reason the catalogue it
replaces was: this is authored content, so a release changes it and a migration
never has to. The database keeps only what each player is holding and growing.

Ids are the stable part. They appear in satchel_items and plantings, and the
art files are named after them, so renaming one orphans whatever is planted.
Names are placeholders awaiting a naming pass.

The mustard tree is the exception in every way but its data. It comes out of
the first chest an account ever opens and nowhere else, it takes the longest of
anything to grow, and it carries no marker of its own: nothing in the API and
nothing in the catalogue says it is special, because the game never explains it.
"""

from dataclasses import dataclass

RARITIES = ("common", "uncommon", "rare")


@dataclass(frozen=True)
class Species:
    id: str
    name: str
    # Which slot of a chest roll drops this seed. The mustard tree is a rare
    # for this purpose so that nothing about it reads as unusual; it is never
    # actually rolled.
    rarity: str
    # Converted Miles of growth this species needs to come to maturity. On the
    # species rather than on the rarity, because the mustard tree costs half as
    # much again as the rare trees it stands among.
    maturity_mi: float
    # What it bears once it is grown. Fruit is the word for the category
    # everywhere in the game; this is what this one species calls its own
    # harvest. Nothing bears anything this round, so nothing reads it yet.
    produce: str


_CATALOG: tuple[Species, ...] = (
    # Common: small plants, quick to grow, modest fruit.
    Species("strawberry", "Strawberry", "common", 15.0, "strawberries"),
    Species("tomato", "Tomato", "common", 15.0, "tomatoes"),
    Species("mint", "Mint", "common", 15.0, "mint leaves"),
    # Uncommon: bushes, vines, and shrubs.
    Species("grapevine", "Grapevine", "uncommon", 40.0, "grapes"),
    Species("blackberry", "Blackberry", "uncommon", 40.0, "blackberries"),
    Species("fig_bush", "Fig Bush", "uncommon", 40.0, "figs"),
    Species("coffee", "Coffee", "uncommon", 40.0, "coffee cherries"),
    # Rare: trees, slow, and the best of it.
    Species("olive", "Olive", "rare", 100.0, "olives"),
    Species("pomegranate", "Pomegranate", "rare", 100.0, "pomegranates"),
    Species("apple", "Apple", "rare", 100.0, "apples"),
    Species("banana", "Banana", "rare", 100.0, "bananas"),
    Species("mango", "Mango", "rare", 100.0, "mangoes"),
    # The first chest, and only the first chest.
    Species("mustard", "Mustard", "rare", 150.0, "mustard seed"),
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
