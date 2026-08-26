import { groveArt, groveArtCustom, petSleepArt, petSleepArtCustom } from '../art.ts'

interface Props {
  species: string
  // What it is called on screen, which is its name or its species word.
  name: string
  // 1 young, 2 half grown, 3 grown.
  stage: number
  // Whether the clock says it is sleeping. The drawing is the whole of what
  // this changes: nothing is stored, nothing is owed, and a pat still lands.
  sleeping?: boolean
  className?: string
}

// One animal, drawn at the stage it has reached. The files sit with the plants
// and are read the same way, so `pet-bat-s1.png` is found by name and a species
// with no drawing yet costs a picture rather than the card.
export default function PetArt({ species, name, stage, sleeping, className }: Props) {
  // The sleeping set arrives after this, so a species without one is drawn at
  // the stage it stands at instead. A missing picture never leaves a hole here.
  const dozing = sleeping === true ? petSleepArt(species) : null
  const art = dozing ?? groveArt(`pet-${species}`, stage)
  // The committed set is pixel art and is scaled up square-edged; a painting in
  // the custom layer keeps smooth scaling, as the plants' own do.
  const custom =
    dozing !== null ? petSleepArtCustom(species) : groveArtCustom(`pet-${species}`, stage)
  const pixel = art !== null && !custom

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
