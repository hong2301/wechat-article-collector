// 发布收尾: GitHub Release 转正式 + 校验资产齐全
// 在 release-it after:release 执行(electron-builder publish 已建 draft release 并上传)
const { execSync } = require('child_process')
const path = require('path')
const fs = require('fs')

const ROOT = path.join(__dirname, '..')
const REPO = 'hong2301/wechat-article-collector'
const PACKAGE = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'))
const VER = PACKAGE.version
const TAG = `v${VER}`

function run(cmd) {
  console.log(`>>> ${cmd}`)
  execSync(cmd, { stdio: 'inherit', shell: true })
}

try {
  // 1) 校验发布资产(安装包 exe + latest.yml 在 Release 上)
  const out = execSync(
    `gh release view ${TAG} --repo ${REPO} --json assets`,
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  const assets = JSON.parse(out).assets || []
  const names = assets.map((a) => a.name)
  console.log(`[release] v${VER} 资产:`, names.length ? names.join(', ') : '(暂无)')
  if (!names.some((n) => /setup.*\.exe|Setup.*exe/i.test(n))) {
    console.warn('⚠ 未找到安装包(exe)资产, 请检查上传')
  }
  if (!names.includes('latest.yml')) {
    console.warn('⚠ 未找到 latest.yml, 自动更新将不可用')
  }
  // 2) 转正式(draft -> false)
  run(`gh release edit ${TAG} --repo ${REPO} --draft=false`)
  console.log(`✅ Release ${TAG} 已正式发布`)
  run(`gh release view ${TAG} --repo ${REPO}`)
} catch (e) {
  console.error('❌ 发布收尾失败:', e.message)
  process.exit(e.status ?? 1)
}