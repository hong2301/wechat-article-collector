// 发布专用构建: 完整包(壳 + 后段) -> 供 release-it 上传 GitHub Release assets
//  ① PyInstaller 打包后端 -> backend/dist/collector-backend
//  ② electron-builder --win zip(extraResources 已把后端打进 resources/backend)
//     -> frontend/build-publish/*.zip + latest.yml(自动更新可整包拉取)
const { execSync } = require('child_process')
const path = require('path')
const fs = require('fs')

const ROOT = path.join(__dirname, '..')
const FRONT = path.join(ROOT, 'frontend')
const OUT = path.join(FRONT, 'build-publish')

function run(cmd, cwd) {
  console.log(`\n>>> ${cmd}`)
  execSync(cmd, { stdio: 'inherit', cwd, shell: true })
}

// ① 后段 PyInstaller(产出 backend/dist/collector-backend)
run('python backend/build_backend.py', ROOT)
if (!fs.existsSync(path.join(ROOT, 'backend', 'dist', 'collector-backend'))) {
  console.error('❌ 后端构建产物缺失 backend/dist/collector-backend')
  process.exit(1)
}

// ② electron-builder zip(整包, 含后段; publish=never 只构建不上传)
fs.rmSync(OUT, { recursive: true, force: true })
fs.mkdirSync(OUT, { recursive: true })
const rel = path.relative(path.join(FRONT, 'electron'), OUT).replace(/\\/g, '/')
run(`npx electron-builder --win zip --publish never --config.directories.output="${rel}"`,
    path.join(FRONT, 'electron'))

const zip = fs.readdirSync(OUT).filter((f) => f.endsWith('.zip'))
const yml = fs.existsSync(path.join(OUT, 'latest.yml'))
if (!zip.length || !yml) {
  console.error('❌ 发布包不完整: 需要 zip + latest.yml', fs.readdirSync(OUT))
  process.exit(1)
}
console.log(`\n✅ 发布包完成: ${zip.join(', ')} + latest.yml @ ${OUT}`)