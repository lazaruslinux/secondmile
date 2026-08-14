import { useEffect, useState } from 'react'
import {
  errorText,
  listInviteLinks,
  mintInviteLink,
  revokeInviteLink,
  type InviteLink,
} from '../api.ts'
import Confirm from './Confirm.tsx'

// The way in for somebody who has no account here yet, which is the other half
// of inviting by name: one link, one person, and the two of you are friends the
// moment they use it.
export default function InviteLinks() {
  const [links, setLinks] = useState<InviteLink[]>([])
  const [linkError, setLinkError] = useState('')
  const [linkBusy, setLinkBusy] = useState(false)
  // Which link a Revoke button is asking about. Null while nothing is asked.
  const [revoking, setRevoking] = useState<InviteLink | null>(null)
  // Null until a Copy button is used, then which copyable thing it was and
  // whether it worked, so one message never appears under another's button.
  // Invite links name themselves by id, since there may be several.
  const [copyState, setCopyState] = useState<{ what: string; ok: boolean } | null>(null)

  useEffect(() => {
    listInviteLinks()
      .then(setLinks)
      .catch((err: unknown) => setLinkError(errorText(err)))
  }, [])

  // Both verbs end the same way: the server is asked for the list again, so
  // what is on screen is what it holds rather than what was just sent to it.
  async function changeLinks(work: () => Promise<void>) {
    setLinkBusy(true)
    setLinkError('')
    try {
      await work()
      setLinks(await listInviteLinks())
      setRevoking(null)
    } catch (err) {
      setLinkError(errorText(err))
    } finally {
      setLinkBusy(false)
    }
  }

  // Built from the address this page was opened on, so the link somebody sends
  // is right for whoever is reading it rather than for whoever installed the
  // site.
  function linkUrl(code: string): string {
    return `${window.location.origin}/welcome/${code}`
  }

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text)
      setCopyState({ what, ok: true })
    } catch {
      // No clipboard on an insecure origin, or the browser refused. Nothing is
      // lost: the text is on the screen and can be selected by hand.
      setCopyState({ what, ok: false })
    }
  }

  return (
    <section className="settings-group">
      <h2 className="label settings-title">Invite links</h2>

      <div className="card">
        <h3>Invite someone</h3>
        <p className="hint">
          A link lets one person make an account, and the two of you are friends once
          they do. It works once and does not expire. Revoke it if you send it to the
          wrong place.
        </p>

        {links.length > 0 && (
          <ul className="link-list">
            {links.map((link) => (
              <li key={link.id} className="link-row">
                <code className="link-url">{linkUrl(link.code)}</code>
                <div className="link-verbs">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => void copy(linkUrl(link.code), `link-${link.id}`)}
                  >
                    Copy
                  </button>
                  {/* Every listed link is waiting: a spent one leaves the list
                      (the friendship is its record) and a revoked one is
                      deleted, so both verbs always apply. */}
                  <button
                    type="button"
                    className="secondary"
                    disabled={linkBusy}
                    onClick={() => setRevoking(link)}
                  >
                    Revoke
                  </button>
                </div>
                {copyState?.what === `link-${link.id}` && (
                  <p className={copyState.ok ? 'note note-success' : 'note'} role="status">
                    {copyState.ok
                      ? 'Copied.'
                      : 'This browser would not copy it. Select the link and copy it by hand.'}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}

        {/* While the dialog is up it is the one saying what went wrong, so
            the card does not say the same sentence a second time behind it. */}
        {linkError && revoking === null && (
          <p className="error" role="alert">
            {linkError}
          </p>
        )}

        <button
          type="button"
          className="primary"
          disabled={linkBusy}
          onClick={() => void changeLinks(async () => void (await mintInviteLink()))}
        >
          Make a link
        </button>

        {/* A link somebody may already be holding, so it asks first, in the
            same dialog every other question of this shape is asked in. */}
        {revoking !== null && (
          <Confirm
            heading="Revoke this link?"
            confirmLabel="Revoke the link"
            cancelLabel="Cancel"
            busy={linkBusy}
            error={linkError}
            onConfirm={() => void changeLinks(() => revokeInviteLink(revoking.id))}
            onCancel={() => {
              setLinkError('')
              setRevoking(null)
            }}
          >
            <p>
              Anybody holding it will not be able to make an account with it. You can
              make another.
            </p>
          </Confirm>
        )}
      </div>
    </section>
  )
}
