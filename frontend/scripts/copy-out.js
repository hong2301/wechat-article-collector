// 将 Next.js 静态导出产物 (next/out) 复制到 electron/out
// 原因: electron-builder 的 files 不允许引用 app 目录之外的文件
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const outSrc = path.join(root, 'next', 'out');
const outDst = path.join(root, 'electron', 'out');

if (!fs.existsSync(outSrc)) {
  console.error('[copy-out] 未找到 next/out，请先执行 npm run build:frontend');
  process.exit(1);
}

fs.rmSync(outDst, { recursive: true, force: true });
fs.cpSync(outSrc, outDst, { recursive: true });
console.log('[copy-out] next/out -> electron/out 完成');