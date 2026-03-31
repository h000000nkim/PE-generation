// HWP → HTML 변환 스크립트
// Usage: node hwp_converter.js <input.hwp> [html|markdown]
const { toHtml, toMarkdown } = require('@ohah/hwpjs');
const fs = require('fs');

const [,, inputPath, format = 'html'] = process.argv;

if (!inputPath) {
  process.stderr.write('Usage: node hwp_converter.js <input.hwp> [html|markdown]\n');
  process.exit(1);
}

try {
  const buf = fs.readFileSync(inputPath);
  const result = format === 'markdown' ? toMarkdown(buf) : toHtml(buf);
  process.stdout.write(result);
} catch (e) {
  process.stderr.write(`Error: ${e.message}\n`);
  process.exit(1);
}
