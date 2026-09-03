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
// 3) 根 .env 的 APP_VERSION(版本硬编码来源, 构建时注入 version_info.py)
const envp = path.join(ROOT, '.env')
try {
  let e = fs.readFileSync(envp, 'utf8')
  if (/^APP_VERSION\s*=/.test(e)) e = e.replace(/^APP_VERSION\s*=.*$/m, `APP_VERSION=${ver}`)
  else e += `
APP_VERSION=${ver}`
  fs.writeFileSync(envp, e)
  console.log(`  sync .env APP_VERSION -> ${ver}`)
} catch (err) { console.log('  (跳过 .env: ' + err.message + ')') }
console.log(`✅ 版本已统一为 ${ver}`)