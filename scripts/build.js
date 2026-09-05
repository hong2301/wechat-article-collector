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

// 打包日志镜像到 <data>/logs/build.log(与运行日志同目录, 不落根目录)
const __closeBuildLog = (() => {
  const dir = path.join(ROOT, 'data', 'logs')
  try { fs.mkdirSync(dir, { recursive: true }) } catch (e) {}
  let f = null
  try { f = fs.openSync(path.join(dir, 'build.log'), 'a') } catch (e) {}
  const wr = (...a) => { if (f) { try { fs.writeSync(f, a.join(' ') + '\n') } catch (e) {} } }
  const oLog = console.log, oErr = console.error
  console.log = (...a) => { oLog(...a); wr(...a) }
  console.error = (...a) => { oErr(...a); wr(...a) }
  return () => { if (f) { try { fs.closeSync(f) } catch (e) {} } }
})()
process.on('exit', __closeBuildLog)

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
  // Windows rename 偶发 EPERM(目录句柄未释放/杀软扫描): 自动重试 + 复制兜底
  for (let i = 0; i < 3; i++) {
    try {
      fs.renameSync(src, dst)
      return
    } catch (e) {
      if (i === 2) {
        console.log(`   rename 三次失败(${e.code}), 改为复制后删源`)
        fs.cpSync(src, dst, { recursive: true })
        try { fs.rmSync(src, { recursive: true, force: true }) } catch (e2) {
          console.warn('   复制完成, 但源目录删除失败(可手动清理):', path.relative(ROOT, src))
        }
        return
      }
      console.log(`   rename 第${i + 1}次失败(${e.code}), 0.5s 后重试`)
      const sab = new SharedArrayBuffer(4)
      Atomics.wait(new Int32Array(sab), 0, 0, 500)
    }
  }
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

// 打包前预检: 提前发现 release 被占用, 避免打包完成才卡在组装阶段
function preflightCheck() {
  console.log('\n>>> 预检 release 是否可写/可清空...')
  // 1) 正在运行的程序(会锁住 release 文件)
  for (const exe of ['WeChatCollector.exe', 'collector-backend.exe']) {
    try {
      const out = execSync(`tasklist /FI "IMAGENAME eq ${exe}" /FO CSV /NH`, { encoding: 'utf8', windowsHide: true })
      // 只统计真正含 exe 名进程的行(tasklist 无匹配时会输出 INFO: No tasks... 信息行, 不能算)
      const n = out.split(/\r?\n/).filter(l => l.toLowerCase().includes(exe.toLowerCase())).length
      if (n > 0) {
        console.error(`❌ 检测到 ${n} 个 ${exe} 正在运行, 会锁住 release 文件!`)
        console.error(`   请先关闭程序再打包 (或执行 taskkill /IM ${exe} /F 强制结束)`)
        process.exit(1)
      }
    } catch (e) { /* tasklist 失败则跳过进程检查 */ }
  }
  // 2) release 完整试清空: 真正删除现有内容, 精确暴露被锁文件(EPERM 根因)
  fs.mkdirSync(RELEASE, { recursive: true })
  const blocked = []
  for (const entry of fs.readdirSync(RELEASE)) {
    const p = path.join(RELEASE, entry)
    try {
      fs.rmSync(p, { recursive: true, force: true })
    } catch (e) {
      blocked.push(path.relative(ROOT, p))
    }
  }
  if (blocked.length) {
    console.error('❌ release 里以下文件/目录无法删除(被占用, 会导致打包中途失败):')
    for (const b of blocked) console.error('    - ' + b)
    console.error('   请关闭占用 release 的程序(测试中的采集器/资源管理器/杀软)后重试')
    process.exit(1)
  }
  // 3) 磁盘空间: release 所在盘至少留 1GB(前端包 ~260MB + 后端 ~150MB + 余量)
  try {
    const drive = path.parse(RELEASE).root.replace(/\\+$/, '')
    const out = execSync(
      `powershell -NoProfile -Command "(Get-PSDrive -Name '${drive[0]}' ).Free"`,
      { encoding: 'utf8', windowsHide: true })
    const free = Number((out.match(/\d+/) || ['0'])[0])
    if (free && free < 1024 * 1024 * 1024) {
      console.error(`❌ ${drive} 盘剩余空间不足 1GB(当前 ${(free / 1048576).toFixed(0)}MB), 打包产物无法放下!`)
      process.exit(1)
    }
    console.log(`   磁盘空间: ${(free / 1073741824).toFixed(2)}GB 可用`)
  } catch (e) { /* 空间检查失败则跳过 */ }
  // 4) 工具链与关键目录存在性(python/npm/node/源码/模板库)
  const needFiles = [
    ['backend/build_backend.py', '后端打包脚本'],
    ['frontend/next/package.json', '前端源码'],
    ['scripts/template_collector.db', '模板数据库'],
    ['scripts/fix-exe-meta.js', 'exe元数据脚本'],
  ]
  for (const [f, desc] of needFiles) {
    if (!fs.existsSync(path.join(ROOT, f))) {
      console.error(`❌ 缺少 ${desc}: ${f}`)
      process.exit(1)
    }
  }
  for (const [cmd, arg] of [['python', '-c pass'], ['node', '--version']]) {
    try { execSync(`${cmd} ${arg}`, { stdio: 'ignore', windowsHide: true }) }
    catch (e) {
      console.error(`❌ 命令不可用: ${cmd}, 无法打包!`)
      process.exit(1)
    }
  }
  const npmOk = (() => { try { execSync('npm --version', { stdio: 'ignore', windowsHide: true }); return true } catch { return false } })()
  if (!npmOk) { console.error('❌ npm 不可用, 无法打包!'); process.exit(1) }
  console.log('   预检通过: release 可清空 / 磁盘空间足 / 工具链齐全')
}

async function main() {
const t0 = Date.now()
try {
  // ---- 0. 预检: release 是否被占用(提前失败, 避免白打包) ----
  preflightCheck();

  // ---- 0.5 生成内置版本文件 version_info.py: 读根 .env(APP_VERSION/WECHAT_VERSION), 缺失回退根 package.json
  (() => {
    const envPath = path.join(ROOT, '.env')
    let appVer = '', wxVer = ''
    try {
      const envTxt = fs.readFileSync(envPath, 'utf-8')
      const mApp = envTxt.match(/^APP_VERSION\s*=\s*(.+)$/m)
      const mWx = envTxt.match(/^WECHAT_VERSION\s*=\s*(.+)$/m)
      if (mApp) appVer = mApp[1].trim()
      if (mWx) wxVer = mWx[1].trim()
    } catch (e) { /* .env 不存在, 用回退 */ }
    if (!appVer) {
      try { appVer = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf-8')).version || '' } catch (e) { appVer = '' }
    }
    const vi = `# -*- coding: utf-8 -*-
"""版本硬编码(构建时生成/覆盖): 由根目录 .env 的 APP_VERSION / WECHAT_VERSION 注入
- 构建: build.js 组装前读 .env(缺失回退根 package.json/TEMPLATE) 重写本文件, PyInstaller 打进 exe
- dev : 直接读本文件(提交的当前版本), 与打包版一致
- 数据库/接口不再存版本(从 settings 表剔除, 同步脚本删除)
"""
APP_VERSION = "${appVer}"       # 程序版本(单一来源: 根 .env APP_VERSION → 构建时写入)
WECHAT_VERSION = "${wxVer}"  # 微信基准版本(单一来源: 根 .env WECHAT_VERSION → 构建时写入)
`
    fs.writeFileSync(path.join(ROOT, 'backend', 'app', 'version_info.py'), vi)
    console.log(`
>>> 生成内置版本: APP_VERSION=${appVer} WECHAT_VERSION=${wxVer}`)
  })()

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
  // 2.3 模板库 -> release/data(先同步微信版本号: dev库 -> 模板库, 保证打包版版本号最新)
  console.log('\n>>> 复制模板数据库 -> release/data')
  fs.mkdirSync(path.join(RELEASE, 'data'), { recursive: true })
  fs.copyFileSync(TPL_DB, path.join(RELEASE, 'data', 'collector.db'))
  console.log('   template_collector.db -> release/data/collector.db')

  // 2.3b 客人卡密 -> release/guest.key(存在即永久授权; 与模板库同源 scripts/)
  const guestKey = path.join(ROOT, 'scripts', 'guest.key')
  if (fs.existsSync(guestKey)) {
    fs.copyFileSync(guestKey, path.join(RELEASE, 'guest.key'))
    console.log('   guest.key -> release/guest.key (客人卡密/永久授权)')
  } else {
    console.log('   (无 scripts/guest.key, 跳过客人卡密——正式版需卡密激活)')
  }

  // 2.4 app-update.yml(自动更新必需)
  const updaterYml = 'owner: hong2301\n' +
    'provider: github\n' +
    'repo: wechat-article-collector\n' +
    'updaterCacheDirName: wechat-collector-electron-updater\n'
  const f = path.join(RELEASE, 'resources', 'app-update.yml')
  fs.mkdirSync(path.dirname(f), { recursive: true })
  fs.writeFileSync(f, updaterYml)
  console.log('   app-update.yml -> release/resources/app-update.yml')

  // 2.5 修正 exe 版本资源: 文件说明=项目名 + 语言=中文(简体)
  //   electron-builder 只能写 productName/copyright/author, FileDescription 固定=productName、语言默认 en-US
  run(`node scripts/fix-exe-meta.js "${path.join(RELEASE, 'WeChatCollector.exe')}" 微信公众号文章与评论自动化采集工具`)

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