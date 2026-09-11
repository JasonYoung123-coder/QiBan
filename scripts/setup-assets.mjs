import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const url = 'https://cubism.live2d.com/sdk-web/bin/CubismSdkForWeb-5-r.3.zip'
const archive = join(root, '.data', 'CubismSdkForWeb-5-r.3.zip')
await mkdir(dirname(archive), { recursive: true })
console.log('Preparing official Cubism Core and Hiyori sample for local evaluation.')
console.log('Model and runtime are separately licensed; see docs/ASSETS.md before redistribution.')
if (!existsSync(archive)) {
  const response = await fetch(url, { signal: AbortSignal.timeout(120000) })
  if (!response.ok) throw new Error(`SDK download returned ${response.status}`)
  const bytes = Buffer.from(await response.arrayBuffer())
  if (bytes.length > 150_000_000) throw new Error('SDK archive exceeds expected size')
  await writeFile(archive, bytes)
}
const hash = createHash('sha256').update(await readFile(archive)).digest('hex')
if (hash !== 'c70cc086950c7a318515e8ee606d8458a6dd2b96773fc2514ff67bf8a2d9ead7') {
  throw new Error('SDK archive checksum differs from the verified baseline; review the upstream release before updating.')
}
const python = process.env.QIBAN_PYTHON || join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const result = spawnSync(python, [join(root, 'scripts', 'extract-assets.py'), archive, root], { stdio: 'inherit' })
if (result.status !== 0) throw new Error('Asset extraction failed; run Python dependency setup first.')
await writeFile(join(root, '.data', 'assets-manifest.json'), JSON.stringify({
  sdk: 'CubismSdkForWeb-5-r.3', source: url, sha256: hash,
  model: 'Hiyori', license: 'Live2D Free Material + individual sample model terms',
}, null, 2))
console.log(`Assets ready. SDK SHA-256: ${hash}`)
