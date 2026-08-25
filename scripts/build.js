// 一键打包完整桌面应用(前端 + Electron + Python后端) 到 release/
// 用法:
//   npm run build          仅打包, 不清理中间产物(默认)
//   npm run build -- --clean   打包并清理全部中间产物(需显式确认)
// 流程: next静态导出 -> PyInstaller后端 -> electron-builder -> 组装 release -> (可选)清理
// 最终结构:
//   release\WeChatCollector.exe
//   release\data\collector.db   (模板库: 保留点位/滚动/AI配置, 敏感值清空)
const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const withClean = process.argv.includes('--clean')

const ROOT = path.join(__dirname, '..')
const RELEASE = 'C:/Users/86150/Desktop/微信公众号ocr采集器/release'
const ELECTRON_DIR = path.join(ROOT, 'frontend', 'electron')
const ELECTRON_BUILD = path.join(ROOT, 'frontend', 'build')          // electron-builder 中间输出
const WIN_UNPACKED = path.join(ELECTRON_BUILD, 'win-unpacked')
const BACKEND_DIST = path.join(ROOT, 'backend', 'dist', 'collector-backend')
const EXTRA_BACKEND = path.join(ELECTRON_DIR, 'extra', 'backend')

// 全部中间产物(前端两个框架 + 后端), 与 --clean 参数配套使用
const TRASH = [
  // Python 后端 (PyInstaller)
  BACKEND_DIST,
  path.join(ROOT, 'backend', 'build'),
  path.join(ROOT, 'backend', 'collector-backend.spec'),
  // Next.js 前端
  path.join(ROOT, 'frontend', 'next', '.next'),
  path.join(ROOT, 'frontend', 'next', 'out'),
  // Electron 前端
  path.join(ELECTRON_DIR, 'out'),
  path.join(ELECTRON_DIR, 'extra'),
  ELECTRON_BUILD,
]

function run(cmd) {
  console.log(`\n>>> ${cmd}`)
  execSync(cmd, { stdio: 'inherit', cwd: ROOT })
}
function rmdir(p) {
  fs.rmSync(p, { recursive: true, force: true })
}
function copy(src, dst) {
  console.log(`\n>>> 复制: ${path.relative(ROOT, src)} -> ${path.relative(ROOT, dst)}`)
  rmdir(dst)
  fs.cpSync(src, dst, { recursive: true })
}

const t0 = Date.now()
try {
  // 1. Next.js 静态导出 (output: export -> next/out)
  run('npm --prefix frontend/next run build')

  // 2. 静态页复制到 electron/out
  run('node frontend/scripts/copy-out.js')

  // 3. Python 后端 PyInstaller onedir
  run('python backend/build_backend.py')

  // 4. 后端产物复制进 electron-builder 的 extraResources 区(须在 app 目录内)
  copy(BACKEND_DIST, EXTRA_BACKEND)

  // 5. electron-builder 打包 -> frontend/build/win-unpacked
  run('npm --prefix frontend/electron run build')

  // 6. 组装 release: 清空 -> 平铺 win-unpacked -> 放模板数据库
  console.log('\n>>> 组装 release 目录')
  fs.mkdirSync(RELEASE, { recursive: true })
  for (const entry of fs.readdirSync(RELEASE)) {
    rmdir(path.join(RELEASE, entry))
  }
  for (const entry of fs.readdirSync(WIN_UNPACKED)) {
    fs.cpSync(path.join(WIN_UNPACKED, entry), path.join(RELEASE, entry), { recursive: true })
  }

  // 7. 生成模板数据库到 release/data
  run(`python scripts/make_template_db.py "${RELEASE}/data"`)

  // 8. 清理中间产物(仅在有 --clean 参数时执行, 默认保留)
  if (withClean) {
    console.log('\n>>> 清理全部中间产物(前端Next/Electron + 后端)')
    for (const p of TRASH) {
      if (fs.existsSync(p)) {
        rmdir(p)
        console.log('   删除:', path.relative(ROOT, p))
      }
    }
  } else {
    console.log('\n(中间产物已保留。如需清理请运行: npm run build -- --clean)')
  }

  console.log(`\n✅ 打包完成 (${((Date.now() - t0) / 1000).toFixed(0)}s)`)

  // 9. 汇总
  const exe = fs.readdirSync(RELEASE).find((f) => f.endsWith('.exe'))
  const db = fs.existsSync(path.join(RELEASE, 'data', 'collector.db'))
  console.log(`   目录: ${RELEASE}`)
  console.log(`   exe : ${exe || '(未找到!)'}`)
  console.log(`   data: ${db ? 'collector.db ✓' : '(缺失!)'}`)
} catch (e) {
  console.error('\n❌ 打包失败:', e.message.slice(0, 500))
  process.exit(1)
}