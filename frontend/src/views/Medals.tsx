import type { Medal } from '../api.ts'
import { medalArt } from '../art.ts'
import {
  MEDAL_FAMILY_NAMES,
  MEDAL_ORDER,
  medalName,
  medalsByFamily,
} from '../labels.ts'
import { EARNS_PER_STAR, MAX_STARS, medalCountsOf, starsFor } from '../profile.ts'

// The word the interface uses for these, in one place. Everything underneath it
// (ids, files, classes) is named badge; only what a person reads says medal.
const SECTION_TITLE = 'Medals'

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
  const art = medalArt(id)
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

interface Props {
  medals: Medal[] | undefined
}

// The whole catalogue, in families, earned and unearned together. A medal is a
// thing to aim at as much as a thing won, so nothing here is hidden until it
// arrives: one not yet earned is the same drawing gone quiet with a nought
// under it.
export default function Medals({ medals }: Props) {
  const counts = medalCountsOf(medals)
  const earned = MEDAL_ORDER.filter((id) => (counts.get(id) ?? 0) > 0).length

  return (
    <section className="card" id="medals">
      <div className="set-head">
        <h2>{SECTION_TITLE}</h2>
        <span className="muted">
          {earned} of {MEDAL_ORDER.length}
        </span>
      </div>
      <p className="hint">
        They repeat: every time you earn one again it counts again. Every {EARNS_PER_STAR} of
        the same medal adds a star around it, up to {MAX_STARS}.
      </p>

      {medalsByFamily().map((group) => (
        <div key={group.family} className="medal-group">
          <h3 className="label">{MEDAL_FAMILY_NAMES[group.family]}</h3>
          {/* The count sits under its own medal, and one never earned keeps a
              nought rather than a gap, so the columns stay level across the
              families. */}
          <ul className="medal-strip">
            {group.ids.map((id) => {
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
        </div>
      ))}
    </section>
  )
}
