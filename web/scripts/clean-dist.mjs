import { execFileSync } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'dist')

if (!existsSync(dist)) {
  process.exit(0)
}

if (process.platform === 'win32') {
  // Vite 内置 rimraf 在本机删除大量字体文件时会留下 ENOTEMPTY；
  // PowerShell 的 Remove-Item 能稳定清掉同一目录。
  execFileSync(
    'powershell.exe',
    ['-NoProfile', '-Command', 'Remove-Item -LiteralPath $env:PSYCH_DIST -Recurse -Force'],
    { env: { ...process.env, PSYCH_DIST: dist }, stdio: 'inherit' },
  )
} else {
  rmSync(dist, { recursive: true, force: true })
}
