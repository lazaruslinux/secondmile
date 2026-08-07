import { badgeArt } from '../art.ts'
import type { Achievement } from '../api.ts'

interface Props {
  achievement: Achievement
  // True where the badge stands on its own, as it does in the nest under the
  // avatar, and the picture has to carry its own name.
  standalone?: boolean
}

// One badge, used in the nest under the avatar, in the achievements list, in
// the picker, and in the recap. A badge with no artwork of its own falls back
// to the generic one for its kind, and a gilded badge with no gilded artwork
// gets a gilded treatment here instead, so going the second mile always shows.
export default function Badge({ achievement, standalone = false }: Props) {
  const art = badgeArt(achievement.id, achievement.kind, achievement.gilded)
  const classes = ['badge']
  if (!achievement.earned) classes.push('badge-locked')
  if (achievement.gilded && !art.gildedArt) classes.push('badge-gilded')

  return (
    <span className={classes.join(' ')} title={achievement.name}>
      {art.url ? (
        <img src={art.url} alt={standalone ? achievement.name : ''} />
      ) : (
        <span className="badge-blank" aria-hidden="true" />
      )}
    </span>
  )
}
