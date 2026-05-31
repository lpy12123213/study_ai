import fs from 'node:fs'
import path from 'node:path'

const generatedDir = path.resolve('src/api/__generated__')
const requiredFiles = ['components.ts', 'paths.ts', 'index.ts']

function fail(message) {
  console.error(`[gen:api] ERROR: ${message}`)
  process.exit(1)
}

if (!fs.existsSync(generatedDir) || !fs.statSync(generatedDir).isDirectory()) {
  fail('src/api/__generated__/ is missing. Run `npm run gen:api`.')
}

for (const file of requiredFiles) {
  const filePath = path.join(generatedDir, file)
  if (!fs.existsSync(filePath)) {
    fail(`src/api/__generated__/${file} is missing. Run \`npm run gen:api\`.`)
  }
  const stat = fs.statSync(filePath)
  if (!stat.isFile() || stat.size < 64) {
    fail(`src/api/__generated__/${file} is empty or unexpectedly small. Run \`npm run gen:api\`.`)
  }
}

const components = fs.readFileSync(path.join(generatedDir, 'components.ts'), 'utf8')
if (!components.includes('export interface components')) {
  fail('src/api/__generated__/components.ts does not contain OpenAPI components. Run `npm run gen:api`.')
}
if (!components.includes('export interface operations')) {
  fail('src/api/__generated__/components.ts does not contain OpenAPI operations. Run `npm run gen:api`.')
}

const paths = fs.readFileSync(path.join(generatedDir, 'paths.ts'), 'utf8')
if (!paths.includes('export interface paths')) {
  fail('src/api/__generated__/paths.ts does not contain OpenAPI paths. Run `npm run gen:api`.')
}

const index = fs.readFileSync(path.join(generatedDir, 'index.ts'), 'utf8')
if (!index.includes("export type { components, operations } from './components'")) {
  fail('src/api/__generated__/index.ts does not re-export components/operations. Run `npm run gen:api`.')
}
if (!index.includes("export type { paths } from './paths'")) {
  fail('src/api/__generated__/index.ts does not re-export merged paths. Run `npm run gen:api`.')
}
