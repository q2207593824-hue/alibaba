const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopEnv', {
  isElectron: true,
  waitBackendReady: (timeoutMs = 60000) => ipcRenderer.invoke('desktop:waitBackendReady', timeoutMs),
  restartBackend: () => ipcRenderer.invoke('desktop:restartBackend'),
  getRuntimeInfo: () => ipcRenderer.invoke('desktop:getRuntimeInfo'),
  exportRuntimeLog: () => ipcRenderer.invoke('desktop:exportRuntimeLog'),
  openAlibabaLoginAndGetCookies: (payload) => ipcRenderer.invoke('desktop:openAlibabaLoginAndGetCookies', payload || {}),
  /** 主进程代理云端请求，绕过渲染进程的 Clash/代理拦截 */
  cloudRequest: (payload) => ipcRenderer.invoke('desktop:cloudRequest', payload || {}),
});
