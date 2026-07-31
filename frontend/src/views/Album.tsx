import { useEffect, useState } from 'react'
import { ApiError, getAlbum, type AlbumSet } from '../api.ts'
import CardPlate from './CardPlate.tsx'

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Something went wrong. Try again.'
}

export default function Album() {
  const [sets, setSets] = useState<AlbumSet[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    getAlbum()
      .then((album) => setSets(album.sets))
      .catch((err: unknown) => setLoadError(errorText(err)))
      .finally(() => setLoading(false))
  }, [])

  return (
    <>
      <section className="card">
        <h2>The album</h2>
        <p className="hint">
          Cards come out of chests, and chests come from Miles covered. Nothing else mints one,
          so the album ends up being a record of how far you have gone.
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
