// First, and before anything draws: it names the chosen ground on the root
// element, and the stylesheet under it reads that.
import './theme.ts'
// Registers the push worker on the way in, so a deploy reaches every
// subscribed device without anyone opening Settings again.
import './push.ts'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
