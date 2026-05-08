import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    strictPort: true,
    proxy: {
      '/triage': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        timeout: 600_000,
      },
      '/draft-postmortem': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        timeout: 600_000,
      },
      '/healthz': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
