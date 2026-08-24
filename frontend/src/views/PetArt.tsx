import { groveArt, groveArtCustom } from '../art.ts'

interface Props {
  species: string
  // What it is called on screen, which is its name or its species word.
  name: string
  // 1 young, 2 half grown, 3 grown.
  stage: number
  className?: string
}

// One animal, drawn at the stage it has reached. The files sit with the plants
// and are read the same way, so `pet-bat-s1.png` is found by name and a species
// with no drawing yet costs a picture rather than the card.
export default function PetArt({ species, name, stage, className }: Props) {
  const art = groveArt(`pet-${species}`, stage)
  // The committed set is pixel art and is scaled up square-edged; a painting in
  // the custom layer keeps smooth scaling, as the plants' own do.
  const pixel = art !== null && !groveArtCustom(`pet-${species}`, stage)

  return (
    <span className={className ? `plant-art ${className}` : 'plant-art'} title={name}>
      {art ? (
        <img className={pixel ? 'pixel' : undefined} src={art} alt={name} />
      ) : (
        <span className="plant-blank" aria-hidden="true" />
      )}
    </span>
  )
}
