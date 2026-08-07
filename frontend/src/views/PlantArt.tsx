import { groveArt } from '../art.ts'
import { speciesName } from '../labels.ts'

interface Props {
  species: string
  // What the server calls it. Left out where only the id is to hand.
  name?: string | null
  // 1 seedling, 2 growing, 3 grown.
  stage: number
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
  className,
  labelled = false,
}: Props) {
  const art = groveArt(species, stage)
  const name = speciesName(species, given)

  return (
    <span className={className ? `plant-art ${className}` : 'plant-art'} title={name}>
      {art ? (
        <img src={art} alt={labelled ? name : ''} />
      ) : (
        <span className="plant-blank" aria-hidden="true" />
      )}
    </span>
  )
}
