import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const katex = require('../vendor/katex.min.js');
if (process.argv.includes('--probe')) {
  console.log(JSON.stringify({ node: process.versions.node, katex: katex.version }));
} else {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const output = input.map(item => {
    try {
      return { html: katex.renderToString(item.tex, { displayMode: item.display,
        throwOnError: true, output: 'htmlAndMathml', trust: false,
        strict: 'ignore', maxExpand: 1000, maxSize: 20 }) };
    } catch (error) { return { error: String(error.message) }; }
  });
  process.stdout.write(JSON.stringify(output));
}
