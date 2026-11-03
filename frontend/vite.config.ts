import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({ plugins:[react()], base: process.env.VITE_BASE || '/', server:{port:5173,strictPort:true,proxy:{'/api':'http://localhost:8000'}}, build:{outDir:'../app/web/static/studio',emptyOutDir:true} })
