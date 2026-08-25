import { useEffect, useState } from 'react'
import { ALPHA, ALPHA_NOTICE } from '../alpha.ts'
import { getStatus, welcomeAvatarUrl, type Welcome as WelcomeData } from '../api.ts'
import heroDark from '../assets/landing-hero-dark.png'
import mastheadShoe from '../assets/masthead-shoe.png'
import shotArcadeYou from '../assets/shot-arcade-you.webp'
import shotArcadeGrove from '../assets/shot-arcade-grove.webp'
import shotArcadeDetails from '../assets/shot-arcade-details.webp'
import shotDarkHome from '../assets/shot-dark-home.webp'
import shotLightHome from '../assets/shot-light-home.webp'
import shotLightGrove from '../assets/shot-light-grove.webp'
import shotLightYou from '../assets/shot-light-you.webp'
import heroLight from '../assets/landing-hero-light.png'
import { ACTIVITY_ICONS, ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'
import { applyTheme, rememberTheme, type Theme, useTheme } from '../theme.ts'
import AvatarFrame from './AvatarFrame.tsx'
import Icon from './Icon.tsx'
import LandingStats from './LandingStats.tsx'

interface Props {
  // Straight to the form, already on the tab the button promised.
  onEnter: (registering: boolean) => void
  // Set only when this page was opened from an invite link: the invite's own
  // answers, and the code the inviter's picture is fetched by. Absent is the
  // plain page. One page, two variants, and the action block in the hero is
  // the only thing that differs between them.
  invite?: { data: WelcomeData; code: string }
}

// Nothing here may say a step earns anything: steps earn no XP, chest or medal.
export default function Landing({ onEnter, invite }: Props) {
  // Null until the server says which way it is set, so the page does not offer
  // an account and then take the offer back a moment later.
  const [openRegistration, setOpenRegistration] = useState<boolean | null>(null)
  const invited = invite !== undefined
  const who = invite?.data.inviter_display_name ?? ''
  const theme = useTheme()

  // The same two calls Settings makes, in the same order: the ground changes
  // under the button and this browser keeps the choice.
  function chooseTheme(next: Theme) {
    applyTheme(next)
    rememberTheme(next)
  }

  useEffect(() => {
    // A link is its own answer: the invite variant offers the same account on
    // an open instance and a closed one, so it never asks which this is.
    if (invited) return
    getStatus()
      .then((status) => setOpenRegistration(status.registration_open))
      // An unreachable status endpoint means the whole app is unreachable, so
      // there is nothing useful to say. Closed is the safe guess: it offers a
      // sign in, which works on either setting, rather than a form that might
      // refuse everybody who fills it in.
      .catch(() => setOpenRegistration(false))
  }, [invited])

  return (
    <div className="landing">
      <header className="landing-bar">
        <span className="landing-brand">
          {/* The name says everything the mark says, so the mark is decor. */}
          <img className="masthead-shoe" src={mastheadShoe} alt="" />
          <span className="wordmark">secondmile</span>
        </span>
        <div className="landing-bar-verbs">
          {/* Named for the ground it is on rather than the one it would move
              to, so somebody reading it learns where they are before they
              press anything. Quieter than Sign in beside it: the way in is
              the errand, and this is a preference. */}
          <button
            type="button"
            className="secondary landing-appearance"
            onClick={() =>
              chooseTheme(theme === 'light' ? 'dark' : theme === 'dark' ? 'arcade' : 'light')
            }
          >
            Theme: {theme === 'light' ? 'Light' : theme === 'arcade' ? 'Arcade' : 'Dark'}
          </button>
          <button type="button" className="link" onClick={() => onEnter(false)}>
            Sign in
          </button>
        </div>
      </header>

      <section className="landing-hero">
        {/* One drawing per ground; the stylesheet shows whichever matches the
            theme. Decorative rather than described: the four sports are named
            in words a few lines below, so an alt text here would only say
            them twice. */}
        <img className="landing-hero-img landing-hero-img-dark" src={heroDark} alt="" />
        <img className="landing-hero-img landing-hero-img-light" src={heroLight} alt="" />

        {/* The line the name comes from, quoted and cited. The citation is set
            small and faint on purpose: it belongs to the sentence rather than
            competing with it, and somebody who does not recognise the words
            still reads a line about going further than you were asked. */}
        <h1 className="landing-verse">
          &ldquo;And whoever compels you to go one mile, go with him two.&rdquo;
        </h1>
        <p className="landing-cite">Matthew 5:41 NKJV</p>
        <h2 className="landing-tagline">Private running & fitness feed</h2>
        <p className="landing-sub">
          Whether it's your first walk around the block, your first 5K, or your next
          Ironman, every mile counts the same. Earn XP, grow a garden, and encourage others
          on the feed.
        </p>

        {/* The four sports, each with its own mark. The same marks are used
            wherever an activity is named, so this is the first place somebody
            learns them and every screen after it reads the same way. */}
        <ul className="landing-sports">
          {ACTIVITY_ORDER.map((name) => (
            <li key={name}>
              <span className="sport-icon">
                <Icon name={ACTIVITY_ICONS[name]} />
              </span>
              <span className="label">{ACTIVITY_NAMES[name]}</span>
            </li>
          ))}
        </ul>

        {/* What the instance has actually covered, on both variants. It draws
            itself or it draws nothing: see the component. */}
        <LandingStats />

        {/* Their face in its frame, drawn exactly as it is drawn on every
            screen inside the app. The picture rides on the code rather than on
            a session, because nobody reading this page has one. */}
        {invite && (
          <div className="welcome-who">
            <AvatarFrame
              name={who}
              src={invite.data.inviter_has_avatar ? welcomeAvatarUrl(invite.code) : null}
              borderTier={invite.data.inviter_border_tier ?? 0}
              flourish={invite.data.inviter_flourish ?? 0}
              labelled
            />
            <p className="welcome-name">
              This is a private group, and {who} has invited you to join.
            </p>
          </div>
        )}

        {/* The invite variant has no button up here: the one it gets is at the
            foot of the page, past everything the page has to say, so reading
            it is the path of least resistance rather than a thing skipped. */}
        {!invite && (
          <div className="landing-actions">
            {openRegistration ? (
              <button type="button" className="primary" onClick={() => onEnter(true)}>
                Create account
              </button>
            ) : (
              <button type="button" className="primary" onClick={() => onEnter(false)}>
                Sign in
              </button>
            )}
            {/* Said only once the server has actually said so, and said
                plainly: somebody with no way in should learn that before
                they have typed an email address into a form that was always
                going to refuse. There is nothing to type any more, so this
                points at the only way in there is. */}
            {openRegistration === false && (
              <p className="hint landing-invite">
                secondmile is invite-only. Ask a friend for an invite link.
              </p>
            )}
          </div>
        )}

        <p className="landing-sub landing-intro">
          secondmile is a small, invite-only place for staying active and encouraging the
          people you know. Think of that orange running app, but privately hosted and free.
          Walk, run, bike, or swim; every synced workout opens treasure chests along the
          way and grows a personal grove of plants and trees that get boosted with your
          miles. The harvest draws visitors. Your steps come along too, counted and shown
          but not earning. They also do other things, but you'll have to start earning to
          find out.
        </p>

        {/* Said before the account rather than found afterwards: this is what
            makes the promises above honest while they are still being built. */}
        {ALPHA && <p className="landing-alpha">{ALPHA_NOTICE}</p>}
      </section>

      {/* First, because it answers what a person actually has to do, said
          before anything about what they get for it. */}
      <section className="landing-section">
        <p className="label landing-eyebrow">How it works</p>
        <h2>One-time setup, then just move!</h2>
        <p>
          After you set up one of the recommended companion apps to export your activity
          and steps data to secondmile, every walk, run, bicycle and swim workout you
          record with your phone or smart watch earns XP. You never have to log anything
          by hand (unless you wish to manually sync with the exporter app). You never
          have to keep the app open to earn XP: secondmile is designed to encourage you
          to stay active while reducing screentime. Everything you earn will be waiting
          for you in a recap letter the next time you log in and refresh.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Miles earn XP</p>
        <h2>Every mile counts for something</h2>
        {/* The two modifiers are stated rather than discovered. Cycling is the
            only one that earns less than its distance, and somebody who finds
            that out by riding trusts the rest of this page less. Steps are not
            named here at all: a mile is the work put in on a recorded
            activity, and this section is only about those. */}
        <p>
          Each mile earns XP the moment your workout syncs. Swimming counts 4x, cycling
          counts 0.33x. XP opens treasure chests that go up in rarity at each tier, then
          loop back around.
        </p>
      </section>

      {/* Written on 2026-08-09 and held until it was true. It ships in the
          round that built the two sinks it promises: feeding a garden and
          giving to a friend. The eyebrow uses "=" where the one above uses
          "earn" because manna really is calories one for one, while a mile
          earns a different amount of XP depending on the activity; the two read
          differently on purpose, and the difference is the truth.

          The last two sentences are the two-lane law said plainly, and they
          close the obvious objection to it in the same breath: water is not a
          loophole, because water only ever comes out of chests the miles
          dropped. */}
      <section className="landing-section">
        <p className="label landing-eyebrow">Calories = manna</p>
        <h2>Give your garden energy by burning more</h2>
        <p>
          Calories become manna, one for one. Feed it to your garden for a richer
          harvest, or give it to a friend for theirs. It will never make anything grow
          faster. Growth comes from distance, and from the water that distance earns.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Private by design</p>
        <h2>No tracking or selling your data</h2>
        {/* The ZFS pool is the homelab this moves to, which has to be true by
            the day anybody outside can read this. */}
        <p>
          This website has absolutely no trackers, and this entire project is hosted on a
          private server with encrypted ZFS storage. Multiple public visibility settings
          inside.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">What you need</p>
        <h2>An iPhone or an Android</h2>
        <p>
          An iPhone with health and workout data turned on, or an Android phone with Health
          Connect. Each one needs a small exporter app that posts what it reads to your
          account: Health Auto Export on iOS, Health Connect Webhook on Android. The setup
          guide inside walks through both, start to finish, and takes about five minutes.
          {/* Somebody invited by a friend is not turned away by the hardware:
              the friendship is the point and the miles can start later. */}
          {invite && (
            <>
              {' '}
              No phone that qualifies yet? Create your account anyway and look around: you
              will be friends with {who} from day one, and your miles start arriving
              whenever your phone does.
            </>
          )}
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">What this is</p>
        <h2>A fitness encouragement app, not a leaderboard</h2>
        <p>
          No follower counts, no leaderboards, no competitions. This is a fun way to
          encourage friends to stay active, no matter what their lifestyle is like.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Built for busy people</p>
        <h2>No streaks to lose, no expiring items, no FOMO</h2>
        <p>
          Come back to secondmile whenever you want. Your welcome-back letter and XP you
          earned will be waiting for you when you return, as long as you keep syncing your
          workouts. (Notifications can be enabled/disabled)
        </p>
      </section>

      {/* The way in, after everything the page had to say. His call: the top
          button invited people to join before they had read what they were
          joining, and moving it is honester than locking it. */}
      {invite && (
        <section className="landing-section landing-actions">
          {/* Read before the button on purpose: the window anchors to the day
              the account is made, so this is the one fact that rewards being
              known in advance. */}
          <p className="hint landing-invite">
            The app accepts workouts from up to 14 days before your account is
            created, so the sooner you join, the more of your recent miles make
            it in.
          </p>
          <button type="button" className="primary" onClick={() => onEnter(true)}>
            Create your account
          </button>
          <p className="hint landing-invite">
            You will be friends with {who} once you are in.
          </p>
        </section>
      )}

      {/* Real screens near the door, softly blurred where a life shows
          through. A strip rather than a grid: thumbed sideways like the app
          itself. */}
      <section className="landing-section">
        <p className="label landing-eyebrow">Themes</p>
        <h2>Light Mode, Dark Mode, Arcade Mode. (Try it now at the top of the screen)</h2>
        <ul className="landing-shots">
          {[
            [shotArcadeYou, 'The You screen in arcade mode'],
            [shotArcadeGrove, 'The grove in arcade mode'],
            [shotArcadeDetails, 'A workout details view in arcade mode'],
            [shotDarkHome, 'The home feed in dark mode'],
            [shotLightHome, 'The home feed in light mode'],
            [shotLightGrove, 'The grove in light mode'],
            [shotLightYou, 'The You screen in light mode'],
          ].map(([src2, alt]) => (
            <li key={alt}>
              <img src={src2} alt={alt} loading="lazy" />
            </li>
          ))}
        </ul>
      </section>

      <footer className="landing-foot">
        {/* No repository link while the repository is private: a link to a page
            nobody can open says less than the licence does on its own. */}
        <p>secondmile. Open source, AGPL-3.0.</p>
      </footer>
    </div>
  )
}
