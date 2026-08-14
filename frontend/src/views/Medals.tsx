import { useState } from 'react'

import type { Medal } from '../api.ts'
import { medalArt } from '../art.ts'
import { MEDAL_ORDER, medalName } from '../labels.ts'
import { EARNS_PER_STAR, MAX_STARS, medalCountsOf, starsFor } from '../profile.ts'
import { useTheme } from '../theme.ts'

// The word the interface uses for these, in one place. Everything underneath it
// (ids, files, classes) is named badge; only what a person reads says medal.
const SECTION_TITLE = 'Medals'

// Whether this browser was last left hiding the ones still to come. Kept
// between visits like the Activity tab's view is, and off until it is asked
// for: a medal is a thing to aim at as much as a thing won, so the catalogue
// opens showing all of them.
const UNEARNED_KEY = 'secondmile.medals.unearned'

function rememberedHiding(): boolean {
  try {
    return localStorage.getItem(UNEARNED_KEY) === 'hide'
  } catch {
    // A browser with storage turned off simply opens on the whole catalogue.
    return false
  }
}

function rememberHiding(hiding: boolean): void {
  try {
    localStorage.setItem(UNEARNED_KEY, hiding ? 'hide' : 'show')
  } catch {
    // Nothing to say: the choice holds for this visit and is forgotten after.
  }
}

// Where the stars sit, in the 64 unit box every medal is drawn in. The ring is
// outside the artwork's own rim: the places that can show stars inset the
// drawing by the width of the ring, so the stars circle the medal rather than
// lie on it, and a row of medals stays one size whether it has any yet or not.
const STAR_RING = 30
const STAR_SIZE = 1.8

// The stars circling a medal, drawn as one overlay rather than as a file each.
// They are evenly spaced around the rim whatever their number, the first
// straight up and the rest clockwise from it, so two stars are opposite each
// other and thirty three are a ring. Nothing is drawn at nought.
function MedalStars({ stars }: { stars: number }) {
  if (stars <= 0) return null
  const marks = []
  for (let index = 0; index < stars; index += 1) {
    // Straight up is minus ninety degrees in a box whose y grows downward.
    const angle = ((-90 + (index * 360) / stars) * Math.PI) / 180
    marks.push(
      <circle
        key={index}
        cx={Number((32 + STAR_RING * Math.cos(angle)).toFixed(2))}
        cy={Number((32 + STAR_RING * Math.sin(angle)).toFixed(2))}
        r={STAR_SIZE}
      />,
    )
  }

  return (
    <svg
      className="medal-stars"
      viewBox="0 0 64 64"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      {marks}
    </svg>
  )
}

interface MarkProps {
  id: string
  earned: boolean
  // How many stars circle it, worked out from the count by the caller that
  // holds it. Left at nought where the medal is drawn too small for them to
  // read, which is the nest under the avatar and the picker.
  stars?: number
  // True where the medal stands on its own and the picture has to carry its
  // own name.
  standalone?: boolean
}

// One medal picture. Used in the strip on You, in the nest under the avatar, in
// the rail on Home, in the picker, and in the recap, so all five show the same
// drawing from the same file.
export function MedalMark({ id, earned, stars = 0, standalone = false }: MarkProps) {
  // Every medal is drawn twice, once per ground: the picker, the strip and the
  // chips all sit on the page rather than in a well, so the mark follows the
  // theme wherever it is used, including inside the nest under an avatar.
  const theme = useTheme()
  const art = medalArt(id, theme)
  const name = medalName(id)
  const classes = ['badge']
  if (!earned) classes.push('badge-locked')

  return (
    <span className={classes.join(' ')} title={name}>
      {art ? (
        <img src={art} alt={standalone ? name : ''} />
      ) : (
        <span className="badge-blank" aria-hidden="true" />
      )}
      <MedalStars stars={stars} />
    </span>
  )
}

// One medal on a workout, in the strip along the bottom of a feed card and in
// an Activity row. The drawing carries it and the name sits beside it: the five race
// medals are one silver plate apart from the word stamped on it, and at this
// size that word is a few pixels tall, so MARATHON has to be readable in type
// the interface draws itself.
export function MedalChip({ id }: { id: string }) {
  return (
    <span className="feed-badge">
      <MedalMark id={id} earned />
      <span className="feed-badge-label">{medalName(id)}</span>
    </span>
  )
}

interface Props {
  medals: Medal[] | undefined
}

// The whole catalogue in one list, earned and unearned together, in catalogue
// order. No headings over it: Early Riser and Night Owl are neither a distance
// nor a week, so any word put above them would be the wrong one. A medal is a
// thing to aim at as much as a thing won, so nothing here is hidden until it
// arrives: one not yet earned is the same drawing gone quiet with a nought
// under it, unless this browser has asked for the shelf it has already won.
export default function Medals({ medals }: Props) {
  const counts = medalCountsOf(medals)
  const held = MEDAL_ORDER.filter((id) => (counts.get(id) ?? 0) > 0)
  const [hiding, setHiding] = useState(rememberedHiding)
  const shown = hiding ? held : MEDAL_ORDER

  function chooseHiding(next: boolean) {
    setHiding(next)
    rememberHiding(next)
  }

  return (
    <section className="card" id="medals">
      <div className="set-head">
        <h2>{SECTION_TITLE}</h2>
        <span className="muted">
          {held.length} of {MEDAL_ORDER.length}
        </span>
      </div>
      <p className="hint">
        Medals repeat. Every {EARNS_PER_STAR} of the same one adds a star, up to {MAX_STARS}.
      </p>

      {/* A filter rather than a setting, and the count above it still says how
          many of the whole catalogue are held. */}
      <button
        type="button"
        className={hiding ? 'filter-chip filter-chip-on medal-filter' : 'filter-chip medal-filter'}
        aria-pressed={hiding}
        onClick={() => chooseHiding(!hiding)}
      >
        Hide unearned
      </button>

      {hiding && held.length === 0 && <p className="hint">No medals earned yet.</p>}

      {/* The count sits under its own medal, and one never earned keeps a
          nought rather than a gap, so the columns stay level down the grid. */}
      <ul className="medal-strip">
        {shown.map((id) => {
          const count = counts.get(id) ?? 0
          return (
            <li key={id} className="medal-tile">
              <MedalMark id={id} earned={count > 0} stars={starsFor(count)} />
              <span
                className={count > 0 ? 'medal-tile-count' : 'medal-tile-count medal-tile-none'}
              >
                {count}
              </span>
              <span className="medal-tile-name">{medalName(id)}</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
