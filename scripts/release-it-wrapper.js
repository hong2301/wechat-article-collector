// release-it 包装: 本地发版时自动从 gh CLI 取 token(gho_ 存钥匙串), 无需手动设环境变量
// 用法: npm run release [-- --increment patch|minor|major] 或 [-- 4.0.2]
const { execSync } = require('child_process')

// 1) 取 token: 优先环境变量, 否则从 gh CLI 取
let token = process.env.GH_TOKEN || process.env.GITHUB_TOKEN
if (!token) {
  try {
    token = execSync('gh auth token', { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch (e) {
    console.error('❌ 未找到 GH_TOKEN 且 gh CLI 未登录。')
    console.error('   方式1: 设环境变量 setx GH_TOKEN "ghp_..."')
    console.error('   方式2: gh auth login 登录后重试')
    process.exit(1)
  }
}
if (!token) { console.error('❌ 获取 token 为空'); process.exit(1) }

// 2) 携带 token 运行 release-it(release-it github 插件读 GITHUB_TOKEN)
const args = process.argv.slice(2).join(' ')
try {
  execSync(`npx release-it ${args}`, {
    stdio: 'inherit',
    shell: true,
    env: { ...process.env, GH_TOKEN: token, GITHUB_TOKEN: token },
  })
} catch (e) {
  process.exit(e.status ?? 1)
}