import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { defineConfig } from 'vitest/config'

function tsTranspilePlugin() {
  return {
    name: 'vitest-typescript-transpile',
    enforce: 'pre',
    transform(code, id) {
      const normalized = id.replace(/\\/g, '/')
      if (normalized.includes('/node_modules/')) return null
      if (!/\.[cm]?[tj]sx?$/.test(normalized)) return null

      const output = ts.transpileModule(code, {
        fileName: id,
        compilerOptions: {
          target: ts.ScriptTarget.ES2022,
          module: ts.ModuleKind.ESNext,
          moduleResolution: ts.ModuleResolutionKind.Bundler,
          jsx: ts.JsxEmit.ReactJSX,
          useDefineForClassFields: true,
          esModuleInterop: true,
          allowSyntheticDefaultImports: true,
          isolatedModules: true,
          sourceMap: true,
        },
      })

      return {
        code: output.outputText,
        map: output.sourceMapText ? JSON.parse(output.sourceMapText) : null,
      }
    },
  }
}

export default defineConfig({
  plugins: [tsTranspilePlugin()],
  esbuild: false,
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    fileParallelism: false,
    pool: 'threads',
    deps: {
      optimizer: {
        web: { enabled: false },
        ssr: { enabled: false },
      },
    },
  },
})
