import { gildArt, groveArt, groveArtCustom } from '../art.ts'
import { speciesName } from '../labels.ts'

interface Props {
  species: string
  // What the server calls it. Left out where only the id is to hand.
  name?: string | null
  // 1 seedling, 2 growing, 3 grown.
  stage: number
  // Fully grown: the shared gild is laid over the picture.
  gilded?: boolean
  // Extra class for the places that size the picture themselves.
  className?: string
  // True where the picture stands on its own and has to carry its own name.
  labelled?: boolean
}

// One plant, drawn at the stage it has reached. Every screen that shows
// something growing uses this, so the plot, the band on You, and a chest reveal
// all draw the same file.
export default function PlantArt({
  species,
  name: given,
  stage,
  gilded = false,
  className,
  labelled = false,
}: Props) {
  const art = groveArt(species, stage)
  // The committed set is pixel art and is scaled up square-edged. The owner's
  // own paintings are not pixel art and keep smooth scaling.
  const pixel = art !== null && !groveArtCustom(species, stage)
  const name = speciesName(species, given)
  // One placeholder file for every species. Real gilded artwork per species is
  // a later pass, and this comes off when it lands.
  const gild = gilded ? gildArt() : null

  return (
    <span className={className ? `plant-art ${className}` : 'plant-art'} title={name}>
      {art ? (
        <img className={pixel ? 'pixel' : undefined} src={art} alt={labelled ? name : ''} />
      ) : (
        <span className="plant-blank" aria-hidden="true" />
      )}
      {gild && <img className="plant-gild" src={gild} alt="" aria-hidden="true" />}
    </span>
  )
}
