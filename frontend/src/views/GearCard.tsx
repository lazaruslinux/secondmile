import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  addGear,
  deleteGear,
  errorText,
  retireGear,
  setDefaultGear,
  unretireGear,
  updateGear,
  type Gear,
  type GearApplies,
  type GearStyle,
} from '../api.ts'
import {
  DEFAULT_WIDTH,
  fitLine,
  GEAR_APPLIES,
  GEAR_STYLES,
  gearName,
  gearSizes,
  gearSubline,
  gearWidths,
  milesLine,
  sizeLabel,
  wearLine,
} from '../gear.ts'
import Confirm from './Confirm.tsx'
import Icon from './Icon.tsx'

// The server's own limits, held to here as well so a box stops taking letters
// where the server would have refused them.
const BRAND_LIMIT = 60
const MODEL_LIMIT = 80
const NICKNAME_LIMIT = 60

// An empty box means the field is being emptied, which the server reads as a
// null rather than as an empty string.
function orNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

// A number typed into an optional box, or null for an empty one. Anything that
// is not a number is left to the server to refuse in its own words.
function orNullNumber(value: string): number | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : Number(trimmed)
}

// The form behind Add and Edit, which is one form: a pair is the same handful
// of fields whether it is being recorded or corrected. Style sits at the top
// because it is what the size and width lists are drawn from, and changing it
// redraws both.
function GearForm({
  pair,
  busy,
  error,
  verbs,
  onSave,
  onClose,
}: {
  // Null while a pair is being recorded for the first time.
  pair: Gear | null
  busy: boolean
  error: string
  // What can be done to the pair itself rather than to its fields. Inside the
  // panel, because the page behind a modal cannot be pressed.
  verbs?: ReactNode
  onSave: (fields: {
    style: GearStyle
    brand: string
    model: string
    nickname: string | null
    size: number
    width: string
    starting_mi: number
    replace_around_mi: number | null
    applies_to: GearApplies
  }) => void
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [style, setStyle] = useState<GearStyle>(pair?.style ?? 'mens')
  const [brand, setBrand] = useState(pair?.brand ?? '')
  const [model, setModel] = useState(pair?.model ?? '')
  const [nickname, setNickname] = useState(pair?.nickname ?? '')
  const [size, setSize] = useState(String(pair?.size ?? 10))
  const [width, setWidth] = useState(pair?.width ?? DEFAULT_WIDTH[pair?.style ?? 'mens'])
  const [startingMi, setStartingMi] = useState(
    pair?.starting_mi ? String(pair.starting_mi) : '',
  )
  const [replaceMi, setReplaceMi] = useState(
    pair?.replace_around_mi ? String(pair.replace_around_mi) : '',
  )
  const [appliesTo, setAppliesTo] = useState<GearApplies>(pair?.applies_to ?? 'both')

  // Opened as a modal rather than with the open attribute, because only the
  // modal form brings the focus trap, the page behind held still, and Esc.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  const sizes = gearSizes(style)
  const widths = gearWidths(style)

  // The two lists are the style's, so a style that moves takes whatever no
  // longer exists on it back to something that does. The server does the same
  // on its side; this is so the form never shows a choice it cannot save.
  function chooseStyle(next: GearStyle) {
    setStyle(next)
    if (!gearSizes(next).some((offered) => String(offered) === size)) {
      setSize(String(gearSizes(next)[0]))
    }
    if (!gearWidths(next).some((offered) => offered.id === width)) {
      setWidth(DEFAULT_WIDTH[next])
    }
  }

  function save(event: FormEvent) {
    event.preventDefault()
    onSave({
      style,
      brand: brand.trim(),
      model: model.trim(),
      nickname: orNull(nickname),
      size: Number(size),
      width,
      starting_mi: Number(orNullNumber(startingMi) ?? 0),
      replace_around_mi: orNullNumber(replaceMi),
      applies_to: appliesTo,
    })
  }

  return (
    <dialog
      className="overlay"
      ref={dialog}
      aria-labelledby="gear-form-title"
      onCancel={(event) => {
        // Esc. Closing is the caller's business, so the browser's own close is
        // left undone and the caller takes this off the screen.
        event.preventDefault()
        onClose()
      }}
    >
      <section className="overlay-panel">
        <header className="overlay-head">
          <h2 id="gear-form-title">{pair ? 'Edit shoes' : 'Add shoes'}</h2>
          <p className="hint">
            Shoes are for keeping track of mileage. They earn nothing and change nothing.
          </p>
        </header>

        <form className="edit-form" onSubmit={save}>
          <label>
            Style
            <select
              value={style}
              disabled={busy}
              onChange={(event) => chooseStyle(event.target.value as GearStyle)}
            >
              {GEAR_STYLES.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>

          <div className="field-row">
            <label>
              Brand
              <input
                type="text"
                value={brand}
                maxLength={BRAND_LIMIT}
                disabled={busy}
                onChange={(event) => setBrand(event.target.value)}
              />
            </label>
            <label>
              Model
              <input
                type="text"
                value={model}
                maxLength={MODEL_LIMIT}
                disabled={busy}
                onChange={(event) => setModel(event.target.value)}
              />
            </label>
          </div>

          <label>
            Nickname
            <input
              type="text"
              value={nickname}
              maxLength={NICKNAME_LIMIT}
              disabled={busy}
              onChange={(event) => setNickname(event.target.value)}
            />
          </label>
          <p className="hint">Optional. Without one they go by their brand and model.</p>

          <div className="field-row">
            <label>
              Size
              <select
                value={size}
                disabled={busy}
                onChange={(event) => setSize(event.target.value)}
              >
                {sizes.map((offered) => (
                  <option key={offered} value={String(offered)}>
                    {sizeLabel(offered)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Width
              <select
                value={width}
                disabled={busy}
                onChange={(event) => setWidth(event.target.value)}
              >
                {widths.map((offered) => (
                  <option key={offered.id} value={offered.id}>
                    {offered.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="field-row">
            <label>
              Miles already on them
              <input
                type="number"
                inputMode="decimal"
                min={0}
                step="0.1"
                value={startingMi}
                disabled={busy}
                onChange={(event) => setStartingMi(event.target.value)}
              />
            </label>
            <label>
              Replace around
              <input
                type="number"
                inputMode="decimal"
                min={0}
                step="10"
                value={replaceMi}
                disabled={busy}
                onChange={(event) => setReplaceMi(event.target.value)}
              />
            </label>
          </div>
          <p className="hint">
            Both optional. A replacement mileage adds one line to the card and nothing else:
            nothing here reminds you.
          </p>

          <label>
            Used for
            <select
              value={appliesTo}
              disabled={busy}
              onChange={(event) => setAppliesTo(event.target.value as GearApplies)}
            >
              {GEAR_APPLIES.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
          <p className="hint">
            Where your default pair goes on its own when a new activity arrives. You can put
            any pair on any walk or run yourself.
          </p>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          <div className="choice">
            <button type="submit" className="secondary" disabled={busy}>
              Save
            </button>
            <button type="button" className="secondary" disabled={busy} onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>

        {verbs}
      </section>
    </dialog>
  )
}

// The shoes on the You screen: what is in the rotation, how far each pair has
// gone, and the way to add, correct, retire or remove one.
//
// Nothing here is a game object. There is no notification, no warning and no
// nudge anywhere in it: a pair with a replacement mileage says where it is and
// stops.
export default function GearCard({
  gear,
  onChanged,
}: {
  gear: Gear[]
  // Every write answers with the whole list, handed back so the screen holding
  // it redraws from the server's word.
  onChanged: (gear: Gear[]) => void
}) {
  // Which pair a panel is open on: a Gear for an edit, null for a new pair, and
  // undefined for nothing open.
  const [editing, setEditing] = useState<Gear | null | undefined>(undefined)
  const [removing, setRemoving] = useState<Gear | null>(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [cardError, setCardError] = useState('')

  async function run(call: () => Promise<Gear[]>, whichError: (message: string) => void) {
    setBusy(true)
    whichError('')
    try {
      onChanged(await call())
      return true
    } catch (err) {
      whichError(errorText(err))
      return false
    } finally {
      setBusy(false)
    }
  }

  async function save(fields: Parameters<Parameters<typeof GearForm>[0]['onSave']>[0]) {
    const pair = editing
    const done = await run(
      () => (pair ? updateGear(pair.id, fields) : addGear(fields)),
      setFormError,
    )
    if (done) setEditing(undefined)
  }

  // Each of the three is a decision rather than an edit, so the panel closes
  // behind it and the card redraws from what came back.
  async function act(call: () => Promise<Gear[]>) {
    if (await run(call, setFormError)) setEditing(undefined)
  }

  // What can be done to a pair rather than to its fields. Drawn inside the
  // panel, and only ever for a pair that already exists.
  function verbsFor(pair: Gear) {
    return (
      <div className="gear-verbs">
        {!pair.retired && !pair.is_default && (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => void act(() => setDefaultGear(pair.id))}
          >
            Make default
          </button>
        )}
        {pair.retired ? (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => void act(() => unretireGear(pair.id))}
          >
            Un-retire
          </button>
        ) : (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => void act(() => retireGear(pair.id))}
          >
            Retire
          </button>
        )}
        <button
          type="button"
          className="workout-delete"
          disabled={busy}
          onClick={() => {
            setCardError('')
            setRemoving(pair)
          }}
        >
          Delete shoes
        </button>
      </div>
    )
  }

  async function remove(pair: Gear) {
    setBusy(true)
    setCardError('')
    try {
      await deleteGear(pair.id)
      onChanged(gear.filter((row) => row.id !== pair.id))
      setRemoving(null)
      setEditing(undefined)
    } catch (err) {
      setCardError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h2 className="label">
        <span className="sport-icon sport-icon-small">
          <Icon name="shoe" />
        </span>
        Shoes
      </h2>

      {gear.length === 0 && (
        <p className="hint">
          No shoes yet. Add a pair and your walks and runs start adding up on them.
        </p>
      )}

      {gear.length > 0 && (
        <ul className="gear-list">
          {gear.map((pair) => {
            const subline = gearSubline(pair)
            const wear = wearLine(pair)
            return (
              <li key={pair.id} className={pair.retired ? 'gear-row gear-retired' : 'gear-row'}>
                <div className="gear-what">
                  <p className="gear-name">
                    {gearName(pair)}
                    {pair.is_default && <span className="gear-chip">Default</span>}
                    {pair.retired && <span className="gear-chip gear-chip-quiet">Retired</span>}
                  </p>
                  {subline !== '' && <p className="hint">{subline}</p>}
                  <p className="hint">{fitLine(pair)}</p>
                  {wear !== '' && <p className="hint">{wear}</p>}
                </div>
                <div className="gear-figure">
                  <span className="count-value">{milesLine(pair.miles)}</span>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => {
                      setFormError('')
                      setEditing(pair)
                    }}
                  >
                    Edit
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {/* While the question is up it is the one saying what went wrong, so the
          card does not say the same sentence behind it. */}
      {cardError && removing === null && (
        <p className="error" role="alert">
          {cardError}
        </p>
      )}

      <div className="choice">
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => {
            setFormError('')
            setEditing(null)
          }}
        >
          Add shoes
        </button>
      </div>

      {editing !== undefined && (
        <GearForm
          pair={editing}
          busy={busy}
          error={formError}
          verbs={editing === null ? undefined : verbsFor(editing)}
          onSave={(fields) => void save(fields)}
          onClose={() => setEditing(undefined)}
        />
      )}

      {/* Only a pair nothing was ever recorded in can go, and the server is what
          says so: anything on an activity comes back with the sentence that
          offers retiring instead. */}
      {removing !== null && (
        <Confirm
          heading="Delete these shoes?"
          confirmLabel="Delete"
          cancelLabel="Keep them"
          busy={busy}
          error={cardError}
          onConfirm={() => void remove(removing)}
          onCancel={() => {
            setRemoving(null)
            setCardError('')
          }}
        >
          <p>{gearName(removing)} comes off your profile for good.</p>
          <p>
            Only a pair with no activities on it can go. If any of your walks or runs were
            done in these, retire them instead: they keep their miles and stay on those
            activities.
          </p>
        </Confirm>
      )}
    </section>
  )
}
