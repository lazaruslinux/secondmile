import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  acceptFriend,
  avatarUrl,
  errorText,
  getFriends,
  inviteFriend,
  removeFriend,
  type Friends,
  type Person,
} from '../api.ts'
import { personName } from '../labels.ts'
import AvatarFrame from './AvatarFrame.tsx'

// Said whatever happened. Whether that name belongs to anybody is not this
// screen's news to give: the same sentence either way is what keeps the app
// from being a way to find out who has an account here.
const INVITE_SENT =
  'Sent. If that name belongs to someone here, the invite is waiting in their app.'

// What this card last showed, kept by account for as long as the page lives, so
// coming back to You is not a blank card while the list is on its way.
const cache = new Map<number, Friends>()

const EMPTY: Friends = { friends: [], pending_in: [], pending_out: [] }

interface RowProps {
  person: Person
  // Opens their profile. Only a friend's row carries it: an invitation is not
  // yet somebody there is anything to see about.
  onOpen?: () => void
  children?: ReactNode
}

function PersonRow({ person, onOpen, children }: RowProps) {
  const name = personName(person)
  const face = (
    <AvatarFrame
      name={name}
      src={person.has_avatar ? avatarUrl(person.user_id, null) : null}
      borderTier={person.border_tier}
      flourish={person.flourish}
      frameClass="friend-frame"
    />
  )

  return (
    <li className="friend-row">
      {/* The picture and the name are one control, so a row that goes somewhere
          is pressed anywhere along it rather than only on the two letters of a
          short name. Stripped back to nothing: the row looks as it always did. */}
      {onOpen ? (
        <button type="button" className="friend-open" onClick={onOpen}>
          {face}
          <span className="friend-name">{name}</span>
        </button>
      ) : (
        <>
          {face}
          <span className="friend-name">{name}</span>
        </>
      )}
      {children}
    </li>
  )
}

interface Props {
  userId: number
  // The app owns which screen is up, so the rows that go somewhere are handed
  // the switch rather than reaching for it.
  onOpenPerson: (userId: number) => void
}

// Friends, both ways round: who is one, who asked, and who was asked. There are
// no numbers on this card and no way to look anybody up; a friendship starts
// with a name typed by somebody who already knows it.
export default function Fellowship({ userId, onOpenPerson }: Props) {
  const [state, setState] = useState<Friends>(() => cache.get(userId) ?? EMPTY)
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')

  const [name, setName] = useState('')
  const [inviteBusy, setInviteBusy] = useState(false)
  const [inviteNote, setInviteNote] = useState('')
  const [inviteError, setInviteError] = useState('')

  // Which person a button is working on, so only that row goes quiet.
  const [busyId, setBusyId] = useState<number | null>(null)
  const [actionError, setActionError] = useState('')

  const load = useCallback(async () => {
    try {
      const found = await getFriends()
      cache.set(userId, found)
      setState(found)
      setLoadError('')
    } catch (err) {
      setLoadError(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    void load()
  }, [load])

  async function invite(event: FormEvent) {
    event.preventDefault()
    const wanted = name.trim()
    if (wanted === '') return
    setInviteBusy(true)
    setInviteNote('')
    setInviteError('')
    try {
      await inviteFriend(wanted)
      setInviteNote(INVITE_SENT)
      setName('')
      await load()
    } catch (err) {
      setInviteError(errorText(err))
    } finally {
      setInviteBusy(false)
    }
  }

  async function act(personId: number, work: () => Promise<void>) {
    setBusyId(personId)
    setActionError('')
    try {
      await work()
      await load()
    } catch (err) {
      setActionError(errorText(err))
    } finally {
      setBusyId(null)
    }
  }

  const { friends, pending_in: waiting, pending_out: asked } = state
  const quiet = friends.length === 0 && waiting.length === 0 && asked.length === 0

  return (
    <section className="card fellowship">
      <h2 className="label">Friends</h2>

      {loading && <p className="notice">Loading.</p>}
      {loadError && (
        <p className="error" role="alert">
          {loadError}
        </p>
      )}
      {actionError && (
        <p className="error" role="alert">
          {actionError}
        </p>
      )}

      {/* Friends first, directly under the heading that names them, so the
          lists below cannot be read as part of this one. Nothing is drawn for a
          list that is empty: no headings over nothing, no count of how few. */}
      {friends.length > 0 && (
        <ul className="friend-list">
          {friends.map((person) => (
            <PersonRow
              key={person.user_id}
              person={person}
              onOpen={() => onOpenPerson(person.user_id)}
            />
          ))}
        </ul>
      )}

      {waiting.length > 0 && (
        <>
          <h3 className="label fellowship-head">Invites to you</h3>
          <ul className="friend-list">
            {waiting.map((person) => (
              <PersonRow key={person.user_id} person={person}>
                <span className="friend-buttons">
                  <button
                    type="button"
                    className="primary"
                    disabled={busyId === person.user_id}
                    onClick={() => void act(person.user_id, () => acceptFriend(person.user_id))}
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busyId === person.user_id}
                    onClick={() => void act(person.user_id, () => removeFriend(person.user_id))}
                  >
                    Decline
                  </button>
                </span>
              </PersonRow>
            ))}
          </ul>
        </>
      )}

      {asked.length > 0 && (
        <>
          <h3 className="label fellowship-head">Invites you sent</h3>
          <ul className="friend-list">
            {asked.map((person) => (
              <PersonRow key={person.user_id} person={person}>
                <span className="friend-buttons">
                  <button
                    type="button"
                    className="secondary"
                    disabled={busyId === person.user_id}
                    onClick={() => void act(person.user_id, () => removeFriend(person.user_id))}
                  >
                    Cancel
                  </button>
                </span>
              </PersonRow>
            ))}
          </ul>
        </>
      )}

      {!loading && quiet && <p className="hint">No one here yet.</p>}

      <form className="invite" onSubmit={invite}>
        <label>
          Invite by username
          <input
            type="text"
            value={name}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            disabled={inviteBusy}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <button type="submit" className="primary" disabled={inviteBusy || name.trim() === ''}>
          Send invite
        </button>
        <p className="hint">
          Invites are quiet: the other person simply sees it in their app. Friends see each
          other's distance, time, and route. Nobody else does.
        </p>
        {inviteNote && (
          <p className="note note-success" role="status">
            {inviteNote}
          </p>
        )}
        {inviteError && (
          <p className="error" role="alert">
            {inviteError}
          </p>
        )}
      </form>
    </section>
  )
}
