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
| Medals | 32 | One face per medal in the catalogue | You screen, Home rail, feed and Activity chips, avatar slots |
| Avatar borders | 6 | One per level tier, `border-t1` to `border-t6` | Around every avatar, every screen |
| Flourishes | 3 | The growth earned by encouraging people, `f1` to `f3` | Over the border, on every avatar |
| Interface icons | 18 | Tab bar, cheer, gear, pencil, play, eye, chest ladder marker, week diamond, running shoe, and the five sport marks | Chrome, everywhere |
| Plants | 39 | Thirteen species at three growth stages each | The plot, and the reveal when a seed is found |
| Ground | 1 | The strip of soil a grove stands on, `ground` | The floor of the band across the top of both profiles |
| Loose pieces | 5 | Chest, gilding overlay, boost potion, water, unmarked seed | Inventory squares, chest reveals, finished plants |
| Landing hero | 2 | The four sports in four strips, one drawing per ground, `landing-hero-dark` and `landing-hero-light` | The top of the landing page |

One hundred and six files in total, all under `frontend/src/assets/`.

Every `border-t` file also has a `-light` twin beside it, such
as `border-t3-light.svg`, which is the same drawing with its palette turned over
for the light ground. Those twins are generated from the originals rather than
drawn, so they are not counted above and a commission does not cover them: draw
the original and the twin is regenerated from whatever arrives. Nothing else in
the register has a twin any more: the medals and the flourishes are pixel art
that reads on every ground, and their twins are retired and deleted.

There are two chest drawings on purpose. `grove/chest.png` is a picture loaded
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

The interface ships dark by default, with a light appearance and an arcade one
the reader can choose instead. Arcade is a skin over the dark ground rather than
a ground of its own, so anything drawn twice is drawn for light and dark and
nothing has to be drawn a third time. The art wells behind plants, medals, and
chest reveals stay near-black on every appearance. Every file here is drawn to
sit on that near-black card; interface icons are the exception, since they take
the page's own colour.
The placeholder art follows the palette at the bottom of this page; yours does
not have to, as long as it reads on black. Art drawn only in pale greys will
wash out on the light ground wherever it sits outside a well, which is what the
`-light` twins are for.

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
| `tab-friends.svg` | Friends in the bottom bar |
| `tab-you.svg` | You in the bottom bar |
| `gear.svg` | The settings button in the You header |
| `pencil.svg` | The edit button in the You header |
| `diamond.svg` | The week strip on Home, one diamond per day |
| `cheer.svg` | The cheer button under a friend's workout on Home |
| `play.svg` | The mark over a video's poster in a workout's media strip |
| `chest.svg` | The markers along the chest ladder on You |
| `sport-walk.svg` | Beside the word Walk, wherever a walk is named |
| `sport-run.svg` | Beside the word Run, wherever a run is named. HIS MARK (2026-08-21): a filled winged-shoe silhouette traced from his 2M master, not a placeholder and not part of the commission. Filled where the other three sport marks are line-drawn, which is what keeps it tellable from walk at 14 px |
| `sport-cycle.svg` | Beside the word Cycle, wherever a ride is named |
| `sport-swim.svg` | Beside the word Swim, wherever a swim is named |
| `sport-treadmill.svg` | Instead of the walk or run mark, wherever an indoor one is drawn |
| `shoe.svg` | Gear: the Shoes heading on both profiles and the shoe picker in a card's edit panel (feed cards carry no gear) |
| `eye.svg` | The View public profile button on the You screen |

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

The five `sport-*.svg` files are one set and are read as one, so they want the
same weight of line and the same amount of the square filled: they are drawn
side by side on You and one under the next under Activity. Each goes beside the
word for its sport and never instead of it, which is also why they are hidden from
screen readers wherever they are drawn.

`shoe.svg` is not one of that set and must not be drawn as one. It is a pair of
shoes rather than a sport: it stands for gear, it sits next to a walk mark on
the same card, and the two have to be told apart at a glance. The placeholder is
a side-on running shoe with laces and a lugged sole.

`sport-treadmill.svg` is the fifth of that set and the odd one out: it is not a
sport but a place, drawn instead of the walk or run mark when the export named
the session indoors. It is only ever swapped in for those two, because a
stationary bike and a pool are neither a treadmill nor each other, and the
totals and filters that name an activity in the abstract always draw that
activity's own mark. The placeholder is a belt with an upright and a console.

## The landing hero

`frontend/src/assets/landing-hero-dark.png` and
`frontend/src/assets/landing-hero-light.png`

The one picture on the landing page, drawn above the verse and before anybody
has an account. They are the only files that sit at the top of `assets` rather
than in a folder, because they are the only ones of their kind: one drawing per
ground, and the page shows whichever matches the theme.

REAL ART since 2026-08-11, redrawn as a pair 2026-08-14: his finished pieces.
Each is a 2000 by 500 transparent PNG, four to one, cut into four equal 500 by
500 strips. Left to right they are walk, run, cycle, and swim, in the app's own
order. The dark-ground file draws the figures light, the light-ground file
draws them in the deep crimson family, each on transparency so it sits on
whatever the page colour is. The strips are divided by hairlines drawn into the
files. The old SVG swap contract (the four `hero-*` group ids) retired with the
placeholder; a future replacement only has to keep the four-to-one shape, the
four-strip order, and the one-file-per-ground pairing.

Unlike the interface icons, these are loaded as pictures rather than placed
into the page, so they carry their own colours instead of `currentColor`. They
are drawn to the full width of a 46rem column, so each is shown as wide as
about 730 pixels and as narrow as a phone, and fine detail is lost at the
narrow end.

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

`frontend/src/assets/borders/flourish-f1.png` through `flourish-f3.png`

Growth that wraps the border, drawn on top of whichever tier the player has.
Where the border is earned by covering miles, the flourish is earned by
encouraging other people, so the two are separate drawings over the same frame
and either one can change without the other:

| File | Stage |
| --- | --- |
| none | 0, a bare border |
| `flourish-f1.png` | 1 |
| `flourish-f2.png` | 2 |
| `flourish-f3.png` | 3 |

These are pixel art rather than SVG, drawn to the same spec as the grove plants
below: native 48 by 48, nothing anti-aliased, transparent background. They are
laid over the whole square with the **middle left empty** so nobody's face is
covered. The placeholder is a vine that starts low in one corner at stage 1,
climbs the side of the frame at stage 2, and carries on over the top at stage 3,
so the stages read as one plant growing rather than three drawings. Keep the
covered length increasing from file to file for the same reason.

They are drawn everywhere a border is: the You banner, the summary card on
Home, friends' cards in the feed, and the friends list. Each is shown as small
as 40 pixels across in the feed, so keep the shapes bold enough to read there.

## Medals

`frontend/src/assets/badges/*.png`

The whole reward system is thirty-two medals, drawn on the You screen as one list,
again down the rail on Home as the few earned most recently, and again as a chip
on every feed card and Activity row for the medals that workout earned. All but
the twelve lifetime medals are repeatable, so a medal is a count rather than a
yes or a no: each is drawn once with its number under it rather than once per
earning, and one not yet earned is the same file drawn dim.

Each medal reads exactly one file, and **this mapping is the swap contract**:
put a different drawing in the named file and that medal changes everywhere it
appears, with no code, no list, and no import to edit. The ids are the server's;
the file names are the mapping's, and it lives in `frontend/src/art.ts`.

| Id | File | Earned by |
| --- | --- | --- |
| `race_1mi` | `race-1mi.png` | One walk or run of 1 mile or more |
| `race_2mi` | `race-2mi.png` | One walk or run of 2 miles or more |
| `race_5k` | `race-5k.png` | One walk or run of 3.1 miles or more |
| `race_10k` | `race-10k.png` | One walk or run of 6.2 miles or more |
| `race_half` | `race-half.png` | One walk or run of 13.1 miles or more |
| `race_marathon` | `race-marathon.png` | One walk or run of 26.2 miles or more |
| `race_ultra` | `race-ultra.png` | One walk or run of 31.1 miles or more |
| `weekly_10` | `weekly-10.png` | Ten miles inside one week, any activity |
| `weekly_15` | `weekly-15.png` | Fifteen miles inside one week |
| `weekly_25` | `weekly-25.png` | Twenty-five miles inside one week |
| `weekly_40` | `weekly-40.png` | Forty miles inside one week |
| `early_riser` | `time-early-riser.png` | A walk or run of a mile or more started between four and six in the morning |
| `night_owl` | `time-night-owl.png` | A walk or run of a mile or more started between eight at night and four in the morning |
| `cycle_10` | `cycle-10.png` | One ride of 10 miles or more |
| `cycle_25` | `cycle-25.png` | One ride of 25 miles or more |
| `cycle_50` | `cycle-50.png` | One ride of 50 miles or more |
| `cycle_100` | `cycle-100.png` | One ride of 100 miles or more |
| `swim_half` | `swim-half.png` | One swim of half a mile or more |
| `swim_1` | `swim-1.png` | One swim of a mile or more |
| `swim_2` | `swim-2.png` | One swim of 2 miles or more |
| `lifetime_100` | `lifetime-100.png` | 100 miles covered in total, any activity, earned once |
| `lifetime_250` | `lifetime-250.png` | 250 miles covered in total, earned once |
| `lifetime_500` | `lifetime-500.png` | 500 miles covered in total, earned once |
| `lifetime_1000` | `lifetime-1000.png` | 1000 miles covered in total, earned once |
| `cycle_lifetime_100` | `cycle-lifetime-100.png` | 100 miles ridden in total, earned once |
| `cycle_lifetime_250` | `cycle-lifetime-250.png` | 250 miles ridden in total, earned once |
| `cycle_lifetime_500` | `cycle-lifetime-500.png` | 500 miles ridden in total, earned once |
| `cycle_lifetime_1000` | `cycle-lifetime-1000.png` | 1000 miles ridden in total, earned once |
| `swim_lifetime_10` | `swim-lifetime-10.png` | 10 miles swum in total, earned once |
| `swim_lifetime_25` | `swim-lifetime-25.png` | 25 miles swum in total, earned once |
| `swim_lifetime_50` | `swim-lifetime-50.png` | 50 miles swum in total, earned once |
| `swim_lifetime_100` | `swim-lifetime-100.png` | 100 miles swum in total, earned once |

The medal ids are in `backend/app/medals.py`, in the catalogue near the top of
the file. The catalogue is thirty-two and fixed: it gains a medal by gaining a
row there and a file here, and the mapping in `art.ts` gaining a line.

Medals are drawn in eight shapes, one per family, so a screen of thirty-two does
not read as thirty-two versions of the same object:

- **Distance**, the seven races: a struck plate with the distance in a band
  across the middle, and the step of the ladder counted in marks above it. The
  marks start at the 5K, which was the smallest medal there was when they were
  drawn; the mile and the two miles sit below the ladder and carry none, and the
  Second Mile takes a crimson underline instead because the app is named for it.
- **Weeks**, the four mileage weeks: a calendar rather than a plate, the week
  along its head and the mileage large in the middle.
- **Hours**, the two times of day: a plate again, with a picture on it and no
  lettering. Early Riser is a steaming coffee cup in front of a sunrise. Night
  Owl is an owl, with a crescent moon behind it.
- **Rides**, the four cycling medals: a wheel, with spokes to the rim and the
  distance on the hub.
- **Swims**, the three swimming medals: a plate with the distance above two
  waves rather than in a band.
- **Lifetime**, the four odometer medals: not a plate at all but an odometer
  window, wide and rounded, with a gauge arc over it. These count every mile
  covered in any activity.
- **Miles ridden**, the four lifetime cycling medals: the same odometer window
  under a wheel instead of the gauge arc, and RIDDEN under the number.
- **Miles swum**, the four lifetime swimming medals: the same window again under
  two waves, and SWUM under the number.

The twelve lifetime medals are the only ones earned once each rather than
counted. All twelve read raw miles on the ground, the same as every other medal
here: nothing in the catalogue is counted in converted Miles.

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

### The pixel set (2026-08-20)

The thirty-two faces are now 48x48 pixel-art PNGs in the same language as the
grove plants, and they are still placeholders for the commissioned pass. One
file per medal serves every ground: the `-light` twins are retired and deleted,
because the plates read on dark, light and any future ground alike. A
replacement must follow the grove's pixel spec (native 48x48, three or four
shades a hue, one warm near-black outline ring, transparent background, no
anti-aliasing; the app draws them with image-rendering: pixelated). Family is
carried by the motif: a crimson ribbon on the race plates, the red week tab on
the weekly plates, laurel sprigs on lifetime, waves on every swim, a chainring
on every cycle, and the two time-of-day plates carry a sun and a stamped
crescent instead of a figure.

## Grove plants

`frontend/src/assets/grove/<species>-s1.png`, `-s2.png`, `-s3.png`

Three drawings per species, one per stage of growth. Thirteen species, so
thirty nine files. The committed set is pixel art: each file is a PNG drawn on a
native 48 by 48 canvas and blown up square-edged by the browser. Like everything
else in this register it is placeholder art, drawn to hold the shape until real
art arrives, and the pixel spec below is what a replacement has to follow.

The three stages:

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
| Strawberry bush | Common | `strawberry-s1.png`, `-s2`, `-s3` |
| Banana tree | Common | `banana-s1.png`, `-s2`, `-s3` |
| Raspberry bush | Common | `raspberry-s1.png`, `-s2`, `-s3` |
| Blueberry bush | Common | `blueberry-s1.png`, `-s2`, `-s3` |
| Blackberry bush | Uncommon | `blackberry-s1.png`, `-s2`, `-s3` |
| Mango tree | Uncommon | `mango-s1.png`, `-s2`, `-s3` |
| Grapevine | Uncommon | `grapevine-s1.png`, `-s2`, `-s3` |
| Fig bush | Uncommon | `fig-bush-s1.png`, `-s2`, `-s3` |
| Olives | Rare | `olive-s1.png`, `-s2`, `-s3` |
| Dates | Rare | `dates-s1.png`, `-s2`, `-s3` |
| Coffee | Rare | `coffee-s1.png`, `-s2`, `-s3` |
| Pomegranate | Rare | `pomegranate-s1.png`, `-s2`, `-s3` |
| Mustard | Rare | `mustard-s1.png`, `-s2`, `-s3` |

The mustard was the first species finished (2026-08-11) and its three
paintings are the reference for what a finished species looks like: 512 by
512, transparent, the ground at 464. Like every hand-made piece they live in
the custom layer above rather than in the repository, and the committed files
here are the placeholders every fresh build falls back to.

The species ids are in `backend/app/species.py`. An id written with an
underscore reads as a hyphen here, so `fig_bush` is `fig-bush-s1.png`. A species
with no file draws nothing at all and the rest of the row is unaffected, so a
missing file costs a picture rather than a screen.

`.png`, `.webp`, and `.svg` all work. Four things to keep in mind:

- **Draw them standing on the same floor.** Every plant is bottom aligned
  wherever it appears, so leave no empty space under it and keep the ground at
  the same height in all thirty nine files. The placeholder set stands them on
  the same row near the foot of the canvas, and the band across the top of a
  profile stands the whole row on that line: see the ground below.
- **Scale is the story.** The three stages are read side by side down the plot
  and along the band on the profile, and a grown olive tree standing next to a
  seedling is how growth shows. Make each stage plainly bigger than the last,
  and let a rare tree tower over a common bush.
- **They are drawn small.** Roughly 88 pixels tall in the plot, 36 to 52 in the
  band across the top of the profile, and 72 in the inventory and a chest reveal.
  Silhouettes read at that size; fine detail does not.
- **Distinct at a glance.** Thirteen species share one plot, so shape carries
  more than colour: a vine on a wire, an arching bramble, a flat olive crown, a
  round pomegranate crown, banana paddles, a date palm's bare trunk and fronds.

### The pixel spec

The plants are the one group here drawn as pixel art. A replacement has to be
drawn the same way or it will not sit with the rest of the row:

- **Native 48 by 48.** Draw at that size, one drawn pixel to one image pixel,
  and save it that size. The app does the enlarging.
- **Nothing anti-aliased.** The app draws these with the CSS
  `image-rendering: pixelated`, so every edge is enlarged square. Soft edges and
  half-transparent pixels come out as fringe rather than as smoothing, so turn
  the editor's smoothing off. The background is fully transparent, not a matte
  in the colour of the well behind it.
- **Three or four shades a hue.** A base, a light and a shadow, and one more at
  most. Any more than that turns to mush at the size these are read.
- **A warm near-black ring.** Outline the whole silhouette in one warm
  near-black rather than pure black or a colour per part. That ring is what
  holds a plant together on both grounds.
- **It has to read twice.** In the dark appearance a plant stands on the
  near-black art well; in the light one the square behind it is transparent and
  the same drawing stands on a pale card. Look at both before calling one done.
- **PNG, or webp.** Pixel art is not a job for an SVG, so the presentation
  attribute rule at the top of this page does not reach the plants. It still
  holds for every SVG in the app: the icons, borders, medals, ground and gild
  are all bound by it.

A file in the custom layer below is exempt from all of this. Those are paintings
rather than pixel art, and the app scales them smoothly on purpose.

### Work in progress: the custom layer

`frontend/src/assets/grove-custom/` is a git-ignored folder the build reads
FIRST: a file there, named exactly like its committed namesake (hyphens,
`coffee-s1.png`), replaces it at the next build without touching the
repository. This is where hand-made art lives while it is being worked on,
one species at a time, so the instance can wear it before any of it is
final. The committed files under `assets/grove/` stay as the fallback every
fresh clone and CI build uses. When a species' art is declared FINISHED it
moves into `assets/grove/` and gets committed, and its row below changes
from placeholder to real.

Living there now: `mustard-s1/s2/s3.png` (finished 2026-08-11, the
reference set) and `coffee-s1/s2/s3.png` (2026-08-12, three style studies;
not final). None of it is committed; that is the point.

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

Every plant in the band is dropped by a seventh of its height, which tucks the
foot of each drawing just under the soil's top edge and is what makes the row
share one floor. So the top of the strip has to be solid across its whole width:
a feathered or broken edge lets those lines show through and the plants go back
to floating on dashes of their own.

### The gild

`frontend/src/assets/grove/gild.svg`

A plant that reaches the last level is fully grown and gilded, and stays that
way. One file is laid over the grown drawing wherever it appears, in the plot
and in the band across the top of the profile, so every species shares the same
treatment for now: a plain gold ring on a 64 by 64 viewBox, centred on the
picture, with nothing solid in the middle to hide the plant behind it.

Gilded artwork per species is a later pass and is not built. When each species
has its own, this file comes out and the drawings replace it.

### The tools

`frontend/src/assets/grove/water.png`, `oil.png`, and `wish.png`

The three things a chest holds that are not a seed. They live beside the plants
because they are used on them, and each reads one file named after its kind, so
swapping any of them is the same one-file swap as everything else here. A file
that is not there costs the picture and nothing else: the inventory row and the
chest reveal both still read. The file names are the item kinds the code and the
API use, which is why the potion's file is `oil.png`: the picture and the word
on screen changed, the kind did not.

| File | What it is | Rarity |
| --- | --- | --- |
| `water.png` | Water, poured onto one plant | none |
| `oil.png` | The boost potion, used to anoint a friend | Legendary |
| `wish.png` | The unmarked seed, spent on any species the grove is missing | Epic |

Drawn to the plants' own pixel spec, native 48 by 48, and shown at 72 pixels in
the inventory and in a chest reveal. Unlike a plant, none of them stands on a
floor: each is centred in its square, so draw them to fill the box rather than
to sit on the bottom of it. In a chest reveal the picture is what is pressed to find
out what the thing is for, so give it enough shape to look pressable.

The potion and the wish are drawn inside a rarity frame, so the two pixels
around the square are the frame's rather than the drawing's; water is the one
thing in the inventory with no rarity, and it is drawn in a plain square. The
rarity of a tool is fixed by what it is rather than rolled, so a wish is always
epic and the potion is always legendary. The two are both purple and have to
read apart at 72 pixels: the wish is a muted epic teardrop with stars, the potion
a bright stoppered flask.

### The chest

`frontend/src/assets/grove/chest.png`

An unopened chest, which sits on the inventory grid alongside the tools and is
read the same way: one file named after its kind, swapped on its own. Chests
stack onto one square whatever step of the ladder dropped them, so this drawing
carries no tier colour and is framed in no rarity. The same pixel spec again,
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
`frontend/src/styles.css`, not artwork. Every colour in it is a custom property
in the block at the top of that file, and these ten are the ones the rest is
built out of. The values are the dark ground's:

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

There are three appearances: dark, which is the default and the values above;
light, which sets its own further down the same file; and arcade, a dark-hall
skin that sets its own again. A recolour means changing a value in each block
that defines it. `--accent` is the quickest way to make the app look like
something else, and it is defined twice rather than three times: light inherits
the crimson on purpose, because it is the brand rather than a ground.

The four rarity colours are read on a near-black card and printed on in black,
so a replacement has to work both ways round: each of the four clears 5:1
against the card behind it and 5:1 against the black type on it.
The legendary orange is deliberately not a second gold, so that a legendary tab
is never mistaken for the rare one or for the gild on a finished plant.

## The favicon

`frontend/public/favicon.png` and `frontend/public/apple-touch-icon.png`

HIS ART, NOT A PLACEHOLDER (2026-08-21, the register's first real piece):
a crimson winged shoe over water, a dark crimson cross behind, "2M" in
Barlow 800 white beneath, on a black rounded square. Master is a 512 px
PNG he painted (kept outside the repo); favicon.png is it at 64,
apple-touch-icon.png at 180. The earlier generated favicon.svg (shoe over
a crimson 2M, Barlow paths) is deleted; it lives in git history if ever
wanted. These live in `public/` rather than `assets/` because the page
names them by URL before the bundle loads; not counted in the placeholder
register above, and NOT part of the commission.

`frontend/public/icon-192.png` and `frontend/public/icon-512.png` are the same
mark squared for the web app manifest, which is what an installed
home-screen app and its notifications wear. Derived, not drawn: regenerate
from his master PNG (resize to 192; 512 is the master's own size) whenever
the mark changes, and do not count them in the commission either.

## The masthead shoe

`frontend/src/assets/masthead-shoe.png`

HIS ART, NOT A PLACEHOLDER (2026-08-21): the winged shoe alone on a
transparent ground with its pale glow baked in, cut from the same master
set as the favicon. Sits left of the wordmark on the landing and welcome
mastheads at the letters' own height (`.masthead-shoe`, 1.5rem). Stored at
128 px from his 512 px original. Not part of the commission.
