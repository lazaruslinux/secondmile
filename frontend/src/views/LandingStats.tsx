import { useEffect, useRef, useState } from 'react'
import { getStats, type Stats } from '../api.ts'

// How long the digits take to arrive at the totals. Long enough to read as a
// count rather than a flicker, short enough that nobody is waiting on it.
const ROLL_MS = 1200

// Fast then settling, which is what makes a rolling number look like it is
// arriving somewhere rather than being scrubbed.
function easeOut(through: number): number {
  return 1 - (1 - through) ** 3
}

// What the instance has covered, under the sports in the hero. Two numbers and
// nothing else, and every one of them is a fact: this band draws what the
// server counted or it draws nothing at all.
//
// Nothing here is retried and nothing here reports a failure. A counter is a
// garnish on a page somebody is reading before they have an account, so an
// unreachable server, an answer that is not a pair of numbers, and an instance
// with no workouts on it all end the same way, with an empty hero paragraph
// gap and no explanation asked of the reader.
export default function LandingStats() {
  // What the server said, once. One fetch on mount and no polling: the totals
  // move slowly and the page is read once.
  const [totals, setTotals] = useState<Stats | null>(null)
  const [shown, setShown] = useState<Stats>({ miles: 0, activities: 0 })
  const band = useRef<HTMLUListElement>(null)

  useEffect(() => {
    let live = true
    void getStats()
      .then((got) => {
        // Typed as numbers, checked as numbers: this is the one response the
        // app reads without a session, and a server answering something else
        // should leave the page as it was rather than print NaN in it.
        if (!live || !Number.isFinite(got.miles) || !Number.isFinite(got.activities)) return
        // Whole and never negative, whatever arrived. The server already sends
        // them that way; this is what keeps a wrong one from being drawn.
        setTotals({
          miles: Math.max(0, Math.trunc(got.miles)),
          activities: Math.max(0, Math.trunc(got.activities)),
        })
      })
      .catch(() => {
        // See above: a pre-auth page says nothing about a garnish that failed.
      })
    return () => {
      live = false
    }
  }, [])

  // The count runs once, when the band is first scrolled to, and then rests
  // forever. Watching for that rather than starting on mount is what stops the
  // whole thing happening above somebody's first scroll, where the numbers
  // would already be sitting still by the time they were looked at.
  useEffect(() => {
    const list = band.current
    if (!totals || !list) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setShown(totals)
      return
    }
    let frame = 0
    const watcher = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return
        watcher.disconnect()
        const started = performance.now()
        const step = (now: number) => {
          const through = Math.min((now - started) / ROLL_MS, 1)
          const eased = easeOut(through)
          // Rounded rather than floored, so the last frame lands exactly on the
          // totals: eased is 1 there and the numbers are the server's own.
          setShown({
            miles: Math.round(totals.miles * eased),
            activities: Math.round(totals.activities * eased),
          })
          if (through < 1) frame = requestAnimationFrame(step)
        }
        frame = requestAnimationFrame(step)
      },
      { threshold: 0.4 },
    )
    watcher.observe(list)
    return () => {
      watcher.disconnect()
      cancelAnimationFrame(frame)
    }
  }, [totals])

  // Nothing yet, and nothing on an instance that has covered nothing: a wall of
  // zeros sells emptiness rather than life.
  if (!totals || (totals.miles === 0 && totals.activities === 0)) return null

  return (
    <ul className="landing-stats" ref={band}>
      <li>
        <span className="landing-stat-value">{shown.miles.toLocaleString()}</span>
        <span className="label">Miles covered</span>
      </li>
      <li>
        <span className="landing-stat-value">{shown.activities.toLocaleString()}</span>
        <span className="label">Activities synced</span>
      </li>
    </ul>
  )
}
