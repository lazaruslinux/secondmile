# Replacing the artwork

Every picture in secondmile is a file you can open in a vector editor or an
image editor. The application shipped with placeholder art on purpose, and
replacing it does not require touching any code.

The rule the code follows: it reads the asset files as they are and looks only
for the element ids listed below. Everything else about a file, its shapes,
colours, labels, layers, and size, is yours.

Files live under `frontend/src/assets`. After changing any of them, rebuild the
frontend:

```
docker compose up -d --build frontend
```

## The map

`frontend/src/assets/vale-map.svg`

The placeholder is drawn on a `viewBox` of `0 0 1200 800`. A replacement can
declare any `viewBox` it likes, but it has to declare one: the app reads it to
set up panning and zooming, and shows a plain message instead of the map if the
file has no `viewBox` or is not valid XML.

Ids the code depends on:

| Id | What it must be | What the code does with it |
| --- | --- | --- |
| `road-east_road` | One `<path>` from Homestead to Millbrook | Places the marker along it |
| `road-north_road` | One `<path>` from Millbrook to Fells Gate | Places the marker along it |
| `road-fell_road` | One `<path>` from Fells Gate to The Shieling | Places the marker along it |
| `loc-homestead` | Any one element | The centre of its bounding box is the place |
| `loc-millbrook` | Any one element | The centre of its bounding box is the place |
| `loc-fells_gate` | Any one element | The centre of its bounding box is the place |
| `loc-shieling` | Any one element | The centre of its bounding box is the place |
| `gate-high_fells` | Any one element or group | Hidden once the region is open |
| `lake` | Any one element | Nothing. Kept so it stays easy to find |

Three things to know about the roads:

- **Direction matters.** The marker is placed at a fraction of the path's
  length, measured from the start of the path, and the server measures from the
  first place named in the table. A path drawn in the other direction puts the
  marker at the wrong end of the road.
- **Length is spread evenly.** Ten miles of road are ten equal tenths of the
  drawn path, so a path that doubles back on itself makes the marker move
  slowly through the loop. Curves are fine, detours are a design decision.
- **One element per road.** If you want a casing under a road, draw a second
  path without the id. Only the element carrying the id is measured.

The place ids are the same strings the server uses, so they cannot be renamed
here alone. They are defined in `backend/app/world.py` along with the roads,
their lengths, and which region gates them; adding a place to the map means
adding it there too.

Two constraints on the file itself:

- **Presentation attributes, not styles.** Use `fill="#..."` and
  `stroke="#..."` rather than `style="fill:#..."` or a `<style>` block. The
  application's content security policy does not allow inline styles, so
  anything styled that way is drawn without its styling. Editors that write
  style attributes by default usually have a setting to switch this.
- **Nothing loaded from elsewhere.** No external images, no fonts, no scripts.
  The app loads nothing from outside its own origin. Embed anything you need,
  and use generic font families for text.

## The marker

`frontend/src/assets/marker.svg`

The mark that shows where the player is. It needs a `viewBox` and nothing else:
no ids, no particular size. The **centre of the viewBox** is the point that sits
on the road, so draw the mark around the middle of the canvas rather than
around the tip of a pin.

The app scales the file to about five percent of the map's width and keeps it
that size on screen as the map is zoomed.

## Card illustrations

`frontend/src/assets/cards/<card-id>.png`

Drop an image in named after the card id and it appears on that card's plate at
the next build. `.png`, `.webp`, and `.svg` all work. Nothing else has to
change: there is no list to edit and no import to add. A card with no file gets
a plain plate with a blank slot, which is what the whole album looks like now.

The card ids are in `backend/app/world.py`, in the card catalogue near the
bottom of the file. They read like `east_road_hawthorn`, so the file for that
card is `east_road_hawthorn.png`.

Plates draw the illustration in a 4 by 3 slot and crop to fill, so images
around 800 by 600 are a good fit. Album plates are shown at roughly 150 pixels
wide, so nothing enormous is needed.

## What is not a file yet

The interface itself, the buttons, the colours, the type, is plain CSS in
`frontend/src/styles.css`, not artwork. The one accent colour is defined once
at the top of that file.
