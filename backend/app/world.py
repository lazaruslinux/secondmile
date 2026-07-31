"""The collection: four sets of cards, and the weights a chest is drawn against.

All of it is static Python rather than database rows. The catalogue is authored,
not user data, so a release changes it and a migration never has to; the
database keeps only what each player has found.

Ids are the stable part. Names and flavour can be rewritten in place, but an id
appears in chests and user_cards, so changing one orphans whatever a player
already earned. The id convention is <set_id>_<slug>.
"""

from dataclasses import dataclass

RARITIES = ("common", "uncommon", "rare")


@dataclass(frozen=True)
class CardSet:
    id: str
    name: str
    # How often a chest is drawn from this set. Relative, not a percentage:
    # the roll is over every set at once. The scarce sets are scarce because
    # of this number and nothing else, so retuning the feel of the collection
    # is a one-line change rather than a rework.
    weight: float


@dataclass(frozen=True)
class Card:
    id: str
    set_id: str
    number: int
    name: str
    rarity: str
    flavor: str


CARD_SETS: dict[str, CardSet] = {
    card_set.id: card_set
    for card_set in (
        CardSet("hedgerow", "The Hedgerow", 8.0),
        CardSet("still_water", "Still Water", 5.0),
        CardSet("open_hill", "The Open Hill", 3.0),
        CardSet("first_light", "First Light", 2.0),
    )
}


# The field guide. Numbers are the plate numbers a collector sees, so they run
# from one within each set and never move. Unowned plates show the number and
# the rarity and nothing else, which is why the ids are prefixed with the set
# rather than being guessable from the number.
_CARD_LINES: tuple[tuple[str, str, str, str], ...] = (
    # The Hedgerow: what grows and lives in the strip of everything nobody
    # planted. Twelve plates, and the set most chests come from.
    ("hedgerow_hawthorn", "hedgerow", "Hawthorn", "common"),
    ("hedgerow_speedwell", "hedgerow", "Speedwell", "common"),
    ("hedgerow_dog_rose", "hedgerow", "Dog Rose", "common"),
    ("hedgerow_bramble", "hedgerow", "Bramble", "common"),
    ("hedgerow_sloes", "hedgerow", "Blackthorn Sloes", "common"),
    ("hedgerow_red_campion", "hedgerow", "Red Campion", "common"),
    ("hedgerow_elder", "hedgerow", "Elder in Flower", "common"),
    ("hedgerow_wren", "hedgerow", "Wren", "uncommon"),
    ("hedgerow_yellowhammer", "hedgerow", "Yellowhammer", "uncommon"),
    ("hedgerow_hedgehog", "hedgerow", "Hedgehog", "uncommon"),
    ("hedgerow_dormouse", "hedgerow", "Hazel Dormouse", "rare"),
    ("hedgerow_barn_owl", "hedgerow", "Barn Owl", "rare"),
    # Still Water: ponds, slow rivers, and the margins nothing hurries in.
    # Ten plates.
    ("still_water_reedbed", "still_water", "Reedbed", "common"),
    ("still_water_water_mint", "still_water", "Water Mint", "common"),
    ("still_water_crowfoot", "still_water", "Water Crowfoot", "common"),
    ("still_water_moorhen", "still_water", "Moorhen", "common"),
    ("still_water_alder", "still_water", "Alder Roots", "common"),
    ("still_water_dragonfly", "still_water", "Emperor Dragonfly", "uncommon"),
    ("still_water_heron", "still_water", "Grey Heron", "uncommon"),
    ("still_water_willow", "still_water", "Leaning Willow", "uncommon"),
    ("still_water_kingfisher", "still_water", "Kingfisher", "rare"),
    ("still_water_otter", "still_water", "Otter", "rare"),
    # The Open Hill: above the last wall, where the weather arrives first.
    # Eight plates.
    ("open_hill_heather", "open_hill", "Heather", "common"),
    ("open_hill_bilberry", "open_hill", "Bilberry", "common"),
    ("open_hill_cotton_grass", "open_hill", "Cotton Grass", "common"),
    ("open_hill_skylark", "open_hill", "Skylark", "uncommon"),
    ("open_hill_curlew", "open_hill", "Curlew", "uncommon"),
    ("open_hill_rowan", "open_hill", "Rowan", "uncommon"),
    ("open_hill_mountain_hare", "open_hill", "Mountain Hare", "rare"),
    ("open_hill_raven", "open_hill", "Raven Pair", "rare"),
    # First Light: the hour before the day belongs to anybody. Six plates, and
    # the set that turns up least.
    ("first_light_dew", "first_light", "Dew on the Grass", "common"),
    ("first_light_blackbird", "first_light", "Blackbird", "common"),
    ("first_light_mist", "first_light", "Mist in the Hollow", "uncommon"),
    ("first_light_roe_deer", "first_light", "Roe Deer", "uncommon"),
    ("first_light_hare", "first_light", "Brown Hares Boxing", "rare"),
    ("first_light_frost", "first_light", "First Frost", "rare"),
)

_FLAVOR: dict[str, str] = {
    "hedgerow_hawthorn": "White in May, red in October, thorned all year in between.",
    "hedgerow_speedwell": (
        "Blue as a scrap of sky, and gone by the time you turn back to look at it."
    ),
    "hedgerow_dog_rose": "Grows where it likes, which is anywhere the hedge lets it through.",
    "hedgerow_bramble": "Takes the worst ground it can find and fruits there anyway.",
    "hedgerow_sloes": "Bitter until the first frost, which is a kind of patience.",
    "hedgerow_red_campion": "Waist high by June along every verge nobody got round to cutting.",
    "hedgerow_elder": "Flat white plates of flower in June, and the whole lane smells of it.",
    "hedgerow_wren": "The smallest voice in the hedge and by some way the loudest.",
    "hedgerow_yellowhammer": "Sings the same seven notes all afternoon and never gets bored of it.",
    "hedgerow_hedgehog": "Covers more ground in one night than most people do in a week.",
    "hedgerow_dormouse": "Asleep for half the year, and still gets where it is going.",
    "hedgerow_barn_owl": (
        "Hunts the verge without a sound, and is only ever seen by whoever is still out walking."
    ),
    "still_water_reedbed": "A whole county's worth of birds hidden in something you can see through.",
    "still_water_water_mint": "Crushed underfoot at the edge, and the smell follows you home.",
    "still_water_crowfoot": "White flowers on the surface, and everything else happening beneath it.",
    "still_water_moorhen": "Not built for swimming and swims anyway, all afternoon, without complaint.",
    "still_water_alder": "Holds the bank together with roots nobody was ever meant to see.",
    "still_water_dragonfly": "Two years underwater for one summer in the air, and worth it.",
    "still_water_heron": "Stands so long in the shallows that the water forgets about it.",
    "still_water_willow": "Leaning further over every year and still not in the water.",
    "still_water_kingfisher": "You mostly see where it was. That counts.",
    "still_water_otter": "Leaves five toes in the mud and is a mile downstream before you find them.",
    "open_hill_heather": "Grey eleven months of the year, and then the whole hill goes purple.",
    "open_hill_bilberry": "Ankle high, easy to miss, and worth kneeling down for in July.",
    "open_hill_cotton_grass": (
        "White heads over black peat, marking ground that will take your boot if you let it."
    ),
    "open_hill_skylark": "Sings on the way up, which is harder than singing standing still.",
    "open_hill_curlew": "You hear it long before you see it, and usually you never see it.",
    "open_hill_rowan": "Grows out of bare rock where nothing sensible would try.",
    "open_hill_mountain_hare": "Turns white for a winter that does not always come any more.",
    "open_hill_raven": (
        "They travel in pairs, and they roll over in the air for no reason anyone can prove."
    ),
    "first_light_dew": "Every blade holds one, and the whole field is lit for about ten minutes.",
    "first_light_blackbird": "First voice up, most mornings, and in no hurry about it.",
    "first_light_mist": "Lying in the low ground like something poured there overnight.",
    "first_light_roe_deer": "Out in the open at six and back in the wood by seven.",
    "first_light_hare": "March, in a bare field, and neither of them will back down.",
    "first_light_frost": (
        "One morning the grass crunches, and everything from here is a different season."
    ),
}


def _build_cards() -> tuple[dict[str, Card], dict[str, tuple[Card, ...]]]:
    by_id: dict[str, Card] = {}
    by_set: dict[str, list[Card]] = {set_id: [] for set_id in CARD_SETS}
    for card_id, set_id, name, rarity in _CARD_LINES:
        card = Card(
            id=card_id,
            set_id=set_id,
            number=len(by_set[set_id]) + 1,
            name=name,
            rarity=rarity,
            flavor=_FLAVOR[card_id],
        )
        by_id[card_id] = card
        by_set[set_id].append(card)
    return by_id, {set_id: tuple(cards) for set_id, cards in by_set.items()}


CARDS, CARDS_BY_SET = _build_cards()
