import Fellowship from './Fellowship.tsx'
import InviteLinks from './InviteLinks.tsx'

interface Props {
  userId: number
  // The app owns which screen is up, so the rows that go somewhere are handed
  // the switch rather than reaching for it.
  onOpenPerson: (userId: number) => void
}

// The people, and nothing they did: who is here, who asked, who was asked, and
// the two ways to ask somebody else. Home is the feed, and a second one here
// would be Home twice.
export default function Friends({ userId, onOpenPerson }: Props) {
  return (
    <>
      <div className="view-head">
        <h1 className="view-title">Friends</h1>
      </div>

      <Fellowship userId={userId} onOpenPerson={onOpenPerson} />

      {/* Under the people already here, because a link is the errand for
          somebody who has no account yet and cannot be looked up or named. */}
      <InviteLinks />
    </>
  )
}
