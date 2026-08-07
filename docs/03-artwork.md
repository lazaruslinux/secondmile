# Replacing the artwork

Every picture in secondmile is a file you can open in a vector editor or an
image editor. The application shipped with placeholder art on purpose, and
replacing it does not require touching any code.

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
| `tab-log.svg` | Log in the bottom bar |
| `tab-grove.svg` | Grove in the bottom bar |
| `tab-you.svg` | You in the bottom bar |
| `gear.svg` | The settings button in the You header |
| `pencil.svg` | The edit button in the You header |
| `diamond.svg` | The week strip on Home, and the sport diamonds on You |
| `cheer.svg` | The cheer button under a friend's workout on Home |

Three rules on top of the two above, because these files are placed straight
into the page:

- **Draw on a 24 by 24 viewBox.** They are shown at about 24 pixels in the
  bottom bar and about 17 in the week strip, so fine detail is wasted.
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

The whole reward system is twelve medals in four families, drawn on the You
screen family by family and again down the rail on Home. Every one of them is
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
| `second_mile` | `second-mile.svg` | Twenty miles inside one week, which is double the smallest weekly target |

The medal ids are in `backend/app/medals.py`, in the catalogue near the top of
the file. The catalogue is twelve and fixed: a family gains a medal by gaining a
row there and a file here, and the mapping in `art.ts` gaining a line.

Four families, and the placeholder art gives each one a shape of its own so a
screen of twelve does not read as twelve versions of the same object:

- **Distance**, the five races: a struck plate with the distance in a band
  across the middle, and the step of the ladder counted in marks above it.
- **Weeks**, the four mileage weeks: a calendar rather than a plate, the week
  along its head and the mileage large in the middle.
- **Hours**, the two times of day: a plate again, with a picture on it and no
  lettering. Early Riser is a steaming coffee cup in front of a sunrise. Night
  Owl is an owl, with a crescent moon behind it.
- **Second mile**, on its own: a milestone marker reading II.

Draw them as a set: the same size and weight, readable at a glance, because five
of them share the width of a phone screen. Medals are drawn small, roughly 56
pixels in the strip on You, 30 in the rail on Home, and 32 to 36 in the slots
under the avatar, where they are drawn round. Keep the artwork inside a circle
and off fine detail.

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
mustard is drawn the way the parable tells it, a plant, then a shrub, then a
tree, at the same three points as everything else.

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
| Mustard | Rare | `mustard-s1.svg`, `-s2`, `-s3` |

The species ids are in `backend/app/species.py`. An id written with an
underscore reads as a hyphen here, so `fig_bush` is `fig-bush-s1.svg`. A species
with no file draws nothing at all and the rest of the row is unaffected, so a
missing file costs a picture rather than a screen.

`.png`, `.webp`, and `.svg` all work. Four things to keep in mind:

- **Draw them standing on the same floor.** Every plant is bottom aligned
  wherever it appears, so leave no empty space under it and keep the ground at
  the same height in all thirty nine files. The placeholder art puts it at 58
  in a 64 by 64 viewBox.
- **Scale is the story.** The three stages are read side by side down the plot
  and along the band on the profile, and a grown olive tree standing next to a
  seedling is how growth shows. Make each stage plainly bigger than the last,
  and let a rare tree tower over a common bush.
- **They are drawn small.** Roughly 88 pixels tall in the plot, 36 to 52 in the
  band across the top of the profile, and 44 in the satchel and a chest reveal.
  Silhouettes read at that size; fine detail does not.
- **Distinct at a glance.** Thirteen species share one plot, so shape carries
  more than colour: a vine on a wire, an arching bramble, a flat olive crown, a
  round pomegranate crown, banana paddles, a date palm's bare trunk and fronds.

### The gild

`frontend/src/assets/grove/gild.svg`

A plant that reaches the last level is fully grown and gilded, and stays that
way. One file is laid over the grown drawing wherever it appears, in the plot
and in the band across the top of the profile, so every species shares the same
treatment for now: a plain gold ring in the same 64 by 64 viewBox, centred on
the picture, with nothing solid in the middle to hide the plant behind it.

Gilded artwork per species is a later pass and is not built. When each species
has its own, this file comes out and the drawings replace it.

## Profile pictures

Not artwork, and not replaceable here: each player uploads their own. The
server re-encodes every upload to a 512 by 512 webp and stores it outside the
frontend build, so nothing in `assets` affects it.

## What is not a file yet

The interface itself, the buttons, the colours, the type, is plain CSS in
`frontend/src/styles.css`, not artwork. The whole palette is six custom
properties at the top of that file:

| Property | Value | What it is |
| --- | --- | --- |
| `--bg` | `#000000` | The page, and the gutters between cards |
| `--surface` | `#0d0d0f` | Cards |
| `--line` | `#26262b` | Every border and rule |
| `--text` | `#f4f4f5` | Type and numbers |
| `--muted` | `#9a9aa0` | Labels and secondary type |
| `--accent` | `#dc143c` | The one accent, used sparingly |

There is one theme and it is dark. Changing the six values above is the whole
of a recolour; `--accent` on its own is the quickest way to make the app look
like something else.
