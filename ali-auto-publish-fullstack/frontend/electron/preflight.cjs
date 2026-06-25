const fs = require('fs');
const path = require('path');

function fail(msg) {
  console.error(`\n[desktop preflight] ${msg}\n`);
  process.exit(1);
}

const backendDist = path.join(__dirname, '..', '..', 'backend', 'dist');
const exeName = process.platform === 'win32' ? 'ali-backend.exe' : 'ali-backend';
const serviceExeName = process.platform === 'win32' ? 'ali-backend-service.exe' : 'ali-backend-service';
const exeCandidates = [
  path.join(backendDist, 'ali-backend', exeName),
  path.join(backendDist, exeName),
];
const exePath = exeCandidates.find((p) => fs.existsSync(p));
const serviceExePath = path.join(backendDist, serviceExeName);

if (!fs.existsSync(backendDist)) {
  fail(`后端打包目录不存在: ${backendDist}\n请先执行: pnpm run desktop:build:backend`);
}

if (!exePath) {
  const list = fs.readdirSync(backendDist, { withFileTypes: true }).map((d) => d.name).join(', ') || '(empty)';
  fail(`未找到后端可执行文件: ${exeCandidates.join(' 或 ')}\n当前目录内容: ${list}\n请先执行: pnpm run desktop:build:backend`);
}

if (process.platform === 'win32' && !fs.existsSync(serviceExePath)) {
  const list = fs.readdirSync(backendDist, { withFileTypes: true }).map((d) => d.name).join(', ') || '(empty)';
  fail(`未找到后端服务可执行文件: ${serviceExePath}\n当前目录内容: ${list}\n请先执行: pnpm run desktop:build:backend`);
}

console.log(`[desktop preflight] ok: ${exePath}`);
if (process.platform === 'win32') {
  console.log(`[desktop preflight] ok: ${serviceExePath}`);
}
process.exit(0);
