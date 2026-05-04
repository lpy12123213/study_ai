import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'

function vendorChunkName(id: string): string | undefined {
  const normalized = id.replace(/\\/g, '/')
  if (!normalized.includes('/node_modules/')) return undefined

  if (normalized.includes('/node_modules/katex/')) {
    return 'pkg-katex'
  }

  if (
    normalized.includes('/node_modules/react-markdown/')
    || normalized.includes('/node_modules/remark-')
    || normalized.includes('/node_modules/rehype-')
    || normalized.includes('/node_modules/unified/')
    || normalized.includes('/node_modules/vfile/')
    || normalized.includes('/node_modules/mdast-util-')
    || normalized.includes('/node_modules/hast-util-')
    || normalized.includes('/node_modules/micromark')
  ) {
    return 'pkg-markdown'
  }

  if (normalized.includes('/node_modules/@radix-ui/')) {
    return 'pkg-radix'
  }

  if (normalized.includes('/node_modules/cmdk/')) {
    return 'pkg-cmdk'
  }

  if (normalized.includes('/node_modules/react-dom/')) {
    return 'pkg-react-dom'
  }

  if (
    normalized.includes('/node_modules/framer-motion/')
    || normalized.includes('/node_modules/motion-dom/')
    || normalized.includes('/node_modules/motion-utils/')
  ) {
    return 'pkg-motion'
  }

  if (
    normalized.includes('/node_modules/react-router/')
    || normalized.includes('/node_modules/react-router-dom/')
  ) {
    return 'pkg-react-router'
  }

  if (normalized.includes('/node_modules/@tanstack/')) {
    return 'pkg-tanstack'
  }

  if (normalized.includes('/node_modules/axios/')) {
    return 'pkg-axios'
  }

  return undefined
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          return vendorChunkName(id)
        },
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})
