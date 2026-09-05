// 打包后处理: 修正 exe 版本资源的文件说明 + 语言(中文)
// electron-builder 的 FileDescription 固定=productName, 语言默认 en-US, 配置无法覆盖
// 用法: node scripts/fix-exe-meta.js <exe路径> [文件说明]
//      node scripts/fix-exe-meta.js release/WeChatCollector.exe WeChatCollector
const fs = require('fs')
const path = require('path')

const exePath = process.argv[2]
const fileDesc = process.argv[3]

if (!exePath || !fs.existsSync(exePath)) {
  console.error('用法: node scripts/fix-exe-meta.js <exe路径> [文件说明]')
  process.exit(1)
}

const reseditPkg = path.join(__dirname, '..', 'frontend', 'electron', 'node_modules', 'resedit')
// resedit 支持 ESM/CJS; CJS 入口稳定选用
let ResEdit
try {
  ResEdit = require(reseditPkg)
} catch (e) {
  // dist/index.js 可能是 ESM, 回退到 require 内部 cjs
  ResEdit = require(path.join(reseditPkg, 'dist', 'index.js'))
}

// 中文(简体) + Unicode
const ZH_CS = 0x0804
const CP_UNICODE = 1200

function main() {
  const data = fs.readFileSync(exePath)
  const exe = ResEdit.NtExecutable.from(data)
  const res = ResEdit.NtExecutableResource.from(exe)
  const viList = ResEdit.Resource.VersionInfo.fromEntries(res.entries)
  if (viList.length === 0) {
    console.error('未找到版本信息资源:', exePath)
    process.exit(1)
  }
  // 优先取已是中文语言的条目, 否则取第一条(通常 en-US); 在单条上就地改
  const vi = viList.find((v) => Number(v.lang) === ZH_CS) || viList[0]
  const langs = vi.getAvailableLanguages()
  const srcLang = langs.length > 0 ? langs[0] : { lang: 0x0409, codepage: CP_UNICODE }
  const values = { ...vi.getStringValues(srcLang) }
  if (fileDesc) values.FileDescription = fileDesc
  if (Number(srcLang.lang) !== ZH_CS) {
    // 中文表写入(合并现有全部字段), 删旧语言表, 可用语言只留中文
    vi.setStringValues({ lang: ZH_CS, codepage: CP_UNICODE }, values, true)
    vi.removeAllStringValues(srcLang, false)
    vi.replaceAvailableLanguages([{ lang: ZH_CS, codepage: CP_UNICODE }])
    vi.lang = ZH_CS
  } else {
    vi.setStringValues({ lang: ZH_CS, codepage: CP_UNICODE }, values, false)
  }
  vi.outputToResourceEntries(res.entries)
  // 兜底: 只保留中文语言的版本资源条目
  res.entries = res.entries.filter((e) => !(Number(e.type) === 16 && Number(e.lang) !== ZH_CS))
  res.outputResource(exe)
  const out = exe.generate()
  fs.writeFileSync(exePath, Buffer.from(out))
  console.log(`✔ 已修正: ${exePath}`)
  console.log(`  语言 -> 中文(简体 0x0804), FileDescription -> "${fileDesc || '(未改)'}"`)
}

try {
  main()
} catch (e) {
  console.error('处理失败:', e.message)
  process.exit(1)
}