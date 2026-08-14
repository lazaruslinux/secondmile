// Which ground the app is drawn on. Kept per browser rather than per account,
// which is the point of it: a phone in bed at night and a desktop by a window
// are not the same room, and one account is used from both.
//
// Applied by naming the choice on the root element, where the stylesheet's
// light block looks for it. That has to happen before anything renders, so this
// module is imported first in main.tsx and does its work on the way in. It
// cannot happen any earlier: the only way to beat the bundle is a script in the
// page head, and the content security policy refuses inline script. What that
// costs is one dark frame on a cold load for somebody set to light, which is
// cheaper than loosening the policy.

const THEME_KEY = 'secondmile.appearance.theme'

export type Theme = 'light' | 'dark'

// Dark is the default and the fallback: a browser with storage turned off, or
// one that has never been asked, opens on the theme everybody starts with.
export function rememberedTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'
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

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
}

applyTheme(rememberedTheme())
