import { useEffect, useState } from 'react'
import { ApiError, openChest, type JourneyEvent, type OpenedChest } from '../api.ts'
import { ACTIVITY_NAMES } from '../labels.ts'
import CardPlate from './CardPlate.tsx'

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Something went wrong. Try again.'
}

function miles(value: number | undefined): string {
  return (value ?? 0).toFixed(1)
}

interface Line {
  title: string
  detail: string
  tag: string
}

// Deliberately plain sentences. The recap is a record of what your body did
// while the app was shut, and it reads better as a log than as an announcement.
function describe(event: JourneyEvent): Line {
  const data = event.data
  const activity = data.activity ? ACTIVITY_NAMES[data.activity].toLowerCase() : 'workout'
  switch (event.type) {
    case 'travel':
      return data.local
        ? {
            title: `${miles(data.miles)} Miles around ${data.location_name ?? 'home'}`,
            detail: `From a ${activity}, with no destination set.`,
            tag: 'Travel',
          }
        : {
            title: `${miles(data.miles)} Miles along the ${data.road_name ?? 'road'}`,
            detail: `From a ${activity}, heading for ${data.toward_name ?? 'the next place'}.`,
            tag: 'Travel',
          }
    case 'arrival':
      return {
        title: `Arrived at ${data.location_name ?? 'a new place'}`,
        detail: data.was_destination
          ? 'The place you set out for. Choose the next one on the map.'
          : 'Passing through.',
        tag: 'Arrival',
      }
    case 'milestone':
      return {
        title: data.name ?? 'A milestone',
        detail: data.detail ?? '',
        tag: 'Accolade',
      }
    case 'chest':
      return {
        title: `A chest near ${data.area_name ?? 'the road'}`,
        detail: `${data.set_name ?? 'A'} set.`,
        tag: 'Chest',
      }
    case 'unlock':
      return {
        title: `${data.region_name ?? 'A region'} is open`,
        detail: data.detail ?? '',
        tag: 'Region',
      }
  }
}

interface Props {
  events: JourneyEvent[]
  // The parent acks the recap and reloads whatever the opened chests changed.
  onDismiss: () => void
}

export default function Recap({ events, onDismiss }: Props) {
  const [opened, setOpened] = useState<Record<number, OpenedChest>>({})
  const [busy, setBusy] = useState<number | null>(null)
  const [errors, setErrors] = useState<Record<number, string>>({})

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onDismiss()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onDismiss])

  async function open(chestId: number) {
    setBusy(chestId)
    try {
      const result = await openChest(chestId)
      setOpened((current) => ({ ...current, [chestId]: result }))
      setErrors((current) => ({ ...current, [chestId]: '' }))
    } catch (err) {
      setErrors((current) => ({ ...current, [chestId]: errorText(err) }))
    } finally {
      setBusy(null)
    }
  }

  const chests = events.filter((event) => event.type === 'chest').length

  return (
    <div className="overlay">
      <section className="overlay-panel" role="dialog" aria-modal="true" aria-labelledby="recap-title">
        <header className="overlay-head">
          <h2 id="recap-title">While you were away</h2>
          <p className="hint">
            {events.length} {events.length === 1 ? 'entry' : 'entries'}
            {chests > 0 && `, ${chests} ${chests === 1 ? 'chest' : 'chests'}`}. Chests keep. You
            can open them here or later on the map.
          </p>
        </header>

        <ol className="recap">
          {events.map((event) => {
            const line = describe(event)
            const chestId = event.data.chest_id
            const reveal = chestId === undefined ? undefined : opened[chestId]
            return (
              <li key={event.id} className="recap-item">
                <span className={`tag tag-${event.type}`}>{line.tag}</span>
                <div className="recap-body">
                  <p className="recap-title">{line.title}</p>
                  {line.detail && <p className="recap-detail">{line.detail}</p>}

                  {chestId !== undefined && !reveal && (
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy === chestId}
                      onClick={() => void open(chestId)}
                    >
                      Open the chest
                    </button>
                  )}
                  {chestId !== undefined && errors[chestId] && (
                    <p className="error" role="alert">
                      {errors[chestId]}
                    </p>
                  )}
                  {reveal && (
                    <div className="reveal">
                      <CardPlate
                        number={reveal.card.number}
                        rarity={reveal.card.rarity}
                        owned
                        cardId={reveal.card.id}
                        name={reveal.card.name}
                        flavor={reveal.card.flavor}
                        count={reveal.count}
                      />
                      <p className="hint">
                        {reveal.card.set_name} set.{' '}
                        {reveal.duplicate
                          ? `You already had this one. ${reveal.count} copies now.`
                          : 'New to the album.'}
                      </p>
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ol>

        <footer className="overlay-foot">
          <button type="button" className="primary" onClick={onDismiss}>
            Done
          </button>
        </footer>
      </section>
    </div>
  )
}
