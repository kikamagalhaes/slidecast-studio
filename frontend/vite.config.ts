import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig(({ mode }) => {
  const landing = mode === 'landing'
  return {
    plugins: [react()],
    root: landing ? 'landing' : '.',
    base: landing ? (process.env.VITE_LANDING_BASE || '/static/landing/') : (process.env.VITE_BASE || '/'),
    server: { port: 5173, strictPort: true, proxy: { '/api': 'http://localhost:8000' } },
    build: { outDir: landing ? '../../app/web/static/landing' : '../app/web/static/studio', emptyOutDir: true },
  }
})
