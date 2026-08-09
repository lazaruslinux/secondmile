import { MedalMark } from './Medals.tsx'

// How many medals fit under a picture. The server holds the same number.
export const MAX_MEDAL_SLOTS = 3

interface Props {
  // The medals to draw, as ids, in the order they were chosen. Every screen
  // hands this the same field of the same profile, which is what keeps the
  // summary card on Home and the banner on You showing the same three.
  ids: string[]
  // Draw this many positions whether they are filled or not. The You screen
  // asks for all three, because an empty slot there is the invitation to fill
  // it; everywhere else the nest is only what is in it.
  slots?: number
}

// The medals nestled under a picture: overlapping circles centred on the bottom
// edge of the avatar frame, half of each hanging off it, the ends of the row
// sitting a little higher than the middle. Three of them rather than four, so
// each is drawn larger than it was: the arc is the same width and the medal
// inside it is easier to tell apart. The stars a medal has earned are
// deliberately not drawn here: at this size the ring of marks is smaller than a
// pixel apiece and the medals overlap each other besides, so the stars are left
// to the strip on You and the rail on Home where they can be read.
export default function MedalNest({ ids, slots = 0 }: Props) {
  const shown = ids.slice(0, MAX_MEDAL_SLOTS)
  const positions = Math.max(shown.length, Math.min(slots, MAX_MEDAL_SLOTS))
  if (positions === 0) return null

  return (
    <ul className={`medal-nest medal-nest-${positions}`}>
      {Array.from({ length: positions }, (_ignored, index) => {
        const id = shown[index]
        return (
          // Position is the only identity a slot has: the same slot holds a
          // different medal from one render to the next.
          <li key={index} className="medal-nest-item">
            {id ? (
              <MedalMark id={id} earned standalone />
            ) : (
              <span className="badge badge-empty" aria-hidden="true" />
            )}
          </li>
        )
      })}
    </ul>
  )
}
