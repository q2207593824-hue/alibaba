const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopEnv', {
  isElectron: true,
  waitBackendReady: (timeoutMs = 60000) => ipcRenderer.invoke('desktop:waitBackendReady', timeoutMs),
  restartBackend: () => ipcRenderer.invoke('desktop:restartBackend'),
  getRuntimeInfo: () => ipcRenderer.invoke('desktop:getRuntimeInfo'),
  exportRuntimeLog: () => ipcRenderer.invoke('desktop:exportRuntimeLog'),
  openAlibabaLoginAndGetCookies: (payload) => ipcRenderer.invoke('desktop:openAlibabaLoginAndGetCookies', payload || {}),
});
