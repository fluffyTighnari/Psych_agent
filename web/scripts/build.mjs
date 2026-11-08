import { execFileSync } from 'node:child_process'
import { realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = realpathSync(path.resolve(here, '..'))
process.chdir(root)

// 项目目录可能通过 C:\ 的链接访问，而实际文件在 D:\；
// Vite 需要从 realpath 目录启动，否则 index.html 会被当成绝对路径资源。
const viteBin = path.join(root, 'node_modules', 'vite', 'bin', 'vite.js')
execFileSync(process.execPath, [viteBin, 'build'], { stdio: 'inherit' })
