import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Local development proxy for same-origin game and admin API calls.
export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
