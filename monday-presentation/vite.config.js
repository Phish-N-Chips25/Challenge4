import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    watch: {
      // Large/locked media files can trigger EBUSY watcher crashes on Windows.
      ignored: ['**/video/**', '**/videos/**', '**/*.mp4'],
    },
  },
})
