/**
 * Desktop build orchestrator — runs each step in a separate child process
 * to avoid Windows Node/libuv crash when chaining `vite build && ...` via pnpm.
 *
 * Windows notes:
 * - shell:true breaks paths with spaces (e.g. project folder "(3)")
 * - shell:false cannot spawn .cmd/.bat (pnpm.cmd → EINVAL)
 * → invoke vite / electron-builder / python via node or .exe directly
 */
const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const frontendRoot = path.join(__dirname, '..');
const backendRoot = path.join(frontendRoot, '..', 'backend');

function resolveToolBin(pkgName, binRel) {
  const direct = path.join(frontendRoot, 'node_modules', pkgName, binRel);
  if (fs.existsSync(direct)) return direct;
  try {
    return require.resolve(`${pkgName}/${binRel}`, { paths: [frontendRoot] });
  } catch (_) {
    throw new Error(`找不到 ${pkgName}/${binRel}，请先在 frontend 目录执行 pnpm install`);
  }
}

function runStep(label, cmd, args, opts = {}) {
  console.log(`\n==> ${label}`);
  const result = spawnSync(cmd, args, {
    cwd: opts.cwd || frontendRoot,
    stdio: 'inherit',
    shell: false,
    windowsHide: true,
    env: { ...process.env, ...opts.env },
  });
  if (result.error) {
    console.error(`[build-desktop] ${label} failed:`, result.error.message);
    process.exit(1);
  }
  if (result.status !== 0) {
    console.error(`[build-desktop] ${label} exited with code ${result.status}`);
    process.exit(result.status || 1);
  }
}

function runNodeTool(label, pkgName, binRel, args = [], opts = {}) {
  const script = resolveToolBin(pkgName, binRel);
  runStep(label, process.execPath, [script, ...args], opts);
}

function runBackendBuild() {
  const venvPy = path.join(backendRoot, 'venv', 'Scripts', 'python.exe');
  const py = fs.existsSync(venvPy) ? venvPy : 'python';
  const script = path.join(backendRoot, 'build_backend_exe.py');
  runStep('backend (PyInstaller)', py, [script], { cwd: backendRoot });
}

runNodeTool('web (vite)', 'vite', path.join('bin', 'vite.js'), ['build']);
runBackendBuild();
runStep('preflight', process.execPath, [path.join(__dirname, 'preflight.cjs')]);
runNodeTool('electron-builder', 'electron-builder', 'cli.js');

console.log('\n[build-desktop] All steps completed.');
