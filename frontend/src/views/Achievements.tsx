import type { Achievement } from '../api.ts'
import { formatDate } from '../format.ts'
import Badge from './Badge.tsx'

interface Props {
  achievements: Achievement[]
}

// The whole catalogue in its own order, earned and unearned together. Unlike a
// card, an achievement is a target to aim at rather than a surprise, so nothing
// here is hidden until it is won.
export default function Achievements({ achievements }: Props) {
  const earned = achievements.filter((row) => row.earned).length

  return (
    <section className="card" id="achievements">
      <div className="set-head">
        <h2>Achievements</h2>
        <span className="muted">
          {earned} of {achievements.length}
        </span>
      </div>
      <p className="hint">
        Weekly badges have a gilded version, earned by doubling the target in the same week.
      </p>

      <ul className="achievements">
        {achievements.map((row) => (
          <li
            key={row.id}
            className={row.earned ? 'achievement' : 'achievement achievement-locked'}
          >
            <Badge achievement={row} />
            <div className="achievement-body">
              <p className="achievement-name">
                {row.name}
                {row.gilded && <span className="tag tag-gilded">Gilded</span>}
              </p>
              <p className="achievement-detail">{row.detail}</p>
              <p className="muted">
                {row.earned
                  ? row.earned_at
                    ? `Earned ${formatDate(row.earned_at)}`
                    : 'Earned'
                  : 'Not earned yet'}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
