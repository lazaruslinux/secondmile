import type { ItemTallies as Tallies } from '../api.ts'

// A number the grid is willing to print, which is a whole finite one and
// nothing else. Anything else reads as nought rather than as NaN, the way every
// figure crossing the friend seam does.
function count(value: number | undefined): number {
  return typeof value === 'number' && isFinite(value) ? Math.max(0, Math.round(value)) : 0
}

interface Props {
  tallies: Tallies | undefined
}

// What has been given away and what has arrived, on the You screen and on a
// friend's profile both. Two items and two directions: water poured and potions
// spent on the left, the same two coming the other way on the right.
//
// Counts and nothing else. There are no names here and no dates, so the grid
// says how much giving an account has done without saying who it was done with,
// and a gift still on its way is not in it: a potion is counted once it has
// landed. The kind is still 'oil' under the screen.
export default function ItemTallies({ tallies }: Props) {
  const oil = tallies?.oil
  const water = tallies?.water
  return (
    <table className="stats">
      <thead>
        <tr>
          <th scope="col">Item</th>
          <th scope="col">Used</th>
          <th scope="col">Received</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <th scope="row">Boost potion</th>
          <td>{count(oil?.used)}</td>
          <td>{count(oil?.received)}</td>
        </tr>
        <tr>
          <th scope="row">Water</th>
          <td>{count(water?.used)}</td>
          <td>{count(water?.received)}</td>
        </tr>
      </tbody>
    </table>
  )
}
