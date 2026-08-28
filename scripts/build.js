// 一键打包完整桌面应用到 release/
// 分层架构: 前端只管前端(electron-builder), 后端单独打包(PyInstaller), 根目录统一组装
// 用法:
//   npm run build          仅打包, 不清理中间产物(默认)
//   npm run build -- --clean   打包并清理全部中间产物(需显式确认)
// 流程: next静态导出 -> electron-builder(前端壳, 不含后端)
//     -> PyInstaller后端 -> 组装 release(移动前端+移动后端+复制模板库)
// 最终结构:
//   release\WeChatCollector.exe            (前端壳)
//   release\resources\backend\collector-backend.exe + _internal   (后端, 单独打包后移入)
//   release\data\collector.db              (模板库)
// 注意: 前端/后端产物是"移动"进 release 的, 不保留中间副本, 也不压缩 zip
const { execSync, spawn } = require('child_process')
const fs = require('fs')
const path = require('path')

const withClean = process.argv.includes('--clean')

const ROOT = path.join(__dirname, '..')
const RELEASE = path.join(ROOT, 'release')
const ELECTRON_DIR = path.join(ROOT, 'frontend', 'electron')
const ELECTRON_BUILD = path.join(ROOT, 'frontend', 'build')
const WIN_UNPACKED = path.join(ELECTRON_BUILD, 'win-unpacked')
const BACKEND_DIST = path.join(ROOT, 'backend', 'dist', 'collector-backend')   // PyInstaller onedir
const TPL_DB = path.join(ROOT, 'scripts', 'template_collector.db')

// 全部打包中间产物, 与 --clean 参数配套使用
const TRASH = [
  BACKEND_DIST,
  path.join(ROOT, 'backend', 'build'),
  path.join(ROOT, 'backend', 'collector-backend.spec'),
  path.join(ROOT, 'frontend', 'next', '.next'),
  path.join(ROOT, 'frontend', 'next', 'out'),
  path.join(ELECTRON_DIR, 'out'),
  ELECTRON_BUILD,
]

function run(cmd) {
  console.log(`\n>>> ${cmd}`)
  execSync(cmd, { stdio: 'inherit', cwd: ROOT })
}
// 异步并行执行(前端链/后端可同时打包); 输出带标签
function runAsync(cmd, label) {
  console.log(`\n>>> [${label}] ${cmd}`)
  return new Promise((res, rej) => {
    const p = spawn(cmd, { stdio: 'inherit', cwd: ROOT, shell: true })
    p.on('exit', (code) => (code === 0 ? res() : rej(new Error(cmd + ' 退出码 ' + code))))
    p.on('error', rej)
  })
}
function rmdir(p) {
  fs.rmSync(p, { recursive: true, force: true })
}
// 移动(非复制): src -> dst
function move(src, dst) {
  console.log(`\n>>> 移动: ${path.relative(ROOT, src)} -> ${path.relative(ROOT, dst)}`)
  rmdir(dst)
  fs.renameSync(src, dst)
}
// 清空 release 目录内所有条目
function clearRelease() {
  console.log('\n>>> 清空 release 目录')
  fs.mkdirSync(RELEASE, { recursive: true })
  for (const entry of fs.readdirSync(RELEASE)) {
    const p = path.join(RELEASE, entry)
    fs.rmSync(p, { recursive: true, force: true })
    console.log('   删除:', entry)
  }
}

async function main() {
const t0 = Date.now()
try {
  // ---- 1. 并行: 前端链(next->electron) 与 后端(PyInstaller) 同时打包 ----
  await Promise.all([
    (async () => {
      await runAsync('npm --prefix frontend/next run build', '前端-Next')
      await runAsync('node frontend/scripts/copy-out.js', '前端-静态页')
      await runAsync('npm --prefix frontend/electron run build', '前端-Electron')
    })(),
    runAsync('python backend/build_backend.py', '后端'),
  ])

  // ---- 2. 组装 release: 移动前端壳 + 移动后端 + 复制模板库 ----
  clearRelease()
  // 2.1 前端(win-unpacked 内容)整体移入 release 根
  for (const entry of fs.readdirSync(WIN_UNPACKED)) {
    fs.renameSync(path.join(WIN_UNPACKED, entry), path.join(RELEASE, entry))
  }
  // 2.2 后端移入 resources/backend(与 main.js process.resourcesPath 一致)
  move(BACKEND_DIST, path.join(RELEASE, 'resources', 'backend'))
  // 2.3 模板库 -> release/data
  console.log('\n>>> 复制模板数据库 -> release/data')
  fs.mkdirSync(path.join(RELEASE, 'data'), { recursive: true })
  fs.copyFileSync(TPL_DB, path.join(RELEASE, 'data', 'collector.db'))
  console.log('   template_collector.db -> release/data/collector.db')

  // 2.4 app-update.yml(自动更新必需)
  const updaterYml = 'owner: hong2301\n' +
    'provider: github\n' +
    'repo: wechat-article-collector\n' +
    'updaterCacheDirName: wechat-collector-electron-updater\n'
  const f = path.join(RELEASE, 'resources', 'app-update.yml')
  fs.mkdirSync(path.dirname(f), { recursive: true })
  fs.writeFileSync(f, updaterYml)
  console.log('   app-update.yml -> release/resources/app-update.yml')

  // ---- 3. 清理 ----
  if (withClean) {
    console.log('\n>>> 清理全部中间产物')
    for (const p of TRASH) {
      if (fs.existsSync(p)) { rmdir(p); console.log('   删除:', path.relative(ROOT, p)) }
    }
  } else {
    console.log('\n(中间产物已保留。如需清理请运行: npm run build -- --clean)')
  }

  console.log(`\n✅ 打包完成 (${((Date.now() - t0) / 1000).toFixed(0)}s)`)
  const exe = fs.readdirSync(RELEASE).find((f) => f.endsWith('.exe'))
  const dbOk = fs.existsSync(path.join(RELEASE, 'data', 'collector.db'))
  const be = fs.existsSync(path.join(RELEASE, 'resources', 'backend', 'collector-backend.exe'))
  const zipCount = fs.readdirSync(RELEASE).filter((f) => f.endsWith('.zip')).length
  console.log(`   目录: ${RELEASE}`)
  console.log(`   前端解包: ${exe || '(未找到!)'} | 后端: ${be ? '✓' : '✗'} | data: ${dbOk ? 'collector.db ✓' : '✗'} | zip: ${zipCount ? '✗(仍存在!)' : '不生成 ✓'}`)
} catch (e) {
  console.error('\n❌ 打包失败:', e.message.slice(0, 500))
  process.exit(1)
}
}
main()