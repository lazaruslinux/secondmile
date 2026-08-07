import type { RaceBadge } from '../api.ts'
import { raceBadgeArt } from '../art.ts'
import { RACE_BADGE_ORDER, raceBadgeName } from '../labels.ts'
import { raceCountsOf } from '../profile.ts'

// The word the interface uses for these, in one place. Everything underneath it
// (ids, files, classes) is named badge; only what a person reads says medal.
const SECTION_TITLE = 'Medals'

interface MarkProps {
  id: string
  earned: boolean
  // True where the badge stands on its own, as it does in the slots around the
  // avatar, and the picture has to carry its own name.
  standalone?: boolean
}

// One race badge picture. Used in the strip, in the slots around the avatar, in
// the picker, and in the recap, so all four show the same drawing.
export function RaceBadgeMark({ id, earned, standalone = false }: MarkProps) {
  const art = raceBadgeArt(id)
  const name = raceBadgeName(id)

  return (
    <span className={earned ? 'badge' : 'badge badge-locked'} title={name}>
      {art ? (
        <img src={art} alt={standalone ? name : ''} />
      ) : (
        <span className="badge-blank" aria-hidden="true" />
      )}
    </span>
  )
}

interface Props {
  badges: RaceBadge[] | undefined
}

// The five race distances, shortest first. The ones not yet run are drawn dim
// rather than left out: the ladder ahead is the point of the strip.
export default function RaceBadges({ badges }: Props) {
  const counts = raceCountsOf(badges)
  const earned = RACE_BADGE_ORDER.filter((id) => (counts.get(id) ?? 0) > 0).length

  return (
    <section className="card" id="race-badges">
      <div className="set-head">
        <h2>{SECTION_TITLE}</h2>
        <span className="muted">
          {earned} of {RACE_BADGE_ORDER.length}
        </span>
      </div>
      <p className="hint">
        Earned by one run at or past the distance. They repeat: every run that far earns
        another.
      </p>

      {/* The count sits under its own badge, and a distance never run keeps a
          nought rather than a gap, so the five columns stay level. */}
      <ul className="race-strip">
        {RACE_BADGE_ORDER.map((id) => {
          const count = counts.get(id) ?? 0
          return (
            <li key={id} className="race-item">
              <RaceBadgeMark id={id} earned={count > 0} />
              <span className={count > 0 ? 'race-count' : 'race-count race-count-none'}>
                {count}
              </span>
              <span className="race-name">{raceBadgeName(id)}</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
