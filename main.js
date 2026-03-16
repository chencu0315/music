const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const fsp = require('node:fs/promises');

const ffmpeg = require('fluent-ffmpeg');
const rawFfmpegPath = require('ffmpeg-static');

const USER_DATA_DIR_NAME = 'LightAudioCutter';
const TEMP_ROOT_NAME = '.light-audio-cutter-temp';
const TEXT = {
  cannotCreateTempDir: '\u65e0\u6cd5\u521b\u5efa\u4e34\u65f6\u76ee\u5f55',
  stageStart: '\u5f00\u59cb...',
  stageProcessing: '\u5904\u7406\u4e2d...',
  stageDone: '\u5b8c\u6210',
  primaryAudioStage: '\u4e3b\u97f3\u9891\u5904\u7406',
  mergeAudioStage: '\u97f3\u9891\u5408\u5e76',
  missingSourcePath: '\u7f3a\u5c11\u4e3b\u97f3\u9891\u6587\u4ef6\u8def\u5f84',
  sourceFileMissing: '\u4e3b\u97f3\u9891\u6587\u4ef6\u4e0d\u5b58\u5728',
  mergeFileMissing: '\u5f85\u5408\u5e76\u6587\u4ef6\u4e0d\u5b58\u5728',
  invalidTrimRange: '\u4fee\u526a\u65f6\u95f4\u53c2\u6570\u65e0\u6548',
  trimEndBeforeStart: '\u4fee\u526a\u7ed3\u675f\u65f6\u95f4\u5fc5\u987b\u5927\u4e8e\u5f00\u59cb\u65f6\u95f4',
  invalidVolume: '\u97f3\u91cf\u53c2\u6570\u65e0\u6548',
  invalidSpeed: '\u53d8\u901f\u53c2\u6570\u65e0\u6548',
  exportTitle: '\u5bfc\u51fa\u97f3\u9891',
  exportDone: '\u5bfc\u51fa\u5b8c\u6210',
};

app.setPath('userData', path.join(app.getPath('appData'), USER_DATA_DIR_NAME));

const ffmpegPath =
  app.isPackaged && rawFfmpegPath ? rawFfmpegPath.replace('app.asar', 'app.asar.unpacked') : rawFfmpegPath;

ffmpeg.setFfmpegPath(ffmpegPath);

let mainWindow = null;
const sessionTempDirs = new Map();
const tempFileBaseDirMap = new Map();
const tempFileOriginMap = new Map();
const managedTempRoots = new Set();

function normalizeFsPath(filePath) {
  return path.resolve(filePath);
}

function getFallbackLargeTempBaseDir() {
  return path.join(app.getPath('userData'), 'large-temp');
}

function resolveOriginSourcePath(filePath) {
  if (!filePath) {
    return null;
  }

  const normalizedPath = normalizeFsPath(filePath);
  return tempFileOriginMap.get(normalizedPath) || normalizedPath;
}

function resolvePreferredStorageBaseDir(filePath) {
  if (!filePath) {
    return null;
  }

  const normalizedPath = normalizeFsPath(filePath);
  const mappedBaseDir = tempFileBaseDirMap.get(normalizedPath);

  return mappedBaseDir || path.dirname(resolveOriginSourcePath(normalizedPath));
}

async function ensureTempRoot(preferredBaseDir) {
  const candidateBaseDirs = [];

  if (preferredBaseDir) {
    candidateBaseDirs.push(preferredBaseDir);
  }

  candidateBaseDirs.push(getFallbackLargeTempBaseDir());

  let lastError = null;

  for (const baseDir of candidateBaseDirs) {
    const tempRoot = path.join(baseDir, TEMP_ROOT_NAME);

    try {
      await fsp.mkdir(tempRoot, { recursive: true });
      managedTempRoots.add(tempRoot);
      return tempRoot;
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError || new Error(TEXT.cannotCreateTempDir);
}

async function ensureSessionTempDir(sourcePath) {
  const preferredBaseDir = resolvePreferredStorageBaseDir(sourcePath);
  const cacheKey = preferredBaseDir || getFallbackLargeTempBaseDir();

  if (sessionTempDirs.has(cacheKey)) {
    return sessionTempDirs.get(cacheKey);
  }

  const tempRoot = await ensureTempRoot(preferredBaseDir);
  const sessionTempDirPath = await fsp.mkdtemp(path.join(tempRoot, 'session-'));

  sessionTempDirs.set(cacheKey, sessionTempDirPath);
  return sessionTempDirPath;
}

function sanitizeBaseName(filePath) {
  return path
    .basename(filePath, path.extname(filePath))
    .replace(/[<>:"/\\|?*]+/g, '_')
    .replace(/\s+/g, '_');
}

async function createSessionAudioPath(sourcePath, suffix = 'split', ext = '.wav') {
  const dir = await ensureSessionTempDir(sourcePath);
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const outputPath = path.join(dir, `${sanitizeBaseName(sourcePath)}-${suffix}-${stamp}${ext}`);
  const preferredBaseDir = resolvePreferredStorageBaseDir(sourcePath);
  const originSourcePath = resolveOriginSourcePath(sourcePath);
  const normalizedOutputPath = normalizeFsPath(outputPath);

  if (preferredBaseDir) {
    tempFileBaseDirMap.set(normalizedOutputPath, preferredBaseDir);
  }

  if (originSourcePath) {
    tempFileOriginMap.set(normalizedOutputPath, originSourcePath);
  }

  return outputPath;
}

async function createScopedTempDir(preferredBaseDir, prefix) {
  const tempRoot = await ensureTempRoot(preferredBaseDir);
  return fsp.mkdtemp(path.join(tempRoot, prefix));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1024,
    height: 768,
    minWidth: 960,
    minHeight: 700,
    backgroundColor: '#0f111a',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'index.html'));
}

function createAudioFilters({ volume, speed }) {
  const filters = [];

  if (Number.isFinite(volume) && volume > 0 && Math.abs(volume - 1) > 0.001) {
    filters.push(`volume=${volume}`);
  }

  if (Number.isFinite(speed) && speed > 0 && Math.abs(speed - 1) > 0.001) {
    let remaining = speed;

    while (remaining < 0.5) {
      filters.push('atempo=0.5');
      remaining /= 0.5;
    }

    while (remaining > 2.0) {
      filters.push('atempo=2.0');
      remaining /= 2.0;
    }

    filters.push(`atempo=${remaining.toFixed(3)}`);
  }

  return filters;
}

function applyOutputFormat(command, outputPath) {
  const ext = path.extname(outputPath).toLowerCase();

  if (ext === '.wav') {
    command.format('wav').audioCodec('pcm_s16le');
    return;
  }

  command.format('mp3').audioCodec('libmp3lame').audioBitrate('192k');
}

function runFfmpeg(command, event, stageRange, stageLabel) {
  return new Promise((resolve, reject) => {
    command
      .on('start', () => {
        event.sender.send('audio:export-progress', {
          percent: stageRange[0],
          message: `${stageLabel}${TEXT.stageStart}`,
        });
      })
      .on('progress', (progress) => {
        const rawPercent = Number(progress.percent);
        const percent = Number.isFinite(rawPercent)
          ? stageRange[0] + ((stageRange[1] - stageRange[0]) * rawPercent) / 100
          : stageRange[0];

        event.sender.send('audio:export-progress', {
          percent,
          message: `${stageLabel}${TEXT.stageProcessing}`,
        });
      })
      .on('end', () => {
        event.sender.send('audio:export-progress', {
          percent: stageRange[1],
          message: `${stageLabel}${TEXT.stageDone}`,
        });
        resolve();
      })
      .on('error', (error) => {
        reject(error);
      })
      .run();
  });
}

function runFfmpegSilently(command) {
  return new Promise((resolve, reject) => {
    command
      .on('end', resolve)
      .on('error', reject)
      .run();
  });
}

async function processPrimaryAudio({
  sourcePath,
  outputPath,
  trimStart,
  trimEnd,
  volume,
  speed,
  event,
}) {
  const duration = Math.max(0, trimEnd - trimStart);
  const filters = createAudioFilters({ volume, speed });

  const command = ffmpeg(sourcePath)
    .setStartTime(trimStart)
    .duration(duration)
    .output(outputPath)
    .outputOptions('-vn');

  if (filters.length > 0) {
    command.audioFilters(filters);
  }

  applyOutputFormat(command, outputPath);
  await runFfmpeg(command, event, [0, 70], TEXT.primaryAudioStage);
}

async function processSelectionOnly({
  sourcePath,
  outputPath,
  trimStart,
  trimEnd,
}) {
  const duration = Math.max(0, trimEnd - trimStart);

  const command = ffmpeg(sourcePath)
    .setStartTime(trimStart)
    .duration(duration)
    .output(outputPath)
    .outputOptions('-vn');

  applyOutputFormat(command, outputPath);
  await runFfmpegSilently(command);
}

async function mergeAudio({
  processedPrimaryPath,
  mergeFilePath,
  outputPath,
  event,
}) {
  const command = ffmpeg()
    .input(processedPrimaryPath)
    .input(mergeFilePath)
    .complexFilter(['[0:a][1:a]concat=n=2:v=0:a=1[outa]'])
    .outputOptions(['-map [outa]', '-vn'])
    .output(outputPath);

  applyOutputFormat(command, outputPath);
  await runFfmpeg(command, event, [70, 100], TEXT.mergeAudioStage);
}

function ensureValidExportPayload(payload) {
  if (!payload || !payload.filePath) {
    throw new Error(TEXT.missingSourcePath);
  }

  if (!fs.existsSync(payload.filePath)) {
    throw new Error(TEXT.sourceFileMissing);
  }

  if (payload.mergeFilePath && !fs.existsSync(payload.mergeFilePath)) {
    throw new Error(TEXT.mergeFileMissing);
  }

  if (!Number.isFinite(payload.trimStart) || !Number.isFinite(payload.trimEnd)) {
    throw new Error(TEXT.invalidTrimRange);
  }

  if (payload.trimEnd <= payload.trimStart) {
    throw new Error(TEXT.trimEndBeforeStart);
  }

  if (!Number.isFinite(payload.volume) || payload.volume <= 0) {
    throw new Error(TEXT.invalidVolume);
  }

  if (!Number.isFinite(payload.speed) || payload.speed <= 0) {
    throw new Error(TEXT.invalidSpeed);
  }
}

function ensureValidSelectionPayload(payload) {
  if (!payload || !payload.filePath) {
    throw new Error(TEXT.missingSourcePath);
  }

  if (!fs.existsSync(payload.filePath)) {
    throw new Error(TEXT.sourceFileMissing);
  }

  if (!Number.isFinite(payload.trimStart) || !Number.isFinite(payload.trimEnd)) {
    throw new Error(TEXT.invalidTrimRange);
  }

  if (payload.trimEnd <= payload.trimStart) {
    throw new Error(TEXT.trimEndBeforeStart);
  }
}

function buildDefaultOutputPath(filePath) {
  const originSourcePath = resolveOriginSourcePath(filePath) || normalizeFsPath(filePath);
  const dir = resolvePreferredStorageBaseDir(filePath) || path.dirname(originSourcePath);
  const ext = path.extname(originSourcePath).toLowerCase();
  const base = path.basename(originSourcePath, ext);
  return path.join(dir, `${base}-edited.mp3`);
}

function normalizeOutputPath(filePath) {
  return path.extname(filePath) ? filePath : `${filePath}.mp3`;
}

ipcMain.handle('dialog:open-audio-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [
      { name: 'Audio Files', extensions: ['mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg'] },
      { name: 'All Files', extensions: ['*'] },
    ],
  });

  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true };
  }

  const filePath = normalizeFsPath(result.filePaths[0]);
  tempFileBaseDirMap.set(filePath, path.dirname(filePath));
  tempFileOriginMap.set(filePath, filePath);

  return {
    canceled: false,
    filePath,
  };
});

ipcMain.handle('dialog:open-merge-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [
      { name: 'Audio Files', extensions: ['mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg'] },
      { name: 'All Files', extensions: ['*'] },
    ],
  });

  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true };
  }

  return {
    canceled: false,
    filePath: result.filePaths[0],
  };
});

ipcMain.handle('audio:split-selection', async (event, payload) => {
  try {
    ensureValidSelectionPayload(payload);

    const outputPath = await createSessionAudioPath(payload.filePath, 'split', '.wav');

    await processSelectionOnly({
      sourcePath: payload.filePath,
      outputPath,
      trimStart: payload.trimStart,
      trimEnd: payload.trimEnd,
    });

    return {
      success: true,
      filePath: outputPath,
    };
  } catch (error) {
    return {
      success: false,
      error: error.message,
    };
  }
});

ipcMain.handle('audio:export', async (event, payload) => {
  try {
    ensureValidExportPayload(payload);

    const saveResult = await dialog.showSaveDialog(mainWindow, {
      title: TEXT.exportTitle,
      defaultPath: buildDefaultOutputPath(payload.filePath),
      filters: [
        { name: 'MP3 Audio', extensions: ['mp3'] },
        { name: 'WAV Audio', extensions: ['wav'] },
      ],
    });

    if (saveResult.canceled || !saveResult.filePath) {
      return { canceled: true };
    }

    const finalOutputPath = normalizeOutputPath(saveResult.filePath);
    const tempDir = await createScopedTempDir(path.dirname(finalOutputPath), 'export-');
    const outputExt = path.extname(finalOutputPath).toLowerCase() || '.mp3';
    const processedPrimaryPath = path.join(tempDir, `processed-primary${outputExt}`);

    try {
      await processPrimaryAudio({
        sourcePath: payload.filePath,
        outputPath: processedPrimaryPath,
        trimStart: payload.trimStart,
        trimEnd: payload.trimEnd,
        volume: payload.volume,
        speed: payload.speed,
        event,
      });

      if (payload.mergeFilePath) {
        await mergeAudio({
          processedPrimaryPath,
          mergeFilePath: payload.mergeFilePath,
          outputPath: finalOutputPath,
          event,
        });
      } else {
        await fsp.copyFile(processedPrimaryPath, finalOutputPath);
        event.sender.send('audio:export-progress', {
          percent: 100,
          message: TEXT.exportDone,
        });
      }
    } finally {
      await fsp.rm(tempDir, { recursive: true, force: true });
    }

    return {
      success: true,
      outputPath: finalOutputPath,
    };
  } catch (error) {
    return {
      success: false,
      error: error.message,
    };
  }
});

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  for (const sessionTempDirPath of sessionTempDirs.values()) {
    try {
      fs.rmSync(sessionTempDirPath, { recursive: true, force: true });
    } catch (_) {}
  }

  for (const tempRoot of managedTempRoots) {
    try {
      if (fs.existsSync(tempRoot) && fs.readdirSync(tempRoot).length === 0) {
        fs.rmdirSync(tempRoot);
      }
    } catch (_) {}
  }
});