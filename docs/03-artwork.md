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

## Avatar borders

`frontend/src/assets/borders/border-t1.svg` through `border-t6.svg`

The frame around the profile picture. Six files, one per tier, and the profile
draws the highest tier the player's level has reached:

| File | Earned at level |
| --- | --- |
| `border-t1.svg` | 1 |
| `border-t2.svg` | 5 |
| `border-t3.svg` | 10 |
| `border-t4.svg` | 20 |
| `border-t5.svg` | 35 |
| `border-t6.svg` | 50 |

Each file needs a `viewBox` and nothing else: no ids, no particular size. The
border is drawn over a square avatar and scaled to it, so **the picture sits
inside the middle of the viewBox**. Leave the centre empty or the frame will
cover somebody's face. A border that grows outward rather than inward is the
safe way to make a higher tier feel more substantial.

The levels are defined in `backend/app/config.py` as `BORDER_LEVELS`, and the
number of files has to match the length of that list.

## Badges

`frontend/src/assets/badges/<achievement-id>.svg`

Drop a file in named after an achievement id and it becomes that achievement's
badge. There is no list to edit and no import to add. An achievement with no
file of its own falls back to a generic badge for its kind:

`frontend/src/assets/badges/kind-duration-single.svg`,
`kind-week-distance.svg`, `kind-lifetime-distance.svg`, `kind-firsts.svg`,
`kind-collection.svg`

The achievement ids are in `backend/app/achievements.py`, in the catalogue near
the top of the file. They read like `week_10`, `lifetime_250`, `first_swim`,
and `collection_set_hedgerow`, so the file for the first of those is
`week_10.svg`.

Badges are drawn small: in the slots around the avatar they are roughly 48
pixels across, and in the achievements list roughly 64. Anything that depends
on fine detail will not read at that size.

### The gilded variant

Weekly achievements have a second, finer version earned by doubling the target
inside the same week. Name it after the achievement with `-gilded` on the end:

`frontend/src/assets/badges/week_10-gilded.svg`

If there is no gilded file, the app draws the ordinary badge with a gilded
treatment of its own. Providing the file is how you make the difference
unmistakable, which is the point of the mechanic: it is meant to be visibly
finer than the badge everybody else has.

## Card illustrations

`frontend/src/assets/cards/<card-id>.png`

Drop an image in named after the card id and it appears on that card's plate at
the next build. `.png`, `.webp`, and `.svg` all work. A card with no file gets a
plain plate with a blank slot, which is what the whole album looks like now.

The card ids are in `backend/app/world.py`, in the catalogue that makes up most
of the file. They are always the set id followed by the card's own name, so
they read like `hedgerow_hawthorn`, `still_water_kingfisher`, and
`open_hill_raven`, and the file for the first of those is
`hedgerow_hawthorn.png`.

The four sets and their sizes:

| Set id | Name | Plates |
| --- | --- | --- |
| `hedgerow` | The Hedgerow | 12 |
| `still_water` | Still Water | 10 |
| `open_hill` | The Open Hill | 8 |
| `first_light` | First Light | 6 |

Plates draw the illustration in a 4 by 3 slot and crop to fill, so images
around 800 by 600 are a good fit. Album plates are shown at roughly 150 pixels
wide, so nothing enormous is needed.

## Profile pictures

Not artwork, and not replaceable here: each player uploads their own. The
server re-encodes every upload to a 512 by 512 webp and stores it outside the
frontend build, so nothing in `assets` affects it.

## What is not a file yet

The interface itself, the buttons, the colours, the type, is plain CSS in
`frontend/src/styles.css`, not artwork. The one accent colour is defined once
at the top of that file.
