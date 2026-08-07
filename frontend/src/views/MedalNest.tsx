import type { ReactNode } from 'react'

// The medals nestled under a picture: overlapping circles centred on the bottom
// edge of the avatar frame, half of each hanging off it, the ends of the row
// sitting a little higher than the middle. Whoever holds the data draws each
// medal; this only decides where they sit, and the count is what the stylesheet
// reads to keep the row centred.
interface Props {
  // One node per position, at most four. The You screen sends four whether they
  // are filled or not, since an empty slot there is the invitation to fill it.
  items: ReactNode[]
}

export default function MedalNest({ items }: Props) {
  if (items.length === 0) return null
  const shown = items.slice(0, 4)

  return (
    <ul className={`medal-nest medal-nest-${shown.length}`}>
      {shown.map((item, index) => (
        // Position is the only identity a slot has: the same slot holds a
        // different medal from one render to the next.
        <li key={index} className="medal-nest-item">
          {item}
        </li>
      ))}
    </ul>
  )
}
