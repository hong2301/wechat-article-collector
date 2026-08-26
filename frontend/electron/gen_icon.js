const { Resvg } = require('@resvg/resvg-js')
const fs = require('fs')
const path = require('path')

const svg = fs.readFileSync(path.join(__dirname, 'telescope.svg'), 'utf8')
const resvg = new Resvg(svg, { fitTo: { mode: 'width', value: 256 } })
const png = resvg.render().asPng()
fs.writeFileSync(path.join(__dirname, 'icon.png'), png)
console.log('icon.png 已生成', png.length)
