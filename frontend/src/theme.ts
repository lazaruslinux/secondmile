// Which ground the app is drawn on. Kept per browser rather than per account,
// which is the point of it: a phone in bed at night and a desktop by a window
// are not the same room, and one account is used from both.
//
// Applied by naming the choice on the root element, where the stylesheet's
// light and arcade blocks look for it. That has to happen before anything
// renders, so this module is imported first in main.tsx and does its work on
// the way in. It cannot happen any earlier: the only way to beat the bundle is
// a script in the page head, and the content security policy refuses inline
// script. What that costs is one dark frame on a cold load for somebody not on
// dark, which is cheaper than loosening the policy.

import { useSyncExternalStore } from 'react'

const THEME_KEY = 'secondmile.appearance.theme'

export type Theme = 'light' | 'dark' | 'arcade'

// The two grounds anything drawn twice is drawn on. Arcade is a skin over the
// dark one rather than a ground of its own: the artwork, the map, and the
// pictures taken of it are dark's, and only the stylesheet tells them apart.
export type Ground = 'light' | 'dark'

export function ground(theme: Theme): Ground {
  return theme === 'light' ? 'light' : 'dark'
}

// Dark is the default and the fallback: a browser with storage turned off, or
// one that has never been asked, opens on the theme everybody starts with. A
// value that is not one of ours reads as dark rather than as itself.
function rememberedTheme(): Theme {
  try {
    const kept = localStorage.getItem(THEME_KEY)
    return kept === 'light' || kept === 'arcade' ? kept : 'dark'
  } catch {
    return 'dark'
  }
}

export function rememberTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Nothing to say: the choice holds for this visit and is forgotten after.
  }
}

// What the browser paints its own chrome with, kept in step with --bg by hand:
// a meta tag cannot read a custom property, so the values live here too.
const CHROME: Record<Theme, string> = {
  dark: '#000000',
  light: '#f6f6f7',
  arcade: '#070709',
}

// The theme the app is being drawn on right now. Kept here beside the element
// it is written to, because the stylesheet is not the only thing that reads it:
// some of the artwork exists twice, once per ground, and the components drawing
// it have to be told when the ground moves under them.
let current: Theme = rememberedTheme()
const watchers = new Set<() => void>()

export function applyTheme(theme: Theme): void {
  current = theme
  document.documentElement.dataset.theme = theme
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', CHROME[theme])
  for (const watcher of watchers) watcher()
}

function watch(watcher: () => void): () => void {
  watchers.add(watcher)
  return () => {
    watchers.delete(watcher)
  }
}

// The current ground, for anything that has to redraw when it changes. Every
// way of changing the theme goes through applyTheme, so this cannot drift from
// what the root element says.
export function useTheme(): Theme {
  return useSyncExternalStore(watch, () => current)
}

applyTheme(current)
