import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import {
  ApiError,
  deleteAvatar,
  errorText,
  setProfileDetails,
  uploadAvatar,
  type Profile as ProfileData,
} from '../api.ts'
import { ageOf } from '../profile.ts'

// What the server accepts, checked here as well so an oversized picture is
// answered at once instead of after a whole upload.
const MAX_AVATAR_BYTES = 5 * 1024 * 1024
const TOO_LARGE = 'That picture is too large. The limit is 5 MB.'

// The upload endpoint refuses things for reasons a person can act on, and two
// of them can be answered by the proxy in front of the app rather than by the
// server, so the sentence is written here rather than read off the response.
function uploadErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 413) return TOO_LARGE
    if (err.status === 429) return 'Too many uploads just now. Wait a minute and try again.'
    return err.message
  }
  return 'Something went wrong. Try again.'
}

// An empty box means the field is being cleared, which the server reads as a
// null rather than as an empty string.
function orNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

interface Props {
  profile: ProfileData
  // The picture is saved the moment it is chosen, so the screen behind this is
  // told about it separately from the rest of the form.
  onAvatarChanged: (hasAvatar: boolean, version: number | null) => void
  onSaved: (profile: ProfileData) => void
  onClose: () => void
}

// Everything about this account a person types in themselves, in one panel: the
// picture, the name it goes by, a birthdate, and a word for gender. All of it is
// optional and all of it can be emptied again.
export default function EditProfile({ profile, onAvatarChanged, onSaved, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)

  const [firstName, setFirstName] = useState(profile.first_name ?? '')
  const [lastName, setLastName] = useState(profile.last_name ?? '')
  const [birthdate, setBirthdate] = useState(profile.birthdate ?? '')
  const [gender, setGender] = useState(profile.gender ?? '')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  // Which avatar call is in flight, so the note can say what is happening.
  const [avatarBusy, setAvatarBusy] = useState<'' | 'upload' | 'remove'>('')
  const [avatarError, setAvatarError] = useState('')
  const [hasAvatar, setHasAvatar] = useState(profile.has_avatar)

  // Opened as a modal rather than with the open attribute, because only the
  // modal form brings the focus trap, the page behind held still, and Esc.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  async function pickAvatar(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    // Cleared either way, so choosing the same file twice still counts as a
    // change and the picker does not sit there naming a spent upload.
    event.target.value = ''
    if (!file) return
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError(TOO_LARGE)
      return
    }
    setAvatarBusy('upload')
    setAvatarError('')
    try {
      const state = await uploadAvatar(file)
      setHasAvatar(state.has_avatar)
      onAvatarChanged(state.has_avatar, state.avatar_version)
    } catch (err) {
      setAvatarError(uploadErrorText(err))
    } finally {
      setAvatarBusy('')
    }
  }

  async function removeAvatar() {
    setAvatarBusy('remove')
    setAvatarError('')
    try {
      await deleteAvatar()
      setHasAvatar(false)
      onAvatarChanged(false, null)
    } catch (err) {
      setAvatarError(uploadErrorText(err))
    } finally {
      setAvatarBusy('')
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setSaveError('')
    try {
      onSaved(
        await setProfileDetails({
          first_name: orNull(firstName),
          last_name: orNull(lastName),
          birthdate: orNull(birthdate),
          gender: orNull(gender),
        }),
      )
      onClose()
    } catch (err) {
      setSaveError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  // The age shown beside the birthdate is worked out from it, here and on the
  // server both, so there is never a second number to keep in step.
  const age = ageOf({ ...profile, age: null, birthdate })

  return (
    <dialog
      className="overlay"
      ref={dialog}
      aria-labelledby="edit-title"
      onCancel={(event) => {
        // Esc. Closing is the caller's business, so the browser's own close is
        // left undone and the caller takes this off the screen.
        event.preventDefault()
        onClose()
      }}
    >
      <section className="overlay-panel">
        <header className="overlay-head">
          <h2 id="edit-title">Edit profile</h2>
          <p className="hint">
            All of this is optional. Your username is what you sign in with and does not
            change here.
          </p>
        </header>

        <form className="edit-form" onSubmit={save}>
          {/* The picture saves itself the moment one is chosen, which is why it
              sits above the fields rather than inside what Save sends. */}
          <div className="edit-avatar">
            <label className="file-field">
              Profile picture
              <input
                type="file"
                accept="image/*"
                disabled={avatarBusy !== ''}
                onChange={pickAvatar}
              />
            </label>
            {hasAvatar && (
              <button
                type="button"
                className="secondary"
                disabled={avatarBusy !== ''}
                onClick={() => void removeAvatar()}
              >
                Remove picture
              </button>
            )}
            {avatarBusy === 'upload' && (
              <p className="hint" role="status">
                Uploading.
              </p>
            )}
            {avatarBusy === 'remove' && (
              <p className="hint" role="status">
                Removing.
              </p>
            )}
            {avatarError && (
              <p className="error" role="alert">
                {avatarError}
              </p>
            )}
          </div>

          <div className="field-row">
            <label>
              First name
              <input
                type="text"
                value={firstName}
                maxLength={40}
                autoComplete="given-name"
                onChange={(event) => setFirstName(event.target.value)}
              />
            </label>
            <label>
              Last name
              <input
                type="text"
                value={lastName}
                maxLength={40}
                autoComplete="family-name"
                onChange={(event) => setLastName(event.target.value)}
              />
            </label>
          </div>
          <p className="hint">
            Shown as your name on your profile and on your workouts. Leave both empty to go
            by your username.
          </p>

          <label>
            Birthdate
            <input
              type="date"
              value={birthdate}
              onChange={(event) => setBirthdate(event.target.value)}
            />
          </label>
          {age !== null && <p className="hint edit-age">Age {age}, from your birthdate.</p>}

          <label>
            Gender
            <input
              type="text"
              value={gender}
              maxLength={32}
              onChange={(event) => setGender(event.target.value)}
            />
          </label>
          <p className="hint">
            Your birthdate and gender are shown to you only. Nobody else sees them.
          </p>

          {saveError && (
            <p className="error" role="alert">
              {saveError}
            </p>
          )}

          <div className="choice">
            <button type="submit" className="primary" disabled={saving}>
              Save
            </button>
            <button type="button" className="secondary" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      </section>
    </dialog>
  )
}
