import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 8501,
    proxy: {
      '/api': {
        target: 'http://localhost:8502',
        changeOrigin: true,
      },
      '/output': {
        target: 'http://localhost:8502',
        changeOrigin: true,
      }
    }
  }
})

