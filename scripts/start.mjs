import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn } from 'node:child_process'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const electron = join(root, 'node_modules', 'electron', 'dist', process.platform === 'win32' ? 'electron.exe' : 'electron')
if (!existsSync(electron) || !existsSync(join(root, 'dist', 'index.html'))) {
  console.error('Please run scripts/setup.ps1 before starting Qiban.')
  process.exit(1)
}
const child = spawn(electron, [join(root, 'desktop', 'main.cjs')], { cwd: root, windowsHide: true, detached: true, stdio: 'ignore' })
child.on('error', error => { console.error(error.message); process.exitCode = 1 })
child.unref()
