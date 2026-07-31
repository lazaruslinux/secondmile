"""The Vale: its places, its roads, its milestones, and its cards.

All of it is static Python rather than database rows. The world is authored,
not user data, so a release changes it and a migration never has to; the
database keeps only where each player has got to and what they have found.
Ids are the stable part. Names and flavour can be rewritten in place, but an
id appears in chests, user_cards, and user_accolades, so changing one orphans
whatever a player already earned.
"""

from collections import deque
from dataclasses import dataclass

# Where a new account's marker stands, and the destination it is given so the
# first sync already moves it. A journey with no destination only ever walks
# local rounds, which is a poor first impression of a game about travelling.
START_LOCATION = "homestead"
START_DESTINATION = "millbrook"

RARITIES = ("common", "uncommon", "rare")


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    # Which card set a chest dropped here comes from. Homestead and Fells Gate
    # borrow the set of the road they sit at the end of; they are gateposts
    # rather than places with a character of their own yet.
    card_set: str


@dataclass(frozen=True)
class Milestone:
    """A fixed mark on a road that grants a permanent accolade the first time a
    marker passes it. The id is the accolade id."""

    id: str
    name: str
    detail: str
    mile: float


@dataclass(frozen=True)
class Road:
    id: str
    name: str
    from_id: str
    to_id: str
    length_mi: float
    card_set: str
    milestones: tuple[Milestone, ...] = ()
    # A road inside a region cannot be walked until that region is unlocked.
    # None means open to everyone from the first day.
    region: str | None = None


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    cost_run_miles: float
    detail: str


@dataclass(frozen=True)
class CardSet:
    id: str
    name: str


@dataclass(frozen=True)
class Card:
    id: str
    set_id: str
    number: int
    name: str
    rarity: str
    flavor: str


LOCATIONS: dict[str, Location] = {
    location.id: location
    for location in (
        Location("homestead", "Homestead", "east_road"),
        Location("millbrook", "Millbrook", "millbrook"),
        Location("fells_gate", "Fells Gate", "north_road"),
        Location("shieling", "The Shieling", "high_fells"),
    )
}


ROADS: dict[str, Road] = {
    road.id: road
    for road in (
        Road(
            id="east_road",
            name="East Road",
            from_id="homestead",
            to_id="millbrook",
            length_mi=10.0,
            card_set="east_road",
            milestones=(
                Milestone(
                    "east_road_footbridge",
                    "The Footbridge",
                    "Three planks over the brook, three miles out from home.",
                    3.0,
                ),
                Milestone(
                    "east_road_old_mill",
                    "The Old Mill",
                    "Six miles out, where the wheel still turns when the water is up.",
                    6.0,
                ),
            ),
        ),
        Road(
            id="north_road",
            name="North Road",
            from_id="millbrook",
            to_id="fells_gate",
            length_mi=15.0,
            card_set="north_road",
            milestones=(
                Milestone(
                    "north_road_waymarker",
                    "The Waymarker Stone",
                    "Four miles north of town, cut with a hand pointing the way.",
                    4.0,
                ),
                Milestone(
                    "north_road_viewpoint",
                    "The Viewpoint",
                    "Nine miles north, where the whole valley lies out below you.",
                    9.0,
                ),
            ),
        ),
        Road(
            id="fell_road",
            name="Fell Road",
            from_id="fells_gate",
            to_id="shieling",
            length_mi=6.0,
            card_set="high_fells",
            region="high_fells",
        ),
    )
}


REGIONS: dict[str, Region] = {
    region.id: region
    for region in (
        Region(
            id="high_fells",
            name="The High Fells",
            cost_run_miles=26.2,
            detail="The gate above Fells Gate. It opens to a marathon of run Miles.",
        ),
    )
}


CARD_SETS: dict[str, CardSet] = {
    card_set.id: card_set
    for card_set in (
        CardSet("east_road", "East Road"),
        CardSet("millbrook", "Millbrook"),
        CardSet("north_road", "North Road"),
        CardSet("high_fells", "High Fells"),
    )
}


# The field guide. Numbers are the plate numbers a collector sees, so they run
# from one within each set and never move. Unowned plates show the number and
# the rarity and nothing else, which is why the names carry no hints and the
# ids are prefixed with the set rather than being guessable from the number.
_CARD_LINES: tuple[tuple[str, str, str, str], ...] = (
    # East Road: the lane between the Homestead and town, its hedges and its
    # brook. Twelve plates.
    ("east_road_hawthorn", "east_road", "Hedgerow Hawthorn", "common"),
    ("east_road_speedwell", "east_road", "Roadside Speedwell", "common"),
    ("east_road_cart_ruts", "east_road", "Cart Ruts", "common"),
    ("east_road_field_gate", "east_road", "The Field Gate", "common"),
    ("east_road_skylark", "east_road", "Skylark", "uncommon"),
    ("east_road_footbridge", "east_road", "The Footbridge", "uncommon"),
    ("east_road_heron", "east_road", "Heron Below the Footbridge", "rare"),
    ("east_road_sloes", "east_road", "Blackthorn Sloes", "common"),
    ("east_road_dog_rose", "east_road", "Dog Rose", "common"),
    ("east_road_footpath_sign", "east_road", "The Footpath Sign", "common"),
    ("east_road_mill_wheel", "east_road", "The Old Mill Wheel", "uncommon"),
    ("east_road_barn_owl", "east_road", "Barn Owl at Dusk", "rare"),
    # Millbrook: the town at the far end of the East Road. Ten plates.
    ("millbrook_millpond", "millbrook", "The Millpond", "common"),
    ("millbrook_miller", "millbrook", "The Old Miller", "uncommon"),
    ("millbrook_cobbles", "millbrook", "Market Cobbles", "common"),
    ("millbrook_bakehouse", "millbrook", "The Bakehouse Door", "common"),
    ("millbrook_notice_board", "millbrook", "The Notice Board", "common"),
    ("millbrook_bridge", "millbrook", "Millbrook Bridge", "common"),
    ("millbrook_swifts", "millbrook", "Swifts Over the Square", "uncommon"),
    ("millbrook_long_table", "millbrook", "The Long Table", "uncommon"),
    ("millbrook_ladder", "millbrook", "The Lamplighter's Ladder", "common"),
    ("millbrook_willow", "millbrook", "The Millbrook Willow", "rare"),
    # North Road: rising ground out of town toward the gate. Eight plates.
    ("north_road_waymarker", "north_road", "The Waymarker Stone", "uncommon"),
    ("north_road_bracken", "north_road", "Bracken", "common"),
    ("north_road_drystone_wall", "north_road", "Drystone Wall", "common"),
    ("north_road_curlew", "north_road", "Curlew", "uncommon"),
    ("north_road_foxglove", "north_road", "Foxglove", "common"),
    ("north_road_viewpoint", "north_road", "The Viewpoint", "common"),
    ("north_road_sheep_track", "north_road", "Sheep Track", "common"),
    ("north_road_rowan", "north_road", "Rowan at the Gate", "rare"),
    # High Fells: above the gate, and only reachable once it is open. Six.
    ("high_fells_cotton_grass", "high_fells", "Cotton Grass", "common"),
    ("high_fells_cairn", "high_fells", "The Cairn", "common"),
    ("high_fells_ravens", "high_fells", "Raven Pair", "uncommon"),
    ("high_fells_shieling", "high_fells", "The Shieling", "uncommon"),
    ("high_fells_late_snow", "high_fells", "Late Snow in the Gully", "common"),
    ("high_fells_inversion", "high_fells", "Cloud Inversion", "rare"),
)

_FLAVOR: dict[str, str] = {
    "east_road_hawthorn": "White in May, red in October, thorned all year in between.",
    "east_road_speedwell": (
        "Blue as a scrap of sky, and gone by the time you turn back to look at it."
    ),
    "east_road_cart_ruts": (
        "Two lines pressed into the mud by every load that ever went to market."
    ),
    "east_road_field_gate": (
        "Latched with baler twine since before anyone can remember. It still holds."
    ),
    "east_road_skylark": "Sings on the way up, which is harder than singing standing still.",
    "east_road_footbridge": "Three planks and a handrail over water that was here first.",
    "east_road_heron": "Stands so long in the shallows that the water forgets about it.",
    "east_road_sloes": "Bitter until the first frost, which is a kind of patience.",
    "east_road_dog_rose": "Grows where it likes, which is anywhere the hedge lets it through.",
    "east_road_footpath_sign": (
        "The way is open. It has always been open. Someone keeps the sign painted."
    ),
    "east_road_mill_wheel": (
        "Turned by the brook for two hundred years, and still turning when the water is up."
    ),
    "east_road_barn_owl": (
        "Hunts the verge without a sound, and is only ever seen by whoever is still out walking."
    ),
    "millbrook_millpond": (
        "Flat as a plate at first light, and full of sky until somebody throws a stone."
    ),
    "millbrook_miller": (
        "Knows the weather by the sound of his own wheel, and will tell you whether you asked."
    ),
    "millbrook_cobbles": "Set by hand, uneven on purpose, kinder to hooves than any flat road.",
    "millbrook_bakehouse": (
        "Open before dawn. You can find it by the smell from the top of the lane."
    ),
    "millbrook_notice_board": (
        "Everything the town needs doing, pinned up where everybody can see it."
    ),
    "millbrook_bridge": (
        "Two arches, one for the water and one for the flood that comes every few winters."
    ),
    "millbrook_swifts": (
        "Back the same week every year, screaming round the chimneys, gone again by August."
    ),
    "millbrook_long_table": (
        "Carried out for anyone the town wants to feed. It is not often put away."
    ),
    "millbrook_ladder": "Leans by the tap room door. Whoever passes at dusk is welcome to use it.",
    "millbrook_willow": (
        "Older than the mill it is named for, and still leaning over the water without falling in."
    ),
    "north_road_waymarker": (
        "Cut with a hand pointing north by somebody who wanted strangers to arrive safely."
    ),
    "north_road_bracken": (
        "Green to the waist in summer, rust to the ankle in winter, in the way in both."
    ),
    "north_road_drystone_wall": (
        "No mortar and no nails. Held up entirely by the care taken putting it there."
    ),
    "north_road_curlew": "You hear it long before you see it, and usually you never see it.",
    "north_road_foxglove": "Tall, purple, and best admired from the path.",
    "north_road_viewpoint": (
        "Everything you walked this morning, laid out small enough to hold in one hand."
    ),
    "north_road_sheep_track": "Not a road, but it knows the hill better than the road does.",
    "north_road_rowan": (
        "Planted where the road turns up into the fells, by somebody who never saw it grown."
    ),
    "high_fells_cotton_grass": (
        "White heads over black peat, marking ground that will take your boot if you let it."
    ),
    "high_fells_cairn": "Every walker adds a stone. Nobody has ever been asked to.",
    "high_fells_ravens": (
        "They travel in pairs, and they roll over in the air for no reason anyone can prove."
    ),
    "high_fells_shieling": (
        "A summer hut with a cold hearth, left unlocked for whoever needs it next."
    ),
    "high_fells_late_snow": "Lies in the north-facing cut until June out of sheer stubbornness.",
    "high_fells_inversion": (
        "Once or twice a year the valley fills with white and the tops become islands."
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

# Every milestone on every road, keyed by accolade id, so the accolades
# endpoint can name a row in user_accolades without walking the road list.
ACCOLADES: dict[str, Milestone] = {
    milestone.id: milestone for road in ROADS.values() for milestone in road.milestones
}


def _neighbours(location_id: str, unlocked: frozenset[str] | set[str]):
    """Every road out of a place that the player is allowed to walk today."""
    for road in ROADS.values():
        if road.region is not None and road.region not in unlocked:
            continue
        if road.from_id == location_id:
            yield road, road.to_id
        elif road.to_id == location_id:
            yield road, road.from_id


def route(start: str, destination: str, unlocked: frozenset[str] | set[str]) -> list[Road] | None:
    """The roads from one place to another, or None if there is no open way.

    Breadth first, so the answer is the fewest roads rather than the fewest
    miles. On a map this size the two are the same thing, and the shape of the
    map is a designed decision rather than something to be optimised over.
    """
    if start == destination:
        return []
    seen = {start}
    queue: deque[tuple[str, list[Road]]] = deque([(start, [])])
    while queue:
        node, path = queue.popleft()
        for road, other in _neighbours(node, unlocked):
            if other in seen:
                continue
            step = [*path, road]
            if other == destination:
                return step
            seen.add(other)
            queue.append((other, step))
    return None


def reachable(start: str, unlocked: frozenset[str] | set[str]) -> set[str]:
    """Everywhere a marker at `start` could get to on foot today, itself included."""
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for _road, other in _neighbours(node, unlocked):
            if other not in seen:
                seen.add(other)
                queue.append(other)
    return seen
