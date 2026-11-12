/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': backend, '/healthz': backend } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
    css: true, // 스타일 규칙을 글로 검사하는 시험이 있음
  },
})
