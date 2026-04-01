/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
const backendProxy = {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
  },
  '/health': {
    target: 'http://localhost:8000',
    changeOrigin: true,
  },
  '/uploads': {
    target: 'http://localhost:8000',
    changeOrigin: true,
  },
  '/outputs': {
    target: 'http://localhost:8000',
    changeOrigin: true,
  },
} as const;

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: [],
  },
  server: {
    port: 3000,
    proxy: { ...backendProxy },
  },
  /** `vite preview` 默认不转发 API，直接打开 dist 会请求不到后端 → 与 dev 共用代理 */
  preview: {
    port: 3000,
    proxy: { ...backendProxy },
  },
})
