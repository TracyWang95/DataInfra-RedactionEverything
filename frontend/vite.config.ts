/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
// 本地后端默认 8090（8082/8083 常被 MinIO 占用）；可通过 VITE_BACKEND_URL 覆盖
const backendTarget =
  process.env.VITE_BACKEND_URL ??
  process.env.BACKEND_URL ??
  'http://127.0.0.1:8090';

const backendProxy = {
  '/api': {
    target: backendTarget,
    changeOrigin: true,
  },
  '/health': {
    target: backendTarget,
    changeOrigin: true,
  },
  '/uploads': {
    target: backendTarget,
    changeOrigin: true,
  },
  '/outputs': {
    target: backendTarget,
    changeOrigin: true,
  },
} as const;

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;
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
