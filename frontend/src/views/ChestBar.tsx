import { fillClass } from '../format.ts'
import { chestName, chestTierRarity, chestTierWord } from '../labels.ts'
import type { ChestBarState } from '../profile.ts'
import Icon from './Icon.tsx'

// Whoever is waiting, and what they are waiting for. Oil on a step that is
// already as rich as a chest gets has nowhere to go, so it holds rather than
// being spent, and this is the only place that is ever said. One name and two
// are read out; more than two is a count, because a caption is one line and a
// list of usernames is not.
function waitingLine(bar: ChestBarState): string {
  const givers = bar.waiting
  const held =
    givers.length === 1
      ? `${givers[0]}'s gift is waiting for a later chest.`
      : givers.length === 2
        ? `Gifts from ${givers[0]} and ${givers[1]} are waiting for later chests.`
        : `${givers.length} gifts are waiting for later chests.`
  // Only said where it is known to be true. An Ultra floors at the top rarity,
  // so there is no step above it for a gift to lift the chest onto.
  return bar.nextIsTop ? `${held} An Ultra chest already opens at the top.` : held
}

interface Props {
  bar: ChestBarState
}

// The whole cycle of five chests as one bar: a marker per step in the colour of
// what that step is worth, the walker's miles filling the rail up to wherever
// they have got, and the step a friend's oil is waiting on marked as double.
// Each step says which of three things it is by its state class: a chest opened
// this cycle is crossed out, the one being walked is lit, the rest are dimmed.
// It lives on this screen rather than in the side rail because the rail is a
// desktop thing and this is the screen a phone can reach.
export default function ChestBar({ bar }: Props) {
  return (
    <div className="chest-bar">
      <ol className="chest-track" aria-label="The chest ladder">
        {bar.steps.map((step) => (
          <li
            key={step.tier}
            className={`chest-step chest-step-${chestTierRarity(step.tier)} chest-step-${step.state}`}
            aria-current={step.state === 'next' ? 'step' : undefined}
          >
            <span className="chest-lane">
              <span className="chest-rail">
                <span className={`chest-rail-fill ${fillClass(step.fill)}`} />
              </span>
              <span className="chest-mark">
                <Icon name="chest" />
                {step.giftedBy !== null && <span className="chest-gift">2x</span>}
              </span>
            </span>
            <span className="chest-step-label">{chestTierWord(step.tier)}</span>
          </li>
        ))}
      </ol>

      {bar.away !== '' && <p className="hint chest-away">{bar.away}</p>}

      {/* Two things a gift can be doing, and both can be true at once with two
          givers: the one landing on the chest coming is named on it, and
          anything with no step to land on says that it is waiting. */}
      {bar.steps.map((step) =>
        step.giftedBy === null ? null : (
          <p key={step.tier} className="hint chest-gifted">
            Your {chestName(step.tier)} opens a step rarer, gifted by {step.giftedBy}.
          </p>
        ),
      )}

      {bar.waiting.length > 0 && <p className="hint chest-waiting">{waitingLine(bar)}</p>}
    </div>
  )
}
