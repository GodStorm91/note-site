#!/usr/bin/env node
import http from 'node:http';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = join(__dirname, '..');
const debugDir = join(projectRoot, 'bear-callback-debug');
mkdirSync(debugDir, { recursive: true });

const PORT = 58503; // match one of the ports grizzly tends to use; we can change later

const server = http.createServer((req, res) => {
  const { url, method } = req;
  const chunks = [];

  req.on('data', (c) => chunks.push(c));
  req.on('end', () => {
    const body = Buffer.concat(chunks).toString('utf8');

    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    const file = join(debugDir, `${ts}-${method}.log`);

    const payload = JSON.stringify({
      method,
      url,
      headers: req.headers,
      body,
    }, null, 2);

    writeFileSync(file, payload);
    console.log(`Saved callback payload → ${file}`);

    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('ok');
  });
});

server.listen(PORT, () => {
  console.log(`Bear callback server listening on http://127.0.0.1:${PORT}/`);
  console.log('Configure grizzly callback_url to use this.');
});
