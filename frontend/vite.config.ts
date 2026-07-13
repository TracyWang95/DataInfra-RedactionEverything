/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
const backendProxy = {
  '/api': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
  },
  '/health': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
  },
  '/uploads': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
  },
  '/outputs': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
  },
} as const;

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(process.env.npm_package_version ?? '0.0.0'),
    __BUILD_TIME__: JSON.stringify(new Date().toISOString().slice(0, 16).replace('T', ' ')),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            // zh stays statically imported (sync, modulepreloaded — no flicker)
            // but lives in its own file so the entry chunk stays small.
            if (id.replace(/\\/g, '/').includes('/src/i18n/zh')) return 'locale-zh';
            return undefined;
          }
          if (
            id.includes('react-router-dom') ||
            id.includes('react-router') ||
            id.includes('@remix-run/router')
          ) {
            return 'vendor-router';
          }
          if (id.includes('react-dom')) return 'vendor-react-dom';
          if (id.includes('/react/')) return 'vendor-react';
          if (id.includes('@radix-ui')) return 'vendor-radix';
          if (id.includes('zustand')) return 'vendor-state';
          if (id.includes('axios')) return 'vendor-network';
          if (id.includes('lucide-react')) return 'vendor-icons';
          return undefined;
        },
      },
    },
  },
  test: {
    globals: true,
    // Pure-logic tests only for now; switch to jsdom (and install it) when
    // component tests arrive.
    environment: 'node',
    setupFiles: [],
  },
  server: {
    port: 3005,
    proxy: { ...backendProxy },
  },
  /** `vite preview` 默认不转发 API，直接打开 dist 会请求不到后端 → 与 dev 共用代理 */
  preview: {
    port: 3005,
    proxy: { ...backendProxy },
  },
})
