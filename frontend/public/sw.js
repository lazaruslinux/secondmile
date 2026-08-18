// Push only, on purpose. No fetch handler and no cache lives here: the app is
// served fresh by nginx, and a worker that cached the bundle would keep
// serving an old one after every deploy. The server composes the whole
// notification, so this stays a pipe.
self.addEventListener('push', (event) => {
  if (!event.data) return
  let payload
  try {
    payload = event.data.json()
  } catch {
    return
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || 'secondmile', {
      body: payload.body || '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
    }),
  )
})

// A tap lands in the app: an open tab if there is one, a new one if not.
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((tabs) => {
      const open = tabs.find((tab) => 'focus' in tab)
      return open ? open.focus() : self.clients.openWindow('/')
    }),
  )
})
