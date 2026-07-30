import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // In development the browser talks to the Vite server and Vite forwards
      // /api to the backend, which keeps every request same-origin so the
      // session cookie behaves exactly as it does behind nginx in production.
      // The path is passed through unchanged because the backend serves its
      // routes under /api itself.
      '/api': { target: 'http://127.0.0.1:8100', changeOrigin: true },
    },
  },
  preview: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8100', changeOrigin: true },
    },
  },
})
