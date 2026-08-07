import { iconArt } from '../art.ts'

interface Props {
  // The file name under src/assets/icons, without the extension.
  name: string
}

// One interface icon, drawn inline from its own file. The markup is part of the
// build, never fetched, so nothing here reaches the network; inlining it is what
// lets the icon take the colour of whatever holds it and lets a diamond be
// hollowed by a CSS rule. Icons carry no meaning a label does not already
// carry, so they are hidden from screen readers.
export default function Icon({ name }: Props) {
  const markup = iconArt(name)
  if (!markup) return <span className="icon" aria-hidden="true" />
  return (
    <span className="icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: markup }} />
  )
}
