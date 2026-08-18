// Web push for this device. The server composes every notification and the
// worker in public/sw.js just shows them; what lives here is the browser half
// of turning a device on and off: permission, the push subscription, and the
// calls that tell the server about it.

import { getPushKey, subscribePush, unsubscribePush } from './api.ts'

// Everything a device needs before it can even ask: a worker, the Push API,
// and the Notification API. An iPhone browser tab has none of the last two
// until the site is added to the Home Screen, which is Apple's rule for web
// push rather than anything this app chose.
export function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

// Where the missing support has a remedy the Settings card can name: on these
// devices, adding the site to the Home Screen is what turns push on.
export function isApplePhone(): boolean {
  return /iPhone|iPad|iPod/.test(navigator.userAgent)
}

// Registered on every load so the browser keeps the worker current after a
// deploy. Harmless when nothing is subscribed: registering asks nobody
// anything and shows nothing.
if ('serviceWorker' in navigator) {
  void navigator.serviceWorker.register('/sw.js').catch(() => {
    // A browser that refuses the worker simply stays a device without push;
    // the Settings card reports that state on its own.
  })
}

export type DeviceState = 'unsupported' | 'off' | 'denied' | 'on'

export async function deviceState(): Promise<DeviceState> {
  if (!pushSupported()) return 'unsupported'
  if (Notification.permission === 'denied') return 'denied'
  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
  return subscription ? 'on' : 'off'
}

// The key arrives base64url; the subscribe call wants raw bytes.
function keyBytes(key: string): ArrayBuffer {
  const padded = key + '='.repeat((4 - (key.length % 4)) % 4)
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i)
  return bytes.buffer
}

export async function enableThisDevice(): Promise<DeviceState> {
  // The key is fetched before the permission prompt on purpose: a server
  // without push configured should say so without spending the one prompt a
  // browser allows before it starts refusing to ask.
  const key = await getPushKey()
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    return permission === 'denied' ? 'denied' : 'off'
  }
  const registration = await navigator.serviceWorker.ready
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(key),
    }))
  const json = subscription.toJSON()
  await subscribePush({
    endpoint: subscription.endpoint,
    keys: { p256dh: json.keys?.p256dh ?? '', auth: json.keys?.auth ?? '' },
  })
  return 'on'
}

export async function disableThisDevice(): Promise<DeviceState> {
  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
  if (subscription) {
    // The server first, while the endpoint still exists to name; the browser
    // half second, so a failed server call leaves a device that can retry.
    await unsubscribePush(subscription.endpoint)
    await subscription.unsubscribe()
  }
  return 'off'
}
