// 版本同步: release-it 升根 package.json 版本后, 同步其余 4 处版本号
// 用法: node scripts/sync-version.js
const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..')
const ver = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8')).version

// 1) JSON 类
for (const p of ['frontend/package.json', 'frontend/next/package.json', 'frontend/electron/package.json']) {
  const f = path.join(ROOT, p)
  const d = JSON.parse(fs.readFileSync(f, 'utf8'))
  if (d.version !== ver) {
    d.version = ver
    fs.writeFileSync(f, JSON.stringify(d, null, 2) + '\n')
    console.log(`  sync ${p} -> ${ver}`)
  }
}
// 2) 后端 FastAPI version
const py = path.join(ROOT, 'backend/app/main.py')
let s = fs.readFileSync(py, 'utf8')
s = s.replace(/version="[^"]*"/, `version="${ver}"`)
fs.writeFileSync(py, s)
console.log(`  sync backend/app/main.py -> ${ver}`)
console.log(`✅ 版本已统一为 ${ver}`)