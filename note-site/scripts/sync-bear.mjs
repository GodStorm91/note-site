#!/usr/bin/env node
import { execSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = join(__dirname, '..');
const outputDir = join(projectRoot, 'src', 'content', 'notes');

mkdirSync(outputDir, { recursive: true });

function run(cmd) {
  console.log(`$ ${cmd}`);
  return execSync(cmd, { encoding: 'utf8' });
}

console.log('> Sync Bear notes tagged #public → Markdown files...');

// Step 1: ask Bear to open the tag so the notes are visible / loaded
run('grizzly open-tag --name "public"');

// Step 2: list notes under that tag (as JSON)
// grizzly doesn't expose direct note export in one shot; to keep it simple v1,
// we'll assume you manually export notes you want public into src/content/notes.
// This script is currently a placeholder, because Bear's x-callback flow makes
// full automation a bit more involved (needs a local HTTP callback server).

console.log('\nHiện tại grizzly chỉ trả về URL x-callback (bear://...) chứ không trả list note dạng JSON sẵn.');
console.log('Để làm sync full auto, mình cần set callback server riêng (hơi overkill cho v1).');
console.log('\nV1 đề xuất:');
console.log('  • Mày vẫn gắn tag #public trong Bear');
console.log('  • Khi muốn publish, trong Bear: Export note → Markdown → lưu vào src/content/notes/');
console.log('  • Web sẽ auto build đẹp như giờ.');

console.log('\nNếu mày thật sự muốn chơi full auto với grizzly + callback server, tao sẽ design flow riêng (node server nhỏ) cho version sau.');
