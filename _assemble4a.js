// Assemble final strategy-4asset.html from template4a.html
// Injects DATA + EXTRA + RAW from strategy_extra.json (single source of truth)
const fs = require('fs');

const tpl = fs.readFileSync('template4a.html', 'utf8');
const extra = JSON.parse(fs.readFileSync('strategy_extra.json', 'utf8'));
const DATA = extra.DATA;
const EXTRA = extra.EXTRA;
const RAW = extra.RAW;

// sanity
const reqDATA = ['meta', 'stats', 'equity', 'rotation', 'current', 'comparison', 'rot_only'];
for (const k of reqDATA) if (!(k in DATA)) throw new Error('DATA missing key: ' + k);
for (const k of ['annual', 'switchStats', 'cash', 'excess']) if (!(k in EXTRA)) throw new Error('EXTRA missing key: ' + k);
for (const k of ['dates', 'growth', 'value', 'ndx', 'a500', 'gold', 'cash', 'weights']) if (!(k in RAW)) throw new Error('RAW missing key: ' + k);

let out = tpl
  .replace('__DATA__', JSON.stringify(DATA))
  .replace('__EXTRA__', JSON.stringify(EXTRA))
  .replace('__RAW__', JSON.stringify(RAW));

if (out.includes('__DATA__') || out.includes('__EXTRA__') || out.includes('__RAW__'))
  throw new Error('placeholder not fully replaced');

fs.writeFileSync('strategy-4asset.html', out);
console.log('=== assembly done ===');
console.log('output bytes:', out.length);
console.log('DATA.stats:', JSON.stringify(DATA.stats));
console.log('comparison keys:', Object.keys(DATA.comparison).join(','));
console.log('current:', JSON.stringify(DATA.current));
