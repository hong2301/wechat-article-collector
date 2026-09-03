// 发布前: 把 release/ 绿色版目录压缩为 zip(命名含版本号), 输出到 frontend/build-publish/
// 用法: node scripts/zip-release.js (release-it before:release 调用, 版本已 bump)
const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..')
const RELEASE = path.join(ROOT, 'release')
const OUT_DIR = path.join(ROOT, 'frontend', 'build-publish')
const ver = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8')).version
const zipName = `微信公众号采集器-${ver}-win.zip`
const out = path.join(OUT_DIR, zipName)

if (!fs.existsSync(RELEASE) || !fs.readdirSync(RELEASE).length) {
  console.error('release/ 目录为空, 请先执行打包(npm run build)')
  process.exit(1)
}
fs.mkdirSync(OUT_DIR, { recursive: true })
// 清掉旧版本同名模式产物(防残留)
for (const f of fs.readdirSync(OUT_DIR)) {
  if (f.startsWith('微信公众号采集器-') && f.endsWith('.zip')) {
    try { fs.rmSync(path.join(OUT_DIR, f), { force: true }) } catch (e) {}
  }
}
console.log(`>>> 压缩绿色版 -> ${zipName} (${(fs.statSync(RELEASE).size / 1048576).toFixed(0)}MB+ 压缩中...)`)
execSync(
  `powershell -NoProfile -Command "Compress-Archive -Path '${path.join(RELEASE, '*')}' -DestinationPath '${out}' -Force"`,
  { stdio: 'inherit', shell: true })
const mb = (fs.statSync(out).size / 1048576).toFixed(0)
console.log(`✅ 绿色版 zip 完成: ${zipName} (${mb}MB)`)