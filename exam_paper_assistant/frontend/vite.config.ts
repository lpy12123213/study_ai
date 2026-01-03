import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      // Fix broken entrypoints in `react-remove-scroll-bar@2.3.8` (it ships `dist/es2019/*` but points to `dist/es2015/*`).
      {
        find: /^react-remove-scroll-bar\/constants$/,
        replacement: path.resolve(
          __dirname,
          './node_modules/react-remove-scroll-bar/dist/es2019/constants.js',
        ),
      },
      {
        find: /^react-remove-scroll-bar$/,
        replacement: path.resolve(
          __dirname,
          './node_modules/react-remove-scroll-bar/dist/es2019/index.js',
        ),
      },
      // Fix broken `get-nonce@1.0.1` module field (ships only `dist/es5/*`).
      {
        find: /^get-nonce$/,
        replacement: path.resolve(__dirname, './node_modules/get-nonce/dist/es5/index.js'),
      },
      { find: '@', replacement: path.resolve(__dirname, './src') },
    ],
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
})
