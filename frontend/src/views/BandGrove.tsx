import { groundArt } from '../art.ts'
import PlantArt from './PlantArt.tsx'

// One plant as the band draws it. Both plots feed this: the owner's rows and a
// friend's rows carry different fields, and each screen reads its own into this
// shape so the band itself never has to know whose grove it is showing.
export interface BandPlant {
  id: number
  species: string
  name: string
  // 1 seedling, 2 growing, 3 grown.
  stage: number
  mature: boolean
  gilded: boolean
}

// How tall a plant comes out. A grown one gets the taller box, and inside any
// box the stage decides how much of it the drawing fills, so the two together
// are the drawn height in the right order.
function drawnHeight(plant: BandPlant): number {
  return (plant.mature ? 10 : 0) + plant.stage
}

// The order the row is drawn in. Arrival order puts whatever was planted last
// at the end, which is how a seedling ends up dangling off the edge, so the row
// is composed instead: sort tallest first, with species and id breaking ties so
// the same plot always draws the same row, split into a tall half and a short
// half, deal the two alternately, and turn the result round. Tall and short
// then alternate into a skyline with the tallest at the outer edge, and the
// smallest is what the band gives up first when a plot outgrows it.
function skyline(plants: BandPlant[]): BandPlant[] {
  const ranked = [...plants].sort(
    (a, b) =>
      drawnHeight(b) - drawnHeight(a) || a.species.localeCompare(b.species) || a.id - b.id,
  )
  const half = Math.ceil(ranked.length / 2)
  const dealt: BandPlant[] = []
  for (let i = 0; i < half; i += 1) {
    dealt.push(ranked[i])
    const shorter = ranked[half + i]
    if (shorter) dealt.push(shorter)
  }
  return dealt.reverse()
}

// The band across the top of a profile: a strip of soil along its floor with
// the plot standing on it, small and unpressable. The You screen and a friend's
// profile draw the same band, so it is written once.
export default function BandGrove({ plants }: { plants: BandPlant[] }) {
  const row = skyline(plants)
  const ground = groundArt()

  return (
    // An empty plot keeps its soil and gives up its height: bare ground reads
    // as a plot with nothing in it yet, where a band's worth of empty surface
    // reads as something that failed to draw. Nothing is said in here either
    // way; the sentence about an empty grove belongs to the Grove screen.
    <div className={row.length > 0 ? 'you-band' : 'you-band you-band-bare'}>
      {row.length > 0 && (
        <ul className="band-grove">
          {row.map((plant) => (
            <li
              key={plant.id}
              className={plant.mature ? 'band-plant band-plant-grown' : 'band-plant'}
            >
              <PlantArt
                species={plant.species}
                name={plant.name}
                stage={plant.stage}
                gilded={plant.gilded}
              />
            </li>
          ))}
        </ul>
      )}
      {/* After the row rather than before it, so the soil is painted over the
          ground line each drawing carries and the row reads as standing on one
          floor. */}
      {ground && <img className="band-ground" src={ground} alt="" aria-hidden="true" />}
    </div>
  )
}
