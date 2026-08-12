import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  acceptFriend,
  avatarUrl,
  cancelInvite,
  errorText,
  findMembers,
  getFriends,
  inviteFriend,
  removeFriend,
  type Friends,
  type MemberCard,
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
  // A friend's little card, or the restricted card a search comes back with.
  // The two carry the same four things a row is drawn from.
  person: Person | MemberCard
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
      borderTier={person.border_tier ?? 0}
      flourish={person.flourish ?? 0}
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

// Friends, both ways round: who is one, who asked, and who was asked, with a
// way to look a member up above them. There are no numbers on this card. The
// search is for members of this instance, which is a room somebody was let
// into rather than an index of the world; the invite form under it still takes
// a name typed by somebody who already knows it, and still says the same thing
// whether that name belongs to anybody or not.
export default function Fellowship({ userId, onOpenPerson }: Props) {
  const [state, setState] = useState<Friends>(() => cache.get(userId) ?? EMPTY)
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')

  const [name, setName] = useState('')
  const [inviteBusy, setInviteBusy] = useState(false)
  const [inviteNote, setInviteNote] = useState('')
  const [inviteError, setInviteError] = useState('')

  // Which person a button is working on, so only that row goes quiet. Sent
  // invites are held by name rather than by id, because a name is all the
  // server says about them.
  const [busyId, setBusyId] = useState<number | null>(null)
  const [busyName, setBusyName] = useState('')
  const [actionError, setActionError] = useState('')

  // Looking a member up. Null until a search has actually been run, so an
  // empty result and a box nobody has used yet are two different states and
  // only one of them says nothing was found.
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<MemberCard[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')

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

  async function search(event: FormEvent) {
    event.preventDefault()
    const wanted = query.trim()
    // The server refuses anything shorter and so does this: a single letter is
    // the roster read a page at a time, and the roster is not on offer.
    if (wanted.length < 2) return
    setSearching(true)
    setSearchError('')
    try {
      setFound(await findMembers(wanted))
    } catch (err) {
      setSearchError(errorText(err))
    } finally {
      setSearching(false)
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

  async function cancel(username: string) {
    setBusyName(username)
    setActionError('')
    try {
      await cancelInvite(username)
      await load()
    } catch (err) {
      setActionError(errorText(err))
    } finally {
      setBusyName('')
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

      {/* Above the lists, because this is how somebody arrives at a person who
          is not on any of them yet. A search and never a listing: nothing is
          shown until a name is typed, and typing one letter shows nothing
          either. */}
      <form className="member-search" onSubmit={search}>
        <label>
          Find a member
          <input
            type="search"
            value={query}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            disabled={searching}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <button
          type="submit"
          className="secondary"
          disabled={searching || query.trim().length < 2}
        >
          Search
        </button>
      </form>

      {searchError && (
        <p className="error" role="alert">
          {searchError}
        </p>
      )}

      {found !== null &&
        (found.length === 0 ? (
          <p className="hint">Nobody here by that name.</p>
        ) : (
          <ul className="friend-list">
            {found.map((person) => (
              <PersonRow
                key={person.user_id}
                person={person}
                onOpen={() => onOpenPerson(person.user_id)}
              />
            ))}
          </ul>
        ))}

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
          {/* Names, and only names. There is no picture and no profile behind
              one of these rows: the server will not say whether anybody answers
              to the name, so there is nothing here to open. */}
          <ul className="friend-list">
            {asked.map((invite) => (
              <li key={invite.username} className="friend-row">
                <span className="friend-name">{invite.username}</span>
                <span className="friend-buttons">
                  <button
                    type="button"
                    className="secondary"
                    disabled={busyName === invite.username}
                    onClick={() => void cancel(invite.username)}
                  >
                    Cancel
                  </button>
                </span>
              </li>
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
          An invite shows up in their app. Friends see each other's activities. Comments on
          an activity are read by everyone who can see it.
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
