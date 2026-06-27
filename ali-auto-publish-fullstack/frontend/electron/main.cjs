const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, execSync } = require('child_process');
const SERVICE_NAME = 'AliAutoPublishBackend';

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
  process.exit(0);
}
app.on('second-instance', () => {
  const wins = BrowserWindow.getAllWindows();
  if (!wins.length) return;
  const win = wins[0];
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
});

// 避免 Clash 等代理劫持 127.0.0.1 / localhost，导致「进程在但连不上」
app.commandLine.appendSwitch('proxy-bypass-list', '<-loopback>;127.0.0.1;localhost;echo-yiwu.cloud');

const CLOUD_PUBLIC_HOST = process.env.CLOUD_MEMBERSHIP_PUBLIC_HOST || 'echo-yiwu.cloud';
const CLOUD_REAL_IP = process.env.CLOUD_MEMBERSHIP_API_IP || '43.164.196.172';
// 强制把会员域名解析到真实 IP，绕过 Clash 假 DNS（198.18.x.x）
if (CLOUD_PUBLIC_HOST && CLOUD_REAL_IP) {
  app.commandLine.appendSwitch('host-resolver-rules', `MAP ${CLOUD_PUBLIC_HOST} ${CLOUD_REAL_IP}`);
}

const isDev = !!process.env.ELECTRON_DEV || !app.isPackaged;
const isPortableRuntime = app.isPackaged && !!(process.env.PORTABLE_EXECUTABLE_DIR || process.env.PORTABLE_EXECUTABLE_FILE);
const backendPort = process.env.BACKEND_PORT || '8000';
const frontendPort = process.env.FRONTEND_PORT || '3000';
/** 本机 backend 请求云端时用域名（Python 侧仍有 IP 回退）；勿默认 IP，避免与浏览器 curl 行为不一致 */
const defaultCloudMembershipBase =
  process.env.CLOUD_MEMBERSHIP_API_BASE || 'https://echo-yiwu.cloud/api/membership';
const defaultCloudPublicHost = process.env.CLOUD_MEMBERSHIP_PUBLIC_HOST || 'echo-yiwu.cloud';
let backendProc = null;
let backendStartInFlight = null;

function loadDesktopDeploySecrets() {
  const candidates = [
    path.join(__dirname, 'desktop.deploy.json'),
  ];
  if (app.isPackaged && process.resourcesPath) {
    candidates.push(path.join(process.resourcesPath, 'desktop.deploy.json'));
  }
  try {
    candidates.push(path.join(getUserDataRoot(), 'desktop.deploy.json'));
  } catch (_) {}
  for (const deployPath of candidates) {
    try {
      if (!deployPath || !fs.existsSync(deployPath)) continue;
      const raw = JSON.parse(fs.readFileSync(deployPath, 'utf-8'));
      if (raw && typeof raw === 'object' && String(raw.admin_api_key || '').trim()) {
        return raw;
      }
    } catch (_) {}
  }
  return {};
}

function seedDesktopDeployFile() {
  try {
    const secrets = loadDesktopDeploySecrets();
    const adminKey = String(secrets.admin_api_key || '').trim();
    if (!adminKey || adminKey === 'change-me-admin') return;
    const target = path.join(getUserDataRoot(), 'desktop.deploy.json');
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const payload = { admin_api_key: adminKey };
    if (fs.existsSync(target)) {
      const cur = JSON.parse(fs.readFileSync(target, 'utf-8'));
      if (String(cur?.admin_api_key || '').trim() === adminKey) return;
    }
    fs.writeFileSync(target, JSON.stringify(payload, null, 2), 'utf-8');
    pushLog('INFO', '[deploy] seeded desktop.deploy.json to user data');
  } catch (e) {
    pushLog('ERROR', `[deploy] seed failed: ${String(e?.message || e)}`);
  }
}

function getBackendChildEnv() {
  const desktopDeploySecrets = loadDesktopDeploySecrets();
  const existingNoProxy = String(process.env.NO_PROXY || process.env.no_proxy || '').trim();
  const mergedNoProxy = existingNoProxy
    ? `${existingNoProxy},127.0.0.1,localhost,echo-yiwu.cloud`
    : '127.0.0.1,localhost,echo-yiwu.cloud';
  const desktopDataDir = path.join(getUserDataRoot(), 'data');
  const driverCacheDir = path.join(getUserDataRoot(), 'chromedriver');
  const bundledDriver = process.resourcesPath
    ? path.join(process.resourcesPath, 'chromedriver', 'chromedriver.exe')
    : '';
  try {
    fs.mkdirSync(desktopDataDir, { recursive: true });
    fs.mkdirSync(driverCacheDir, { recursive: true });
  } catch (_) {}
  // 保留系统代理能力（企业网/需代理出网），由 backend 内 _cloud_http_request 自适应直连/代理/IP 回退
  const disableProxy = String(process.env.ALI_DESKTOP_DISABLE_PROXY || '1').trim() === '1';
  return {
    ...process.env,
    PYTHONIOENCODING: 'utf-8',
    ALI_DESKTOP: '1',
    // 安装版/免安装版统一写到用户目录，避免 Program Files/解包目录无写权限导致后端启动失败
    ALI_APP_DATA_DIR: process.env.ALI_APP_DATA_DIR || desktopDataDir,
    WDM_LOCAL: process.env.WDM_LOCAL || path.join(driverCacheDir, 'wdm'),
    CHROME_DRIVER_PATH:
      process.env.CHROME_DRIVER_PATH ||
      (bundledDriver && fs.existsSync(bundledDriver) ? bundledDriver : ''),
    BACKEND_PORT: String(backendPort),
    CLOUD_MEMBERSHIP_API_BASE: defaultCloudMembershipBase,
    CLOUD_MEMBERSHIP_PUBLIC_HOST: defaultCloudPublicHost,
    CLOUD_MEMBERSHIP_API_IP: process.env.CLOUD_MEMBERSHIP_API_IP || '43.164.196.172',
    ALI_ADMIN_API_KEY:
      process.env.ALI_ADMIN_API_KEY ||
      String(desktopDeploySecrets.admin_api_key || '').trim(),
    MEMBERSHIP_POINTS_SOURCE: process.env.MEMBERSHIP_POINTS_SOURCE || 'cloud',
    MEMBERSHIP_GUARD_CLOUD_OVERRIDE: process.env.MEMBERSHIP_GUARD_CLOUD_OVERRIDE || '1',
    // 云端接口在弱网/跨网环境下波动较大，桌面端默认放宽超时，降低“可用但偶发失败”概率
    CLOUD_LOGIN_CONNECT_TIMEOUT_SEC: process.env.CLOUD_LOGIN_CONNECT_TIMEOUT_SEC || '8',
    CLOUD_LOGIN_READ_TIMEOUT_SEC: process.env.CLOUD_LOGIN_READ_TIMEOUT_SEC || '45',
    CLOUD_ME_CONNECT_TIMEOUT_SEC: process.env.CLOUD_ME_CONNECT_TIMEOUT_SEC || '8',
    CLOUD_ME_READ_TIMEOUT_SEC: process.env.CLOUD_ME_READ_TIMEOUT_SEC || '30',
    CLOUD_MEMBERSHIP_API_IP: process.env.CLOUD_MEMBERSHIP_API_IP || '43.164.196.172',
    NO_PROXY: mergedNoProxy,
    no_proxy: mergedNoProxy,
    // 客户机常见系统代理/安全软件代理会导致会员云端请求失败；
    // 桌面端默认禁用代理转发，仅保留 NO_PROXY 直连。
    HTTP_PROXY: disableProxy ? '' : (process.env.HTTP_PROXY || ''),
    HTTPS_PROXY: disableProxy ? '' : (process.env.HTTPS_PROXY || ''),
    ALL_PROXY: disableProxy ? '' : (process.env.ALL_PROXY || ''),
    http_proxy: disableProxy ? '' : (process.env.http_proxy || ''),
    https_proxy: disableProxy ? '' : (process.env.https_proxy || ''),
    all_proxy: disableProxy ? '' : (process.env.all_proxy || ''),
  };
}
const runtimeLogs = [];
const MAX_LOGS = 1500;

function pushLog(level, text) {
  const line = `[${new Date().toISOString()}] [${level}] ${text}`;
  runtimeLogs.push(line);
  if (runtimeLogs.length > MAX_LOGS) runtimeLogs.shift();
  if (level === 'ERROR') console.error(line);
  else console.log(line);
}

function logWindowState(win, label) {
  try {
    const b = win.getBounds();
    const wb = win.getNormalBounds?.() || null;
    const dd = win.getContentBounds?.() || null;
    const display = require('electron').screen.getDisplayMatching(b);
    const workArea = display?.workArea || null;
    pushLog('INFO', `[window] ${label} bounds=${JSON.stringify(b)} normal=${JSON.stringify(wb)} content=${JSON.stringify(dd)} workArea=${JSON.stringify(workArea)} display=${JSON.stringify(display?.bounds || null)} primary=${!!display?.primary}`);
  } catch (e) {
    pushLog('ERROR', `[window] ${label} logWindowState failed: ${String(e?.message || e)}`);
  }
}

function getUserDataRoot() {
  return path.join(app.getPath('appData'), 'AliAutoPublish');
}

function getRuntimeLogPath() {
  return path.join(getUserDataRoot(), 'runtime.log');
}

function flushLogsToFile() {
  try {
    const p = getRuntimeLogPath();
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, runtimeLogs.join('\n') + '\n', 'utf-8');
    return p;
  } catch (e) {
    console.error('[desktop] write log failed', e);
    return '';
  }
}

function getBackendCwd() {
  if (app.isPackaged) {
    const base = path.join(process.resourcesPath, 'backend-dist');
    const nested = path.join(base, 'ali-backend');
    if (fs.existsSync(nested)) return nested;
    return base;
  }
  return path.join(__dirname, '..', '..', 'backend');
}

function getBackendExecutablePath() {
  const cwd = getBackendCwd();
  const exeName = process.platform === 'win32' ? 'ali-backend.exe' : 'ali-backend';
  const direct = path.join(cwd, exeName);
  if (fs.existsSync(direct)) return direct;
  return path.join(cwd, 'ali-backend', exeName);
}

function getDevBackendArgs() {
  return ['run_backend.py'];
}

function showFatalDesktopError(title, detail) {
  pushLog('ERROR', `${title}: ${detail}`);
  try {
    dialog.showErrorBox(title, detail);
  } catch (_) {
    console.error(`${title}: ${detail}`);
  }
}

function spawnAndLog(cmd, args, opts = {}) {
  const p = spawn(cmd, args, {
    windowsHide: true,
    ...opts,
  });

  p.stdout?.on('data', (d) => {
    const msg = String(d || '').trim();
    if (msg) pushLog('INFO', `[proc:${cmd}] ${msg}`);
  });
  p.stderr?.on('data', (d) => {
    const msg = String(d || '').trim();
    if (msg) pushLog('ERROR', `[proc:${cmd}] ${msg}`);
  });
  p.on('error', (err) => {
    pushLog('ERROR', `[proc:${cmd}] error: ${String(err?.message || err)}`);
  });
  return p;
}

function isBackendChildAlive() {
  return !!(backendProc && backendProc.exitCode === null && !backendProc.killed);
}

function killBackendProcess() {
  if (backendProc && !backendProc.killed) {
    try {
      backendProc.kill();
    } catch (_) {}
  }
  backendProc = null;
}

function freeBackendPortWin() {
  if (process.platform !== 'win32') return;
  try {
    execSync('taskkill /F /IM ali-backend.exe /T', { stdio: 'ignore', windowsHide: true });
  } catch (_) {}
  try {
    const out = execSync(`netstat -ano | findstr ":${backendPort}" | findstr LISTENING`, {
      encoding: 'utf8',
      windowsHide: true,
    });
    const pids = new Set();
    for (const line of out.split(/\r?\n/)) {
      const m = line.trim().match(/\s+(\d+)\s*$/);
      if (m && m[1] && m[1] !== '0') pids.add(m[1]);
    }
    for (const pid of pids) {
      try {
        execSync(`taskkill /F /PID ${pid} /T`, { stdio: 'ignore', windowsHide: true });
      } catch (_) {}
    }
    pushLog('INFO', `[backend] freed :${backendPort} pids=${[...pids].join(',') || 'none'}`);
  } catch (_) {}
}

async function probeDesktopBackendHealth() {
  try {
    const res = await fetch(`http://127.0.0.1:${backendPort}/api/health`, { cache: 'no-store' });
    if (!res.ok) return false;
    const body = await res.json();
    const svc = String(body?.service || '');
    // 勿把云端轻量 health（ali-membership-cloud）或半成品进程当成桌面后端就绪
    if (svc === 'ali-membership-cloud') return false;
    return svc === 'ali-auto-publish-backend';
  } catch (_) {
    return false;
  }
}

function restartPackagedBackend() {
  killBackendProcess();
  freeBackendPortWin();
  return startPackagedBackendFallback();
}

function startBackendDevProcess() {
  const backendCwd = getBackendCwd();
  const projectVenvPython = path.join(backendCwd, 'venv', 'Scripts', 'python.exe');
  const pythonCmd = fs.existsSync(projectVenvPython)
    ? projectVenvPython
    : (process.env.PYTHON_CMD || 'python');
  pushLog('INFO', `[backend] dev python: ${pythonCmd}`);

  backendProc = spawnAndLog(pythonCmd, getDevBackendArgs(), {
    cwd: backendCwd,
    stdio: 'pipe',
    env: getBackendChildEnv(),
  });

  backendProc.on('exit', (code) => {
    pushLog('INFO', `[backend] dev process exited: ${code}`);
    backendProc = null;
  });
}

function startPackagedBackendFallback() {
  const exePath = getBackendExecutablePath();
  const backendCwd = getBackendCwd();

  if (!fs.existsSync(exePath)) {
    pushLog('ERROR', `[backend] fallback executable not found: ${exePath}`);
    return false;
  }

  pushLog('INFO', `[backend] fallback start: ${exePath}`);
  backendProc = spawnAndLog(exePath, [], {
    cwd: backendCwd,
    stdio: 'pipe',
    env: getBackendChildEnv(),
  });

  backendProc.on('exit', (code) => {
    pushLog('INFO', `[backend] fallback process exited: ${code}`);
    backendProc = null;
  });

  return true;
}

function tryStartWindowsService() {
  if (process.platform !== 'win32' || !app.isPackaged) return;

  const sc = spawnAndLog('sc', ['start', SERVICE_NAME], { stdio: 'pipe' });
  sc.on('exit', (code) => {
    pushLog('INFO', `[service] sc start ${SERVICE_NAME} exit=${code}`);
  });
}

async function ensureBackendRunning() {
  if (await probeDesktopBackendHealth()) {
    pushLog('INFO', `[backend] already running on 127.0.0.1:${backendPort}`);
    return;
  }

  if (backendStartInFlight) {
    await backendStartInFlight;
    return;
  }

  backendStartInFlight = (async () => {
    if (app.isPackaged) {
      if (isBackendChildAlive()) {
        pushLog('INFO', '[backend] child process already starting');
        return;
      }
      freeBackendPortWin();
      await new Promise((r) => setTimeout(r, 600));
      if (await probeDesktopBackendHealth()) {
        pushLog('INFO', `[backend] port ${backendPort} available after cleanup`);
        return;
      }
      const started = startPackagedBackendFallback();
      if (!started && !isPortableRuntime) {
        tryStartWindowsService();
      }
      return;
    }

    if (isBackendChildAlive()) {
      pushLog('INFO', '[backend] dev process already starting');
      return;
    }
    startBackendDevProcess();
  })();

  try {
    await backendStartInFlight;
  } finally {
    backendStartInFlight = null;
  }
}

function stopBackend() {
  // 打包环境下后端由 Windows Service 管理，不在客户端退出时停止
  if (app.isPackaged) return;

  if (backendProc && !backendProc.killed) {
    backendProc.kill();
  }
  backendProc = null;
}

async function waitBackendReady(timeoutMs = 20000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await probeDesktopBackendHealth()) return true;
    await new Promise((r) => setTimeout(r, 400));
  }
  return false;
}

async function monitorBackendStartup(timeoutMs = 90000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await probeDesktopBackendHealth()) {
      pushLog('INFO', `[backend] ready at http://127.0.0.1:${backendPort}`);
      return true;
    }
    if (isBackendChildAlive()) {
      await new Promise((r) => setTimeout(r, 400));
      continue;
    }
    await new Promise((r) => setTimeout(r, 400));
  }

  if (await probeDesktopBackendHealth()) {
    pushLog('INFO', `[backend] ready at http://127.0.0.1:${backendPort}`);
    return true;
  }

  // 子进程仍在启动中（PyInstaller 首次解压较慢）— 禁止再起第二个 ali-backend.exe
  if (isBackendChildAlive()) {
    pushLog('INFO', '[backend] child still starting, waiting up to 120s (no duplicate spawn)');
    const extraOk = await waitBackendReady(120000);
    if (extraOk) {
      pushLog('INFO', `[backend] ready after slow start at http://127.0.0.1:${backendPort}`);
      return true;
    }
  }

  if (app.isPackaged && !isBackendChildAlive()) {
    pushLog('ERROR', '[backend] not ready, restarting packaged backend once');
    if (restartPackagedBackend()) {
      const ok = await waitBackendReady(60000);
      if (ok) {
        pushLog('INFO', `[backend] ready after restart at http://127.0.0.1:${backendPort}`);
        return true;
      }
    }
  }

  showFatalDesktopError(
    '本地服务启动异常',
    '请完全关闭软件后重新打开。\n若仍无法使用，请将本软件加入杀毒白名单后重试，或联系技术支持。'
  );
  return false;
}

async function createWindow() {
  const win = new BrowserWindow({
    width: 1366,
    height: 860,
    minWidth: 1200,
    minHeight: 760,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  });

  win.once('ready-to-show', () => {
    pushLog('INFO', '[window] ready-to-show');
    logWindowState(win, 'ready-to-show');
    if (!win.isDestroyed()) {
      win.show();
      win.focus();
    }
  });

  win.webContents.on('did-finish-load', () => {
    pushLog('INFO', `[window] did-finish-load: ${win.webContents.getURL()}`);
    logWindowState(win, 'did-finish-load');
  });

  win.webContents.on('did-fail-load', (_event, code, desc, url) => {
    pushLog('ERROR', `[window] did-fail-load code=${code} desc=${desc} url=${url}`);
    logWindowState(win, 'did-fail-load');
  });

  win.webContents.on('render-process-gone', (_event, details) => {
    pushLog('ERROR', `[window] render-process-gone: ${JSON.stringify(details || {})}`);
    logWindowState(win, 'render-process-gone');
  });

  pushLog('INFO', '[window] createWindow start');
  logWindowState(win, 'after-create');

  if (isDev) {
    pushLog('INFO', `[window] loading dev URL http://127.0.0.1:${frontendPort}`);
    try {
      await win.loadURL(`http://127.0.0.1:${frontendPort}`);
      pushLog('INFO', '[window] dev URL loaded');
      logWindowState(win, 'after-dev-load');
    } catch (e) {
      pushLog('ERROR', `dev server ${frontendPort} unavailable, fallback to backend static: ${String(e?.message || e)}`);
      pushLog('INFO', `[window] loading backend fallback URL http://127.0.0.1:${backendPort}`);
      await win.loadURL(`http://127.0.0.1:${backendPort}`);
      pushLog('INFO', '[window] backend fallback URL loaded');
      logWindowState(win, 'after-backend-load');
    }
  } else {
    // 打包环境直接加载内置前端，避免依赖后端托管静态资源
    await win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.whenReady().then(async () => {
  // 强制会员云端域名直连，绕过 Clash TUN 模式/系统代理拦截
  // PAC 脚本：echo-yiwu.cloud 和真实 IP 直连，其余走系统代理
  try {
    const { session } = require('electron');
    const cloudHost = CLOUD_PUBLIC_HOST || 'echo-yiwu.cloud';
    const cloudIp = CLOUD_REAL_IP || '43.164.196.172';
    await session.defaultSession.setProxy({
      mode: 'pac_script',
      pacScript: [
        'function FindProxyForURL(url, host) {',
        `  if (host === '${cloudHost}') return 'DIRECT';`,
        `  if (host === '${cloudIp}') return 'DIRECT';`,
        `  if (shExpMatch(host, '*.${cloudHost}')) return 'DIRECT';`,
        "  return 'SYSTEM';",
        '}',
      ].join('\n'),
    });
    pushLog('INFO', `[proxy] PAC script set: ${cloudHost} -> DIRECT, others -> SYSTEM`);
  } catch (e) {
    pushLog('ERROR', `[proxy] failed to set session proxy: ${String(e?.message || e)}`);
  }

  seedDesktopDeployFile();
  await ensureBackendRunning();


  // 先打开主界面，避免用户感知“卡启动”
  await createWindow();

  // 后端在后台继续就绪，不阻塞首屏展示
  monitorBackendStartup(90000).catch((e) => {
    pushLog('ERROR', `[backend] startup monitor failed: ${String(e?.message || e)}`);
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

ipcMain.handle('desktop:waitBackendReady', async (_evt, timeoutMs = 60000) => {
  return await waitBackendReady(Number(timeoutMs) || 60000);
});

ipcMain.handle('desktop:restartBackend', async () => {
  if (!app.isPackaged) return false;
  killBackendProcess();
  freeBackendPortWin();
  await new Promise((r) => setTimeout(r, 600));
  const started = restartPackagedBackend();
  if (!started) return false;
  return await waitBackendReady(60000);
});

ipcMain.handle('desktop:getRuntimeInfo', async () => {
  const logPath = flushLogsToFile();
  return {
    appVersion: app.getVersion(),
    backendPort,
    isPackaged: app.isPackaged,
    logPath,
    recentLogs: runtimeLogs.slice(-80),
  };
});

ipcMain.handle('desktop:exportRuntimeLog', async () => {
  const defaultPath = path.join(app.getPath('desktop'), `ali-auto-publish-runtime-${Date.now()}.log`);
  const result = await dialog.showSaveDialog({
    title: '导出运行日志',
    defaultPath,
    filters: [{ name: 'Log', extensions: ['log', 'txt'] }],
  });
  if (result.canceled || !result.filePath) return { ok: false, canceled: true };

  try {
    fs.writeFileSync(result.filePath, runtimeLogs.join('\n') + '\n', 'utf-8');
    return { ok: true, filePath: result.filePath };
  } catch (e) {
    return { ok: false, error: String(e?.message || e) };
  }
});

ipcMain.handle('desktop:openAlibabaLoginAndGetCookies', async (_evt, payload = {}) => {
  const loginUrl = String(payload?.loginUrl || '').trim() || 'https://login.alibaba.com/newlogin/icbuLogin.htm?defaultActive=signIn&return_url=https%3A%2F%2Fwww.alibaba.com%2F%3Fspm%3Da2700.login.0.0.483f71d2SGNvy3%26strategyId%3D106951%26resourcePositionTag%3Dtrue&_lang=en_US';
  pushLog('INFO', `[bind-store] open login requested: ${loginUrl}`);

  const win = new BrowserWindow({
    width: 1200,
    height: 860,
    show: true,
    autoHideMenuBar: true,
    title: '绑定店铺（请在此窗口登录阿里巴巴）',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  return await new Promise(async (resolve) => {
    let done = false;
    let pollTimer = null;

    const finish = async (ok, extra = {}) => {
      if (done) return;
      done = true;
      if (pollTimer) clearInterval(pollTimer);
      try {
        if (!win.isDestroyed()) win.close();
      } catch (_) {}
      resolve({ ok, ...extra });
    };

    const tryReadCookies = async () => {
      try {
        const ses = win.webContents.session;
        const currentUrl = win.webContents.getURL() || 'https://www.alibaba.com/';
        let cookies = [];

        try {
          cookies = await ses.cookies.get({ domain: '.alibaba.com' });
        } catch (_) {
          cookies = [];
        }
        if (!Array.isArray(cookies) || cookies.length === 0) {
          cookies = await ses.cookies.get({ url: currentUrl });
        }

        if (!Array.isArray(cookies) || cookies.length === 0) return false;

        const hasSessionCookie = cookies.some((c) => {
          const n = String(c?.name || '').toLowerCase();
          return n.includes('xman') || n.includes('ali_apache') || n.includes('acw_tc') || n.includes('cookie2') || n.includes('atpsida');
        });

        if (!hasSessionCookie) return false;

        await finish(true, {
          cookies,
          sourceUrl: currentUrl,
          count: cookies.length,
        });
        return true;
      } catch (_) {
        return false;
      }
    };

    win.on('closed', async () => {
      if (done) return;
      pushLog('INFO', '[bind-store] login window closed');
      const ok = await tryReadCookies();
      if (!ok) {
        await finish(false, { canceled: true, message: '窗口已关闭，未检测到可用登录Cookie' });
      }
    });

    try {
      pushLog('INFO', '[bind-store] loading login URL');
      logWindowState(win, 'login-before-load');
      await win.loadURL(loginUrl);
      pushLog('INFO', '[bind-store] login window opened');
      logWindowState(win, 'login-after-load');

      const timeoutAt = Date.now() + 5 * 60 * 1000;
      pollTimer = setInterval(async () => {
        if (done) return;
        if (Date.now() > timeoutAt) {
          await finish(false, { message: '登录超时（5分钟），请重试' });
          return;
        }
        await tryReadCookies();
      }, 1500);
    } catch (e) {
      await finish(false, { message: String(e?.message || e) });
    }
  });
});

/**
 * IPC: 主进程代理云端请求（绕过渲染进程的 Clash/代理拦截）
 * 使用 Node.js https 模块直接连接云端 ，不走 Chromium 网络栈
 * payload: { method, url, headers, body, timeoutMs }
 * 返回: { ok, status, headers, data, error }
 */
ipcMain.handle('desktop:cloudRequest', async (_evt, payload = {}) => {
  const https = require('https' );
  const http = require('http' );
  const { URL } = require('url');

  const method = String(payload?.method || 'GET').toUpperCase();
  const urlStr = String(payload?.url || '').trim();
  const reqHeaders = payload?.headers || {};
  const body = payload?.body ? JSON.stringify(payload.body) : null;
  const timeoutMs = Number(payload?.timeoutMs || 15000);

  if (!urlStr) return { ok: false, error: 'url is required' };

  return new Promise((resolve) => {
    try {
      const parsed = new URL(urlStr);
      const isHttps = parsed.protocol === 'https:';
      const transport = isHttps ? https : http;

      const options = {
        hostname: CLOUD_REAL_IP || parsed.hostname,
        port: parsed.port || (isHttps ? 443 : 80 ),
        path: parsed.pathname + (parsed.search || ''),
        method,
        headers: {
          'Host': parsed.hostname,
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          ...reqHeaders,
          ...(body ? { 'Content-Length': Buffer.byteLength(body) } : {}),
        },
        rejectUnauthorized: true,
      };

      pushLog('INFO', `[cloud-req] ${method} ${urlStr} -> ${options.hostname}:${options.port}${options.path}`);

      const req = transport.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => {
          pushLog('INFO', `[cloud-req] response ${res.statusCode} for ${urlStr}`);
          let parsed_data;
          try { parsed_data = JSON.parse(data); } catch { parsed_data = data; }
          resolve({
            ok: res.statusCode >= 200 && res.statusCode < 300,
            status: res.statusCode,
            headers: res.headers,
            data: parsed_data,
          });
        });
      });

      req.setTimeout(timeoutMs, () => {
        req.destroy();
        pushLog('ERROR', `[cloud-req] timeout after ${timeoutMs}ms for ${urlStr}`);
        resolve({ ok: false, error: `请求超时（${timeoutMs}ms）` });
      });

      req.on('error', (e) => {
        pushLog('ERROR', `[cloud-req] error for ${urlStr}: ${e.message}`);
        resolve({ ok: false, error: e.message, code: e.code });
      });

      if (body) req.write(body);
      req.end();
    } catch (e) {
      pushLog('ERROR', `[cloud-req] exception for ${urlStr}: ${String(e?.message || e)}`);
      resolve({ ok: false, error: String(e?.message || e) });
    }
  });
});




app.on('before-quit', () => {
  flushLogsToFile();
  stopBackend();
});
