import fs from 'node:fs'
import path from 'node:path'

const generatedPath = path.resolve('src/api/__generated__.ts')

function fail(message) {
  console.error(`[gen:api] ERROR: ${message}`)
  process.exit(1)
}

if (!fs.existsSync(generatedPath)) {
  fail('src/api/__generated__.ts is missing. Run `npm run gen:api`.')
}

const stat = fs.statSync(generatedPath)
if (!stat.isFile() || stat.size < 512) {
  fail('src/api/__generated__.ts is empty or unexpectedly small. Run `npm run gen:api`.')
}

const text = fs.readFileSync(generatedPath, 'utf8')
if (!text.includes('Study AI OpenAPI metadata')) {
  fail('src/api/__generated__.ts has no Study AI metadata header. Run `npm run gen:api`.')
}
if (!text.includes('export interface paths')) {
  fail('src/api/__generated__.ts does not contain OpenAPI paths. Run `npm run gen:api`.')
}

