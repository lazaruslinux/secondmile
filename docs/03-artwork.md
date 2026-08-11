# Replacing the artwork

Every picture in secondmile is a file you can open in a vector editor or an
image editor. The application shipped with placeholder art on purpose, and
replacing it does not require touching any code.

## The register: everything waiting to be redrawn

Every file below is placeholder art, drawn to hold the shape until real art
arrives. Nothing here is final. The list is kept current as the app grows: a
round that adds a picture adds its row here in the same round, so this stays the
whole of what a commission would cover.

| Group | Files | What they are | Where they appear |
| --- | --- | --- | --- |
| Medals | 11 | One face per medal in the catalogue | You screen, Home rail, feed and Activity chips, avatar slots |
| Avatar borders | 6 | One per level tier, `border-t1` to `border-t6` | Around every avatar, every screen |
| Flourishes | 3 | The growth earned by encouraging people, `f1` to `f3` | Over the border, on every avatar |
| Interface icons | 10 | Tab bar, cheer, gear, pencil, play, sport diamond, chest ladder marker | Chrome, everywhere |
| Plants | 39 | Thirteen species at three growth stages each | The plot, and the reveal when a seed is found |
| Ground | 1 | The strip of soil a grove stands on, `ground` | The floor of the band across the top of both profiles |
| Loose pieces | 5 | Chest, gilding overlay, boost potion, water, unmarked seed | Inventory squares, chest reveals, finished plants |
| Landing hero | 1 | The four sports in four strips, `landing-hero` | The top of the landing page |

Seventy-six files in total, all under `frontend/src/assets/`.

There are two chest drawings on purpose. `grove/chest.svg` is a picture loaded
by URL with its own colours, used for an inventory square. `icons/chest.svg` is
placed straight into the page and drawn in `currentColor`, which is what lets
each marker on the chest ladder take the colour of its own rarity tier. They can
be redrawn to match each other, but they cannot become one file.

Four things a commission has to know, each learned the hard way here:

1. **Medals must tell each other apart at 28 pixels.** The placeholder races are
   one plate distinguished only by a stamped word, and that word is about three
   pixels tall in a feed chip. It has already forced two rounds of rework. Shape
   and colour have to carry the difference, not lettering.
2. **Borders keep their middle empty.** The photograph is inset inside the
   border at 13%, not cropped by it, so a border that fills its centre covers
   the face.
3. **Interface icons are drawn inline, not loaded as pictures.** That is what
   lets them take the colour of whatever holds them, which is how the bottom bar
   highlights the current tab. A replacement that hard-codes its own colours
   stops the highlight working.
4. **Plants are read as a sequence.** Three stages of one species have to look
   like one thing growing rather than three different plants, and the gilding
   overlay is drawn over the last stage rather than replacing it.

The two hard constraints in the next section apply to every file here, and both
fail silently rather than loudly, so they are worth reading before drawing
anything.

The rule the code follows: it reads the asset files as they are, addressed only
by the file names listed below. Everything else about a file, its shapes,
colours, layers, and size, is yours.

Files live under `frontend/src/assets`. After changing any of them, rebuild the
frontend:

```
docker compose up -d --build frontend
```

Two constraints apply to every SVG here:

- **Presentation attributes, not styles.** Use `fill="#..."` and
  `stroke="#..."` rather than `style="fill:#..."` or a `<style>` block. The
  application's content security policy does not allow inline styles, so
  anything styled that way is drawn without its styling. Editors that write
  style attributes by default usually have a setting to switch this.
- **Nothing loaded from elsewhere.** No external images, no fonts, no scripts.
  The app loads nothing from outside its own origin. Embed anything you need,
  and use generic font families for text.

The interface is dark and has no light variant, so every file here is drawn to
sit on a near-black card. The placeholder art follows the palette at the bottom
of this page; yours does not have to, as long as it reads on black.

## Interface icons

`frontend/src/assets/icons/*.svg`

The small line drawings in the interface chrome. Unlike everything else here,
these are drawn inline in the page rather than loaded as pictures, which is what
lets them take the colour of whatever holds them: the bottom bar draws its
current tab in the accent colour and the rest in grey, using the same file for
both.

| File | Where it appears |
| --- | --- |
| `tab-home.svg` | Home in the bottom bar |
| `tab-log.svg` | Activity in the bottom bar (the file keeps its name) |
| `tab-grove.svg` | Grove in the bottom bar |
| `tab-you.svg` | You in the bottom bar |
| `gear.svg` | The settings button in the You header |
| `pencil.svg` | The edit button in the You header |
| `diamond.svg` | The week strip on Home, one diamond per day |
| `cheer.svg` | The cheer button under a friend's workout on Home |
| `play.svg` | The mark over a video's poster in a workout's media strip |
| `chest.svg` | The markers along the chest ladder on You |
| `sport-walk.svg` | Beside the word Walk, wherever a walk is named |
| `sport-run.svg` | Beside the word Run, wherever a run is named |
| `sport-cycle.svg` | Beside the word Cycle, wherever a ride is named |
| `sport-swim.svg` | Beside the word Swim, wherever a swim is named |

Three rules on top of the two above, because these files are placed straight
into the page:

- **Draw on a 24 by 24 viewBox.** They are shown at about 24 pixels in the
  bottom bar, about 17 in the week strip and beside a sport, and about 14 in a
  table, so fine detail is wasted.
- **Use `currentColor`, never a fixed colour.** `stroke="currentColor"` and
  `fill="currentColor"` are what let one file be grey in one place and crimson
  in another. A hard-coded colour will simply ignore the interface.
- **Nothing but shapes.** No `<script>`, no `<style>`, no `<foreignObject>`, no
  external references. These files become part of the page, so anything else in
  them is a way into it.

`diamond.svg` is used in two states from the one file: a day with miles on it is
drawn as you drew it, and a day without has its fill removed by the stylesheet,
leaving the outline. Give the shape both a `fill="currentColor"` and a
`stroke="currentColor"` so both states have something to show.

The four `sport-*.svg` files are one set and are read as one, so they want the
same weight of line and the same amount of the square filled: they are drawn
side by side on You and one under the next under Activity. Each goes beside the
word for its sport and never instead of it, which is also why they are hidden from
screen readers wherever they are drawn.

## The landing hero

`frontend/src/assets/landing-hero.svg`

The one picture on the landing page, drawn above the verse and before anybody
has an account. It is the only file that sits at the top of `assets` rather than
in a folder, because it is the only one of its kind: one drawing, read by the
page by name.

A wide rectangle, roughly four to one, cut into four equal vertical strips. Left
to right they are walk, run, cycle, and swim, in the app's own order, each a
simple figure in the line the interface icons are drawn in. The strips are
divided by a one pixel rule in `--line` on the `--surface` card colour, and the
crimson appears once per strip as a short mark under the figure.

Each strip is a group with a stable id, and **these four ids are the swap
contract**:

| Id | Strip |
| --- | --- |
| `hero-walk` | First from the left |
| `hero-run` | Second |
| `hero-cycle` | Third |
| `hero-swim` | Fourth |

Keep the four ids and the shape of the file, and the rest is yours. The
placeholder is drawn on a `0 0 800 200` viewBox, which makes each strip a 200 by
200 square, and it carries a `width` and a `height` so the browser knows the
proportion before the file arrives and the page below it does not jump.

Unlike the interface icons, this one is loaded as a picture rather than placed
into the page, so it carries its own colours instead of `currentColor`. The
placeholder uses the palette at the foot of this page: `#0d0d0f` for the card,
`#26262b` for the rules, `#f4f4f5` for the figures, and `#dc143c` for the marks.
It is drawn to the full width of a 46rem column, so it is shown as wide as about
730 pixels and as narrow as a phone, and fine detail is lost at the narrow end.

The two constraints above hold here as they do everywhere: presentation
attributes only, since the content security policy drops a `style` attribute
without saying so, and nothing loaded from anywhere else.

## Avatar borders

`frontend/src/assets/borders/border-t1.svg` through `border-t6.svg`

The frame around the profile picture. Six files, one per tier, and the profile
draws the highest tier the player's level has reached:

| File | Earned at level |
| --- | --- |
| `border-t1.svg` | 0 |
| `border-t2.svg` | 6 |
| `border-t3.svg` | 10 |
| `border-t4.svg` | 15 |
| `border-t5.svg` | 25 |
| `border-t6.svg` | 35 |

Each file needs a `viewBox` and nothing else: no ids, no particular size. The
border is drawn over a square avatar and scaled to it, so **the picture sits
inside the middle of the viewBox**. Leave the centre empty or the frame will
cover somebody's face. A border that grows outward rather than inward is the
safe way to make a higher tier feel more substantial.

The levels are defined in `backend/app/config.py` as `BORDER_LEVELS`, and the
number of files has to match the length of that list.

## Border flourishes

`frontend/src/assets/borders/flourish-f1.svg` through `flourish-f3.svg`

Growth that wraps the border, drawn on top of whichever tier the player has.
Where the border is earned by covering miles, the flourish is earned by
encouraging other people, so the two are separate drawings over the same frame
and either one can change without the other:

| File | Stage |
| --- | --- |
| none | 0, a bare border |
| `flourish-f1.svg` | 1 |
| `flourish-f2.svg` | 2 |
| `flourish-f3.svg` | 3 |

The same rules as the borders apply: a `viewBox` and nothing else, drawn over
the whole square, **middle left empty** so nobody's face is covered. The
placeholder art is a vine that starts in one corner at stage 1, crosses the
foot of the frame and climbs both sides at stage 2, and closes over the top at
stage 3, so the stages read as one plant growing rather than three drawings.
Keep the covered length increasing from file to file for the same reason.

They are drawn everywhere a border is: the You banner, the summary card on
Home, friends' cards in the feed, and the friends list. Each is shown as small
as 40 pixels across in the feed, so keep the shapes bold enough to read there.

## Medals

`frontend/src/assets/badges/*.svg`

The whole reward system is eleven medals, drawn on the You screen as one list,
again down the rail on Home as the few earned most recently, and again as a chip
on every feed card and Activity row for the medals that workout earned. Every one of
them is
repeatable, so a medal is a count rather than a yes or a no: each is drawn once
with its number under it rather than once per earning, and one not yet earned is
the same file drawn dim.

Each medal reads exactly one file, and **this mapping is the swap contract**:
put a different drawing in the named file and that medal changes everywhere it
appears, with no code, no list, and no import to edit. The ids are the server's;
the file names are the mapping's, and it lives in `frontend/src/art.ts`.

| Id | File | Earned by |
| --- | --- | --- |
| `race_5k` | `race-5k.svg` | One run of 3.1 miles or more |
| `race_10k` | `race-10k.svg` | One run of 6.2 miles or more |
| `race_half` | `race-half.svg` | One run of 13.1 miles or more |
| `race_marathon` | `race-marathon.svg` | One run of 26.2 miles or more |
| `race_ultra` | `race-ultra.svg` | One run of 31.1 miles or more |
| `weekly_10` | `weekly-10.svg` | Ten miles inside one week, any activity |
| `weekly_15` | `weekly-15.svg` | Fifteen miles inside one week |
| `weekly_25` | `weekly-25.svg` | Twenty-five miles inside one week |
| `weekly_40` | `weekly-40.svg` | Forty miles inside one week |
| `early_riser` | `time-early-riser.svg` | A run of 5K or more started between four and six in the morning |
| `night_owl` | `time-night-owl.svg` | A run of 5K or more started between eight at night and four in the morning |

The medal ids are in `backend/app/medals.py`, in the catalogue near the top of
the file. The catalogue is eleven and fixed: it gains a medal by gaining a row
there and a file here, and the mapping in `art.ts` gaining a line.

Medals are still drawn in three shapes, so a screen of eleven does not read as
eleven versions of the same object:

- **Distance**, the five races: a struck plate with the distance in a band
  across the middle, and the step of the ladder counted in marks above it.
- **Weeks**, the four mileage weeks: a calendar rather than a plate, the week
  along its head and the mileage large in the middle.
- **Hours**, the two times of day: a plate again, with a picture on it and no
  lettering. Early Riser is a steaming coffee cup in front of a sunrise. Night
  Owl is an owl, with a crescent moon behind it.

Draw them as a set: the same size and weight, readable at a glance, because five
of them share the width of a phone screen. Medals are drawn small, roughly 56
pixels in the strip on You, 30 in the rail on Home, 28 in the chips on feed
cards and Activity rows, and 32 to 36 in the slots under the avatar, where they
are drawn round. Keep the artwork inside a circle and off fine detail.

Lettering inside a medal is gone by the chip size: MARATHON stamped across a
plate is about three pixels tall there. That is why the chip prints the medal's
name beside the drawing, and why the shape and colour of a medal, not its
lettering, have to be what tells it apart.

### The stars

Stars are an overlay the app draws, not artwork, and there is no file per star
to make. Every fifty earnings of the same medal adds one, to a limit of thirty
three, and the marks are spread evenly around the medal at whatever number it
has: the first straight up and the rest clockwise from it, so two sit opposite
each other and thirty three make a ring.

The overlay is drawn in the same 64 unit box the artwork uses, on a circle of
radius 30 about the centre, which is outside the rim of the placeholder plates.
Wherever stars can appear, the app insets the drawing itself to leave that ring
clear, and it insets every medal in the row rather than only the starred ones,
so the count is what changes and a medal is never resized under it. **Keep your
artwork inside a radius of about 27** in the same box, or the stars will sit on
top of it rather than around it.

The stars take the interface's own type colour rather than a colour of their
own. Anything finer, a colour that shifts as they mount up, is a later art pass
and is not built.

## Grove plants

`frontend/src/assets/grove/<species>-s1.svg`, `-s2.svg`, `-s3.svg`

Three drawings per species, one per stage of growth. Thirteen species, so
thirty nine files:

| Stage | File ends | What it shows |
| --- | --- | --- |
| Seedling | `-s1` | Just up, the first third of the first level |
| Growing | `-s2` | The rest of the way to level one |
| Grown | `-s3` | Full size, from level one on |

Every species levels. One level costs what that species costs: fifteen converted
miles for a common, forty for an uncommon, a hundred for a rare and for the
mustard. Level one is grown, which is where the third drawing starts, and a
plant goes on levelling from there without changing what it is drawn as. The
mustard is drawn as the real plant grows: a sprout, then a young plant, then a
tall stand of yellow flowers, at the same three points as everything else.

The species and the file each one reads:

| Species | Rarity | Files |
| --- | --- | --- |
| Strawberry bush | Common | `strawberry-s1.svg`, `-s2`, `-s3` |
| Banana tree | Common | `banana-s1.svg`, `-s2`, `-s3` |
| Raspberry bush | Common | `raspberry-s1.svg`, `-s2`, `-s3` |
| Blueberry bush | Common | `blueberry-s1.svg`, `-s2`, `-s3` |
| Blackberry bush | Uncommon | `blackberry-s1.svg`, `-s2`, `-s3` |
| Mango tree | Uncommon | `mango-s1.svg`, `-s2`, `-s3` |
| Grapevine | Uncommon | `grapevine-s1.svg`, `-s2`, `-s3` |
| Fig bush | Uncommon | `fig-bush-s1.svg`, `-s2`, `-s3` |
| Olives | Rare | `olive-s1.svg`, `-s2`, `-s3` |
| Dates | Rare | `dates-s1.svg`, `-s2`, `-s3` |
| Coffee | Rare | `coffee-s1.svg`, `-s2`, `-s3` |
| Pomegranate | Rare | `pomegranate-s1.svg`, `-s2`, `-s3` |
| Mustard | Rare | `mustard-s1.png`, `-s2`, `-s3` |

The mustard is real artwork now, the first species done (2026-08-11); the other
twelve remain placeholders, and its three files are the reference for what a
finished species looks like: 512 by 512, transparent, the ground at 464.

The species ids are in `backend/app/species.py`. An id written with an
underscore reads as a hyphen here, so `fig_bush` is `fig-bush-s1.svg`. A species
with no file draws nothing at all and the rest of the row is unaffected, so a
missing file costs a picture rather than a screen.

`.png`, `.webp`, and `.svg` all work. Four things to keep in mind:

- **Draw them standing on the same floor.** Every plant is bottom aligned
  wherever it appears, so leave no empty space under it and keep the ground at
  the same height in all thirty nine files. The placeholder art puts it at 58
  in a 64 by 64 viewBox, and the band across the top of a profile stands the
  whole row on that line: see the ground below.
- **Scale is the story.** The three stages are read side by side down the plot
  and along the band on the profile, and a grown olive tree standing next to a
  seedling is how growth shows. Make each stage plainly bigger than the last,
  and let a rare tree tower over a common bush.
- **They are drawn small.** Roughly 88 pixels tall in the plot, 36 to 52 in the
  band across the top of the profile, and 72 in the satchel and a chest reveal.
  Silhouettes read at that size; fine detail does not.
- **Distinct at a glance.** Thirteen species share one plot, so shape carries
  more than colour: a vine on a wire, an arching bramble, a flat olive crown, a
  round pomegranate crown, banana paddles, a date palm's bare trunk and fronds.

### The ground

`frontend/src/assets/grove/ground.svg`

One strip of soil, drawn along the floor of the band across the top of both
profiles, with the whole plot standing on its top edge. Only the band reads it:
the plot on the Grove screen and the row in the Home rail draw their plants
without it.

The strip is stretched to the width of the band, which is a phone's screen at
one end and most of a desktop window at the other, so draw it low and wide and
keep what is in it horizontal. A speck of texture becomes a smear four times its
width on the wide end; a layer or a seam does not. An SVG has to carry
`preserveAspectRatio="none"` to stretch at all, and without it the drawing is
fitted to the height and left floating in the middle of the strip. A `.png` or a
`.webp` stretches on its own.

Every plant in the band is dropped by a seventh of its height, which puts the
ground line each drawing carries at 58 just under the soil's top edge and is
what makes the row share one floor. So the top of the strip has to be solid
across its whole width: a feathered or broken edge lets those lines show through
and the plants go back to floating on dashes of their own.

### The gild

`frontend/src/assets/grove/gild.svg`

A plant that reaches the last level is fully grown and gilded, and stays that
way. One file is laid over the grown drawing wherever it appears, in the plot
and in the band across the top of the profile, so every species shares the same
treatment for now: a plain gold ring in the same 64 by 64 viewBox, centred on
the picture, with nothing solid in the middle to hide the plant behind it.

Gilded artwork per species is a later pass and is not built. When each species
has its own, this file comes out and the drawings replace it.

### The tools

`frontend/src/assets/grove/water.svg`, `oil.svg`, and `wish.svg`

The three things a chest holds that are not a seed. They live beside the plants
because they are used on them, and each reads one file named after its kind, so
swapping any of them is the same one-file swap as everything else here. A file
that is not there costs the picture and nothing else: the satchel row and the
chest reveal both still read. The file names are the item kinds the code and the
API use, which is why the potion's file is `oil.svg`: the picture and the word
on screen changed, the kind did not.

| File | What it is | Rarity |
| --- | --- | --- |
| `water.svg` | Water, poured onto one plant | none |
| `oil.svg` | The boost potion, used to anoint a friend | Legendary |
| `wish.svg` | The unmarked seed, spent on any species the grove is missing | Epic |

Drawn in the same 64 by 64 viewBox as the plants, and shown at 72 pixels in the
satchel and in a chest reveal. Unlike a plant, none of them stands on a floor:
each is centred in its square, so draw them to fill the box rather than to sit
on the bottom of it. In a chest reveal the picture is what is pressed to find
out what the thing is for, so give it enough shape to look pressable.

The potion and the wish are drawn inside a rarity frame, so the two pixels
around the square are the frame's rather than the drawing's; water is the one
thing in the satchel with no rarity, and it is drawn in a plain square. The
rarity of a tool is fixed by what it is rather than rolled, so a wish is always
epic and the potion is always legendary. The two are both purple and have to
read apart at 72 pixels: the wish is a muted epic teardrop with stars, the potion
a bright stoppered flask.

### The chest

`frontend/src/assets/grove/chest.svg`

An unopened chest, which sits on the inventory grid alongside the tools and is
read the same way: one file named after its kind, swapped on its own. Chests
stack onto one square whatever step of the ladder dropped them, so this drawing
carries no tier colour and is framed in no rarity. Same 64 by 64 viewBox,
centred rather than standing on a floor, and still shut: what is inside is the
whole of what opening it is for.

## Rarity frames

Not artwork, and no file to swap: every square holding a plant, a seed, or a
tool with a rarity is bordered in that rarity, with the rarity named on a solid
tab hanging off the foot of the square. Five frames, drawn from the palette
below, and the tab prints its name in black on the same colour as the border.
The gild is a separate treatment and stays on the drawing itself, so a fully
grown rare plant carries both.

Seeds roll no higher than rare. The two steps above that belong to the tools,
which is what makes an epic or a legendary frame mean something when it appears.

| Rarity | Colour | What carries it |
| --- | --- | --- |
| Common | `--text` | Four species |
| Uncommon | `--rarity-uncommon` | Four species |
| Rare | `--rarity-rare` | Five species |
| Epic | `--rarity-epic` | The unmarked seed |
| Legendary | `--rarity-legendary` | The boost potion |

The same five colours name the chests. A chest is named for the step of the
ladder it dropped on, and that name is printed in the step's colour: a 5K chest
in the type colour, a 10K in the uncommon blue, a Half in the rare gold, a
Marathon in the epic purple, an Ultra in the legendary orange.

## Profile pictures

Not artwork, and not replaceable here: each player uploads their own. The
server re-encodes every upload to a 512 by 512 webp and stores it outside the
frontend build, so nothing in `assets` affects it.

## What is not a file yet

The interface itself, the buttons, the colours, the type, is plain CSS in
`frontend/src/styles.css`, not artwork. The whole palette is ten custom
properties at the top of that file:

| Property | Value | What it is |
| --- | --- | --- |
| `--bg` | `#000000` | The page, and the gutters between cards |
| `--surface` | `#0d0d0f` | Cards |
| `--line` | `#26262b` | Every border and rule |
| `--text` | `#f4f4f5` | Type and numbers, and the common rarity frame |
| `--muted` | `#9a9aa0` | Labels and secondary type |
| `--accent` | `#dc143c` | The one accent, used sparingly |
| `--rarity-uncommon` | `#4a8fd9` | The uncommon frame and its tab, and the 10K chest |
| `--rarity-rare` | `#d4af37` | The rare frame and its tab, and the Half chest |
| `--rarity-epic` | `#a06cd5` | The epic frame and its tab, and the Marathon chest |
| `--rarity-legendary` | `#e0762e` | The legendary frame and its tab, and the Ultra chest |

There is one theme and it is dark. Changing the ten values above is the whole of
a recolour; `--accent` on its own is the quickest way to make the app look like
something else. The four rarity colours are read on a near-black card and
printed on in black, so a replacement has to work both ways round: each of the
four clears 5:1 against the card behind it and 5:1 against the black type on it.
The legendary orange is deliberately not a second gold, so that a legendary tab
is never mistaken for the rare one or for the gild on a finished plant.
