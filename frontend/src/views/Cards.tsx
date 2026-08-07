import { useEffect, useState } from 'react'
import { errorText, getAlbum, type AlbumSet } from '../api.ts'
import CardPlate from './CardPlate.tsx'

// What this tab last showed, kept by account so a second person signing in on
// the same browser never sees the first one's cards. It lives as long as the
// page does and no longer.
const cache = new Map<number, AlbumSet[]>()

interface Props {
  userId: number
}

export default function Cards({ userId }: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [sets, setSets] = useState<AlbumSet[]>(() => cache.get(userId) ?? [])
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    getAlbum()
      .then((album) => {
        cache.set(userId, album.sets)
        setSets(album.sets)
      })
      .catch((err: unknown) => setLoadError(errorText(err)))
      .finally(() => setLoading(false))
  }, [userId])

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">Cards</h1>
      </div>

      <section className="card">
        <p className="hint">
          Cards come out of chests, and chests come from the miles you cover. Nothing else
          makes one, so this ends up being a record of how far you have gone.
        </p>
      </section>

      {loading && <p className="notice">Loading.</p>}
      {loadError && (
        <p className="error" role="alert">
          {loadError}
        </p>
      )}

      {sets.map((set) => (
        <section key={set.id}>
          <div className="set-head">
            <h2>{set.name}</h2>
            <span className="muted">
              {set.owned} of {set.size}
            </span>
          </div>
          <div className="plates">
            {set.cards.map((plate) => (
              <CardPlate
                key={`${set.id}-${plate.number}`}
                number={plate.number}
                rarity={plate.rarity}
                owned={plate.owned}
                cardId={plate.id}
                name={plate.name}
                flavor={plate.flavor}
                count={plate.count}
              />
            ))}
          </div>
        </section>
      ))}
    </>
  )
}
