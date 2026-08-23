// Which phone is reading, guessed from the browser, and the name of the app
// that sends workouts from it. Guessed rather than asked, and every screen that
// uses it lets you say otherwise: the setup guide has its chips, and the sync
// notice on Home is only ever a nudge toward an app you already installed.

export type Platform = 'apple' | 'android'

export function guessPlatform(): Platform {
  return /android/i.test(navigator.userAgent) ? 'android' : 'apple'
}

// What to call the exporter in a sentence. A desktop browser is neither phone
// and gets the words rather than a product name, because naming the wrong app
// is worse than naming none.
export function exporterName(): string {
  if (/android/i.test(navigator.userAgent)) return 'Health Connect Webhook'
  if (/iPhone|iPad|iPod/.test(navigator.userAgent)) return 'Health Auto Export'
  return 'your health export app'
}
