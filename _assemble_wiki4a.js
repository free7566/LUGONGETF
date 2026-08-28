// Assemble wiki4a.html from wiki4a_template.html + DATA (from strategy-4asset.html) + EXTRA (from strategy_extra.json)
const fs = require('fs');

const tpl = fs.readFileSync('wiki4a_template.html', 'utf8');
const html = fs.readFileSync('strategy-4asset.html', 'utf8');

// extract DATA from strategy-4asset.html
const marker = 'const DATA = ';
const s0 = html.indexOf(marker);
if (s0 < 0) throw new Error('cannot find "const DATA = "');
const start = s0 + marker.length;
let depth = 0, end = -1;
for (let i = start; i < html.length; i++) {
  const ch = html[i];
  if (ch === '{') depth++;
  else if (ch === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
}
const dataStr = html.slice(start, end);
JSON.parse(dataStr); // validate

const extra = JSON.parse(fs.readFileSync('strategy_extra.json', 'utf8'));
const EXTRA = extra.EXTRA;

let out = tpl
  .replace('__DATA__', dataStr)
  .replace('__EXTRA__', JSON.stringify(EXTRA));

if (out.includes('__DATA__') || out.includes('__EXTRA__')) throw new Error('placeholder not fully replaced');
fs.writeFileSync('wiki4a.html', out);
console.log('=== wiki assembly done ===');
console.log('output bytes:', out.length);
console.log('DATA keys ok, EXTRA keys:', Object.keys(EXTRA).join(','));
