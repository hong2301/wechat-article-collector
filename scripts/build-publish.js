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

function getToken() {
  // 发布需要 GH_TOKEN(env 或 gh CLI)
  if (process.env.GH_TOKEN || process.env.GITHUB_TOKEN) return process.env.GH_TOKEN || process.env.GITHUB_TOKEN
  try {
    return execSync('gh auth token', { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch (e) { return '' }
}

function run(cmd, cwd, env) {
  console.log("\n>>> " + cmd)
  execSync(cmd, { stdio: 'inherit', cwd, shell: true, env: { ...process.env, ...(env || {}) } })
}

const TOKEN = getToken()
if (!TOKEN) {
  console.error('❌ 未找到 GH_TOKEN(设 GH_TOKEN 或 gh auth login)')
  process.exit(1)
}

// ① 后段 PyInstaller(产出 backend/dist/collector-backend)
run('python backend/build_backend.py', ROOT)
if (!fs.existsSync(path.join(ROOT, 'backend', 'dist', 'collector-backend'))) {
  console.error('❌ 后端构建产物缺失 backend/dist/collector-backend')
  process.exit(1)
}

// ② electron-builder zip(整包, 含后段; publish=always 构建并上传 GitHub Release)
fs.rmSync(OUT, { recursive: true, force: true })
fs.mkdirSync(OUT, { recursive: true })
const rel = path.relative(path.join(FRONT, 'electron'), OUT).replace(/\\/g, '/')
run(`npx electron-builder --win nsis --publish always --config.directories.output="${rel}"`,
    path.join(FRONT, 'electron'), { GH_TOKEN: TOKEN, GITHUB_TOKEN: TOKEN })

const zip = fs.readdirSync(OUT).filter((f) => f.endsWith('.exe'))
const yml = fs.existsSync(path.join(OUT, 'latest.yml'))
if (!zip.length || !yml) {
  console.error('❌ 发布包不完整: 需要安装包exe + latest.yml', fs.readdirSync(OUT))
  process.exit(1)
}
console.log(`\n✅ 发布包完成: ${zip.join(', ')} + latest.yml @ ${OUT}`)