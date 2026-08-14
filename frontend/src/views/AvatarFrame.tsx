import type { ReactNode } from 'react'
import { borderArt, flourishArt } from '../art.ts'
import { useTheme } from '../theme.ts'

interface Props {
  // What to call this person on screen: the name they gave if they gave one.
  // Used for the letter that stands in for a missing picture and for the
  // picture's own description, nothing else.
  name: string
  // The picture, or null when there is none and the first letter stands in.
  src: string | null
  borderTier: number
  // How far the border's growth has come, 0 to 3. Nothing is drawn at 0.
  flourish?: number
  // Extra class for the screens that size the frame themselves.
  frameClass?: string
  // True where the picture is the only thing naming the person on screen.
  labelled?: boolean
  // The medal nest, on the screens that have one.
  children?: ReactNode
}

// A profile picture in its level border, with whatever growth has wrapped that
// border drawn over it. Every screen that shows somebody's face uses this, so
// the frame is the same thing in the feed, the friends list, and on You.
export default function AvatarFrame({
  name,
  src,
  borderTier,
  flourish = 0,
  frameClass,
  labelled = false,
  children,
}: Props) {
  // The frame stands on the page rather than in a well, so it is drawn from the
  // twin that suits the ground and redrawn when the ground changes.
  const theme = useTheme()
  const border = borderArt(borderTier, theme)
  const growth = flourishArt(flourish, theme)

  return (
    <div className={frameClass ? `avatar-frame ${frameClass}` : 'avatar-frame'}>
      {src ? (
        <img
          className="avatar-shot"
          src={src}
          alt={labelled ? `${name}'s picture` : ''}
        />
      ) : (
        <span className="avatar-shot avatar-empty" aria-hidden="true">
          {name.slice(0, 1).toUpperCase()}
        </span>
      )}
      {border && <img className="avatar-border" src={border} alt="" />}
      {/* Growth earned by encouraging other people. It lies over the border
          rather than replacing it: the level is still readable underneath. */}
      {growth && <img className="avatar-flourish" src={growth} alt="" />}
      {children}
    </div>
  )
}
