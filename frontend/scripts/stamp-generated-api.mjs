import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const generatedPath = path.resolve('src/api/__generated__.ts')
const metadataRe = /^\/\*\*\n \* Study AI OpenAPI metadata\n \* Generated at: .+\n \* Git SHA: .+\n \*\/\n\n/u

function readTextIfExists(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8').trim()
  } catch {
    return ''
  }
}

function gitShaFromFiles(repoRoot) {
  const gitEntry = path.join(repoRoot, '.git')
  const gitEntryText = readTextIfExists(gitEntry)
  const gitDir = gitEntryText.startsWith('gitdir:')
    ? path.resolve(repoRoot, gitEntryText.slice('gitdir:'.length).trim())
    : gitEntry
  const head = readTextIfExists(path.join(gitDir, 'HEAD'))
  if (!head) return 'unknown'
  if (!head.startsWith('ref:')) return head.slice(0, 7)
  const refPath = head.slice('ref:'.length).trim()
  const refValue = readTextIfExists(path.join(gitDir, refPath))
  if (refValue) return refValue.slice(0, 7)
  const packedRefs = readTextIfExists(path.join(gitDir, 'packed-refs'))
  for (const line of packedRefs.split(/\r?\n/u)) {
    if (!line || line.startsWith('#') || line.startsWith('^')) continue
    const [sha, ref] = line.trim().split(/\s+/u)
    if (ref === refPath && sha) return sha.slice(0, 7)
  }
  return 'unknown'
}

function gitSha() {
  const repoRoot = path.resolve('..')
  try {
    return execFileSync('git', ['rev-parse', '--short', 'HEAD'], {
      cwd: repoRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
  } catch {
    return gitShaFromFiles(repoRoot)
  }
}

if (!fs.existsSync(generatedPath)) {
  console.error('[gen:api] ERROR: src/api/__generated__.ts is missing after generation.')
  process.exit(1)
}

const raw = fs.readFileSync(generatedPath, 'utf8')
if (!raw.includes('export interface paths')) {
  console.error('[gen:api] ERROR: generated API file does not contain OpenAPI paths.')
  process.exit(1)
}

const header = [
  '/**',
  ' * Study AI OpenAPI metadata',
  ` * Generated at: ${new Date().toISOString()}`,
  ` * Git SHA: ${gitSha()}`,
  ' */',
  '',
].join('\n')

const body = raw.replace(metadataRe, '')
fs.writeFileSync(generatedPath, `${header}\n${body}`, 'utf8')
