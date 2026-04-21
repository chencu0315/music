const { contextBridge, ipcRenderer } = require('electron');
const { pathToFileURL } = require('node:url');

contextBridge.exposeInMainWorld('audioAPI', {
  openAudioFile: () => ipcRenderer.invoke('dialog:open-audio-file'),
  openMergeFile: () => ipcRenderer.invoke('dialog:open-merge-file'),
  splitSelection: (payload) => ipcRenderer.invoke('audio:split-selection', payload),
  deleteSelection: (payload) => ipcRenderer.invoke('audio:delete-selection', payload),
  exportAudio: (payload) => ipcRenderer.invoke('audio:export', payload),
  toFileUrl: (filePath) => pathToFileURL(filePath).href,
  onExportProgress: (callback) => {
    if (typeof callback !== 'function') {
      return () => {};
    }

    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on('audio:export-progress', listener);

    return () => {
      ipcRenderer.removeListener('audio:export-progress', listener);
    };
  },
});

