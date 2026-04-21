import WaveSurfer from './node_modules/wavesurfer.js/dist/wavesurfer.esm.js';
import RegionsPlugin from './node_modules/wavesurfer.js/dist/plugins/regions.js';

(() => {
  const state = {
    activeTool: 'trim',
    filePath: '',
    displayName: '',
    mergeFilePath: '',
    volume: 1,
    speed: 1,
    duration: 0,
    isPlaying: false,
  };

  let wavesurfer = null;
  let regionsPlugin = null;
  let activeRegion = null;
  let pendingRestoreSnapshot = null;
  const undoStack = [];
  const HANDLE_SNAP_THRESHOLD_PX = 12;
  const MIN_REGION_LENGTH = 0.1;
  const REGION_EDGE_EPSILON = 0.001;
  const timelineDragState = {
    active: false,
    pointerId: null,
    cleanup: null,
  };

  const refs = {};

  function $(id) {
    return document.getElementById(id);
  }

  function initIcons() {
    if (window.lucide?.createIcons) {
      window.lucide.createIcons();
    }
  }

  function basename(filePath) {
    if (!filePath) return '';
    return filePath.split(/[\\/]/).pop();
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function formatTime(seconds) {
    const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
    const mins = Math.floor(safe / 60);
    const secs = safe % 60;
    return `${String(mins).padStart(2, '0')}:${secs.toFixed(2).padStart(5, '0')}`;
  }

  function parseTime(text) {
    const clean = String(text).trim();
    const parts = clean.split(':');

    if (parts.length === 2) {
      const mins = Number(parts[0]);
      const secs = Number(parts[1]);
      if (Number.isNaN(mins) || Number.isNaN(secs)) return NaN;
      return mins * 60 + secs;
    }

    if (parts.length === 3) {
      const hours = Number(parts[0]);
      const mins = Number(parts[1]);
      const secs = Number(parts[2]);
      if (Number.isNaN(hours) || Number.isNaN(mins) || Number.isNaN(secs)) return NaN;
      return hours * 3600 + mins * 60 + secs;
    }

    return NaN;
  }

  function setStatus(message, isError = false) {
    refs.statusText.textContent = message;
    refs.statusText.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
  }

  function setPlayButtonIcon(isPlaying) {
    refs.playButton.innerHTML = `<i data-lucide="${isPlaying ? 'pause' : 'play'}"></i>`;
    initIcons();
  }

  function setExportButtonBusy(isBusy, label = '导出') {
    refs.exportButton.disabled = isBusy;
    refs.exportButton.innerHTML = isBusy
      ? label
      : '导出 <i data-lucide="download" style="width: 16px; height: 16px;"></i>';

    if (!isBusy) {
      initIcons();
    }
  }

  function setSelectionActionButtonsBusy(activeButton = null, label = '处理中...') {
    const isBusy = Boolean(activeButton);

    if (refs.splitButton) {
      refs.splitButton.disabled = isBusy;
      refs.splitButton.innerHTML = activeButton === 'split'
        ? label
        : '<i data-lucide="split"></i> 分割 <kbd>S</kbd>';
    }

    if (refs.deleteButton) {
      refs.deleteButton.disabled = isBusy;
      refs.deleteButton.innerHTML = activeButton === 'delete'
        ? label
        : '<i data-lucide="trash-2"></i> 删除选区 <kbd>Del</kbd>';
    }

    initIcons();
  }

  function updateUndoButtonState() {
    if (!refs.undoButton) return;
    refs.undoButton.disabled = undoStack.length === 0;
  }

  function isEditingText() {
    const active = document.activeElement;
    if (!active) return false;
    return active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.getAttribute('contenteditable') === 'true';
  }

  function seekRelative(deltaSeconds) {
    if (!wavesurfer || !state.duration || typeof wavesurfer.setTime !== 'function') return;
    const current = Number(wavesurfer.getCurrentTime?.() ?? 0);
    const next = clamp(current + deltaSeconds, 0, state.duration);
    wavesurfer.setTime(next);
    updateTimeDisplay(next);
  }

  function getWaveformWidth() {
    return refs.waveform?.clientWidth || 0;
  }

  function timeToWaveformPx(time) {
    if (!state.duration) return 0;
    return (clamp(time, 0, state.duration) / state.duration) * getWaveformWidth();
  }

  function getCurrentCursorTime() {
    if (!wavesurfer || !state.duration) return null;
    const currentTime = Number(wavesurfer.getCurrentTime?.() ?? 0);
    return Number.isFinite(currentTime) ? clamp(currentTime, 0, state.duration) : null;
  }

  function getMinimumRegionLength() {
    return state.duration > 0 ? Math.min(MIN_REGION_LENGTH, state.duration) : MIN_REGION_LENGTH;
  }

  function eventHasPart(event, partName) {
    if (!event?.composedPath) return false;

    return event.composedPath().some((node) => {
      if (!node || typeof node.getAttribute !== 'function') return false;
      const part = node.getAttribute('part');
      return typeof part === 'string' && part.split(/\s+/).includes(partName);
    });
  }

  function getSnapTargetTime(handleTime) {
    const cursorTime = getCurrentCursorTime();
    if (cursorTime === null || !getWaveformWidth()) return null;

    const distancePx = Math.abs(timeToWaveformPx(handleTime) - timeToWaveformPx(cursorTime));
    return distancePx <= HANDLE_SNAP_THRESHOLD_PX ? cursorTime : null;
  }

  function snapRegionHandleToCursor(region, side) {
    if (!region || !side || typeof region.setOptions !== 'function' || !state.duration) return;

    const snapTarget = getSnapTargetTime(side === 'start' ? region.start : region.end);
    if (snapTarget === null) return;

    const minRegionLength = getMinimumRegionLength();

    if (side === 'start') {
      const maxStart = Math.max(0, region.end - minRegionLength);
      const nextStart = clamp(snapTarget, 0, maxStart);

      if (Math.abs(nextStart - region.start) > 0.0001) {
        region.setOptions({ start: nextStart });
      }
    } else if (side === 'end') {
      const minEnd = Math.min(state.duration, region.start + minRegionLength);
      const nextEnd = clamp(snapTarget, minEnd, state.duration);

      if (Math.abs(nextEnd - region.end) > 0.0001) {
        region.setOptions({ end: nextEnd });
      }
    }
  }

  function setCurrentTimeFromClientX(clientX) {
    if (!wavesurfer || !refs.waveform || !state.duration) return;

    const rect = refs.waveform.getBoundingClientRect();
    if (!rect.width) return;

    const ratio = clamp((clientX - rect.left) / rect.width, 0, 1);
    const nextTime = ratio * state.duration;

    if (typeof wavesurfer.setTime === 'function') {
      wavesurfer.setTime(nextTime);
    } else if (typeof wavesurfer.seekTo === 'function') {
      wavesurfer.seekTo(ratio);
    }

    updateTimeDisplay(nextTime);
  }

  function stopTimelineDrag() {
    if (typeof timelineDragState.cleanup === 'function') {
      timelineDragState.cleanup();
    }

    timelineDragState.active = false;
    timelineDragState.pointerId = null;
    timelineDragState.cleanup = null;
    refs.waveform?.classList.remove('dragging-timeline');
  }

  function startTimelineDrag(event) {
    if (!refs.waveform || !wavesurfer || !state.duration) return;

    stopTimelineDrag();

    timelineDragState.active = true;
    timelineDragState.pointerId = event.pointerId;
    refs.waveform.classList.add('dragging-timeline');
    setCurrentTimeFromClientX(event.clientX);

    const handlePointerMove = (moveEvent) => {
      if (!timelineDragState.active || moveEvent.pointerId !== timelineDragState.pointerId) return;
      moveEvent.preventDefault();
      setCurrentTimeFromClientX(moveEvent.clientX);
    };

    const handlePointerUp = (upEvent) => {
      if (upEvent.pointerId !== timelineDragState.pointerId) return;
      setCurrentTimeFromClientX(upEvent.clientX);
      stopTimelineDrag();
    };

    const handlePointerCancel = (cancelEvent) => {
      if (cancelEvent.pointerId !== timelineDragState.pointerId) return;
      stopTimelineDrag();
    };

    document.addEventListener('pointermove', handlePointerMove, true);
    document.addEventListener('pointerup', handlePointerUp, true);
    document.addEventListener('pointercancel', handlePointerCancel, true);

    timelineDragState.cleanup = () => {
      document.removeEventListener('pointermove', handlePointerMove, true);
      document.removeEventListener('pointerup', handlePointerUp, true);
      document.removeEventListener('pointercancel', handlePointerCancel, true);
    };
  }

  function handleWaveformPointerDown(event) {
    if (event.button !== 0 || !state.filePath || !state.duration) return;
    if (eventHasPart(event, 'region-handle') || eventHasPart(event, 'region-handle-left') || eventHasPart(event, 'region-handle-right')) {
      return;
    }

    event.preventDefault();
    startTimelineDrag(event);
  }

  function getCurrentRegionTimes() {
    if (activeRegion) {
      return { start: activeRegion.start, end: activeRegion.end };
    }

    return { start: 0, end: state.duration || 0 };
  }

  function captureSnapshot() {
    const { start, end } = getCurrentRegionTimes();
    return {
      filePath: state.filePath,
      displayName: state.displayName || basename(state.filePath),
      mergeFilePath: state.mergeFilePath,
      volume: state.volume,
      speed: state.speed,
      trimStart: start,
      trimEnd: end,
    };
  }

  function appendDisplaySuffix(displayName, suffix) {
    return displayName.endsWith(suffix) ? displayName : `${displayName}${suffix}`;
  }

  function updateTimeDisplay(current = 0) {
    refs.timeDisplay.innerHTML = `${formatTime(current)} <span>/ ${formatTime(state.duration)}</span>`;
  }

  function updateTrimFields() {
    const { start, end } = getCurrentRegionTimes();
    refs.selectionStart.textContent = formatTime(start);
    refs.selectionEnd.textContent = formatTime(end);
    refs.selectionDuration.textContent = formatTime(Math.max(0, end - start));
  }

  function updateVolumeFields() {
    refs.volumeSlider.value = String(Math.round(state.volume * 100));
    refs.volumeValue.textContent = `${Math.round(state.volume * 100)}%`;
  }

  function updateSpeedFields() {
    refs.speedSlider.value = String(Math.round(state.speed * 100));
    refs.speedValue.textContent = `${state.speed.toFixed(2)}x`;
  }

  function updateMergeFields() {
    refs.mergeFileName.textContent = state.mergeFilePath ? basename(state.mergeFilePath) : '未选择';
  }

  function setActiveTool(tool) {
    state.activeTool = tool;

    document.querySelectorAll('.tool-btn').forEach((button) => {
      button.classList.toggle('active', button.dataset.tool === tool);
    });

    document.querySelectorAll('.tool-panel').forEach((panel) => {
      panel.classList.toggle('active', panel.dataset.panel === tool);
    });
  }

  function clearAllRegions() {
    if (!regionsPlugin?.getRegions) return;
    regionsPlugin.getRegions().forEach((region) => region.remove());
    activeRegion = null;
  }

  function createRegion(start, end) {
    if (!regionsPlugin) return;

    clearAllRegions();
    activeRegion = regionsPlugin.addRegion({
      start,
      end,
      drag: false,
      resize: true,
      resizeStart: true,
      resizeEnd: true,
      color: 'rgba(0, 208, 191, 0.16)',
    });

    updateTrimFields();
  }

  function resetTrimToFull(showMessage = true) {
    if (!state.duration) return;
    createRegion(0, state.duration);
    if (showMessage) {
      setStatus('已恢复到最初的状态。');
    }
  }

  function syncRegionFromTextInputs() {
    if (!state.duration || !regionsPlugin) return;

    let start = parseTime(refs.selectionStart.textContent);
    let end = parseTime(refs.selectionEnd.textContent);

    if (Number.isNaN(start) || Number.isNaN(end)) {
      updateTrimFields();
      setStatus('时间格式无效，请使用 00:01.20 这样的格式。', true);
      return;
    }

    start = clamp(start, 0, state.duration);
    end = clamp(end, 0, state.duration);

    if (end <= start) {
      end = clamp(start + 0.1, 0, state.duration);
    }

    createRegion(start, end);
    setStatus('修剪区间已更新。');
  }

  function bindRegionEvents() {
    regionsPlugin.on('region-created', (region) => {
      if (activeRegion && activeRegion !== region) {
        const previous = activeRegion;
        activeRegion = region;
        previous.remove();
      } else {
        activeRegion = region;
      }

      if (typeof activeRegion.setOptions === 'function') {
        activeRegion.setOptions({
          drag: false,
          resize: true,
          resizeStart: true,
          resizeEnd: true,
          color: 'rgba(0, 208, 191, 0.16)',
        });
      }

      updateTrimFields();
    });

    regionsPlugin.on('region-update', (region, side) => {
      activeRegion = region;
      snapRegionHandleToCursor(region, side);
      updateTrimFields();
    });

    regionsPlugin.on('region-updated', (region, side) => {
      activeRegion = region;
      snapRegionHandleToCursor(region, side);
      updateTrimFields();
    });

    regionsPlugin.on('region-removed', (region) => {
      if (activeRegion === region) {
        activeRegion = null;
        updateTrimFields();
      }
    });
  }

  function initWaveSurfer() {
    wavesurfer = WaveSurfer.create({
      container: '#waveform',
      waveColor: '#335f5b',
      progressColor: '#00d0bf',
      cursorColor: '#ffca28',
      height: 260,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: true,
      autoScroll: false,
      autoCenter: false,
      minPxPerSec: 0,
      fillParent: true,
      hideScrollbar: true,
    });

    regionsPlugin = wavesurfer.registerPlugin(RegionsPlugin.create());
    bindRegionEvents();

    wavesurfer.on('loading', (percent) => {
      refs.waveEmpty.classList.remove('hidden');
      setStatus(`音频加载中 ${Math.round(percent)}%...`);
    });

    wavesurfer.on('ready', () => {
      state.duration = Number(wavesurfer.getDuration() || 0);
      refs.waveEmpty.classList.add('hidden');
      refs.audioMeta.textContent = `已加载 • 时长 ${formatTime(state.duration)}`;
      const isRestoring = Boolean(pendingRestoreSnapshot);

      if (pendingRestoreSnapshot) {
        const snapshot = pendingRestoreSnapshot;
        pendingRestoreSnapshot = null;

        state.displayName = snapshot.displayName || basename(snapshot.filePath);
        state.mergeFilePath = snapshot.mergeFilePath || '';
        state.volume = snapshot.volume;
        state.speed = snapshot.speed;

        wavesurfer.setVolume(state.volume);
        wavesurfer.setPlaybackRate(state.speed);

        updateVolumeFields();
        updateSpeedFields();
        updateMergeFields();

        const start = clamp(snapshot.trimStart, 0, state.duration);
        const end = clamp(snapshot.trimEnd, Math.min(state.duration, start + 0.1), state.duration);
        createRegion(start, end > start ? end : state.duration);
        updateTimeDisplay(start);
      } else {
        wavesurfer.setVolume(state.volume);
        wavesurfer.setPlaybackRate(state.speed);
        resetTrimToFull(false);
        updateTimeDisplay(0);
      }

      updateUndoButtonState();
      setStatus(isRestoring ? '已撤回到上一步。' : '音频已加载。请直接拖动左右手柄调整起点和终点，靠近时间轴时会自动吸附。');
    });

    wavesurfer.on('play', () => {
      state.isPlaying = true;
      setPlayButtonIcon(true);
    });

    wavesurfer.on('pause', () => {
      state.isPlaying = false;
      setPlayButtonIcon(false);
    });

    wavesurfer.on('finish', () => {
      state.isPlaying = false;
      setPlayButtonIcon(false);
    });

    wavesurfer.on('interaction', () => {
      updateTimeDisplay(wavesurfer.getCurrentTime());
    });

    wavesurfer.on('timeupdate', (currentTime) => {
      updateTimeDisplay(currentTime);

      if (activeRegion && state.isPlaying && currentTime >= activeRegion.end) {
        wavesurfer.pause();
        if (typeof wavesurfer.setTime === 'function') {
          wavesurfer.setTime(activeRegion.start);
          updateTimeDisplay(activeRegion.start);
        }
      }
    });

    wavesurfer.on('error', (error) => {
      setStatus(`音频加载失败：${String(error)}`, true);
    });
  }

  async function loadAudio(filePath, options = {}) {
    if (!filePath) return;

    const {
      displayName = basename(filePath),
      restoreSnapshot = null,
    } = options;

    if (!window.audioAPI?.toFileUrl) {
      setStatus('未检测到 Electron 预加载接口，请使用 npm start 启动。', true);
      return;
    }

    state.filePath = filePath;
    state.displayName = displayName;
    refs.currentFileName.textContent = displayName;
    refs.audioMeta.textContent = '正在读取音频信息...';
    refs.waveEmpty.classList.remove('hidden');
    pendingRestoreSnapshot = restoreSnapshot;

    const fileUrl = window.audioAPI.toFileUrl(filePath);
    wavesurfer.load(fileUrl);
  }

  async function handleImport() {
    if (!window.audioAPI?.openAudioFile) {
      setStatus('当前不是 Electron 环境，无法打开本地文件选择框。', true);
      return;
    }

    const result = await window.audioAPI.openAudioFile();
    if (!result || result.canceled || !result.filePath) {
      setStatus('已取消导入。');
      return;
    }

    undoStack.length = 0;
    updateUndoButtonState();
    state.mergeFilePath = '';
    updateMergeFields();

    await loadAudio(result.filePath);
  }

  async function handleSplitSelection() {
    if (!state.filePath) {
      setStatus('请先导入音频，再执行分割。', true);
      return;
    }

    if (!window.audioAPI?.splitSelection) {
      setStatus('未检测到 Electron 分割接口，请重启应用后再试。', true);
      return;
    }

    const { start, end } = getCurrentRegionTimes();
    if (end <= start) {
      setStatus('当前选区无效，无法分割。', true);
      return;
    }

    const snapshot = captureSnapshot();

    try {
      setSelectionActionButtonsBusy('split', '处理中...');
      setStatus('正在分割，只保留当前选区，请稍候...');

      const result = await window.audioAPI.splitSelection({
        filePath: state.filePath,
        trimStart: start,
        trimEnd: end,
      });

      if (!result || !result.success || !result.filePath) {
        setStatus(`分割失败：${result?.error || '未知错误'}`, true);
        return;
      }

      undoStack.push(snapshot);
      updateUndoButtonState();

      const nextDisplayName = appendDisplaySuffix(snapshot.displayName, '（已分割）');

      await loadAudio(result.filePath, { displayName: nextDisplayName });
      setStatus('分割完成，当前仅保留原选区内容。');
    } catch (error) {
      setStatus(`分割失败：${error.message}`, true);
    } finally {
      setSelectionActionButtonsBusy();
    }
  }

  async function handleDeleteSelection() {
    if (!state.filePath) {
      setStatus('请先导入音频，再执行删除选区。', true);
      return;
    }

    if (!window.audioAPI?.deleteSelection) {
      setStatus('未检测到 Electron 删除接口，请重启应用后再试。', true);
      return;
    }

    const { start, end } = getCurrentRegionTimes();
    if (end <= start) {
      setStatus('当前选区无效，无法删除。', true);
      return;
    }

    const selectionCoversWholeAudio =
      start <= REGION_EDGE_EPSILON && end >= state.duration - REGION_EDGE_EPSILON;

    if (selectionCoversWholeAudio) {
      setStatus('当前选区已覆盖整个音频，删除后将没有剩余内容。', true);
      return;
    }

    const snapshot = captureSnapshot();

    try {
      setSelectionActionButtonsBusy('delete', '处理中...');
      setStatus('正在删除当前选区，并把前后片段自动拼接，请稍候...');

      const result = await window.audioAPI.deleteSelection({
        filePath: state.filePath,
        trimStart: start,
        trimEnd: end,
        duration: state.duration,
      });

      if (!result || !result.success || !result.filePath) {
        setStatus(`删除失败：${result?.error || '未知错误'}`, true);
        return;
      }

      undoStack.push(snapshot);
      updateUndoButtonState();

      const nextDisplayName = appendDisplaySuffix(snapshot.displayName, '（已删除选区）');

      await loadAudio(result.filePath, { displayName: nextDisplayName });
      setStatus('删除完成，剩余音频已自动拼接。');
    } catch (error) {
      setStatus(`删除失败：${error.message}`, true);
    } finally {
      setSelectionActionButtonsBusy();
    }
  }

  async function handleUndo() {
    if (undoStack.length === 0) {
      setStatus('当前没有可撤回的编辑操作。');
      return;
    }

    const snapshot = undoStack.pop();
    updateUndoButtonState();

    try {
      await loadAudio(snapshot.filePath, {
        displayName: snapshot.displayName,
        restoreSnapshot: snapshot,
      });
      setStatus('已撤回到上一步。');
    } catch (error) {
      setStatus(`撤回失败：${error.message}`, true);
    }
  }

  async function handlePickMergeFile() {
    if (!window.audioAPI?.openMergeFile) {
      setStatus('当前不是 Electron 环境，无法选择合并文件。', true);
      return;
    }

    const result = await window.audioAPI.openMergeFile();
    if (!result || result.canceled || !result.filePath) {
      setStatus('已取消选择合并文件。');
      return;
    }

    state.mergeFilePath = result.filePath;
    updateMergeFields();
    setStatus(`已选择合并文件：${basename(result.filePath)}`);
  }

  function handleClearMergeFile() {
    state.mergeFilePath = '';
    updateMergeFields();
    setStatus('已清空合并文件。');
  }

  function handlePlayPause() {
    if (!wavesurfer || !state.filePath) {
      setStatus('请先导入音频。', true);
      return;
    }

    if (state.isPlaying) {
      wavesurfer.pause();
      return;
    }

    const { start, end } = getCurrentRegionTimes();
    const currentTime = Number(wavesurfer.getCurrentTime?.() ?? 0);
    const playFrom = currentTime >= start && currentTime < end ? currentTime : start;
    wavesurfer.play(playFrom, end);
  }

  function handleSkipStart() {
    if (!wavesurfer || typeof wavesurfer.setTime !== 'function') return;
    const { start } = getCurrentRegionTimes();
    wavesurfer.setTime(start);
    updateTimeDisplay(start);
  }

  function handleSkipEnd() {
    if (!wavesurfer || typeof wavesurfer.setTime !== 'function') return;
    const { end } = getCurrentRegionTimes();
    wavesurfer.setTime(end);
    updateTimeDisplay(end);
  }

  async function handleExport() {
    if (!state.filePath) {
      setStatus('请先导入音频，再执行导出。', true);
      return;
    }

    if (!window.audioAPI?.exportAudio) {
      setStatus('未检测到 Electron 导出接口，请使用 npm start 启动。', true);
      return;
    }

    const { start, end } = getCurrentRegionTimes();
    const payload = {
      filePath: state.filePath,
      trimStart: start,
      trimEnd: end,
      volume: state.volume,
      speed: state.speed,
      mergeFilePath: state.mergeFilePath || '',
    };

    try {
      setExportButtonBusy(true, '准备导出...');
      setStatus('正在导出，请稍候...');

      const result = await window.audioAPI.exportAudio(payload);

      if (!result || result.canceled) {
        setStatus('已取消导出。');
        return;
      }

      if (result.success) {
        setStatus(`导出完成：${result.outputPath}`);
      } else {
        setStatus(`导出失败：${result.error || '未知错误'}`, true);
      }
    } catch (error) {
      setStatus(`导出失败：${error.message}`, true);
    } finally {
      setExportButtonBusy(false);
    }
  }

  function bindEvents() {
    document.querySelectorAll('.tool-btn').forEach((button) => {
      button.addEventListener('click', () => {
        setActiveTool(button.dataset.tool);
      });
    });

    refs.importButton.addEventListener('click', handleImport);
    refs.splitButton.addEventListener('click', handleSplitSelection);
    refs.deleteButton.addEventListener('click', handleDeleteSelection);
    refs.undoButton.addEventListener('click', handleUndo);
    refs.pickMergeButton.addEventListener('click', handlePickMergeFile);
    refs.clearMergeButton.addEventListener('click', handleClearMergeFile);
    refs.playButton.addEventListener('click', handlePlayPause);
    refs.skipStartButton.addEventListener('click', handleSkipStart);
    refs.skipEndButton.addEventListener('click', handleSkipEnd);
    refs.exportButton.addEventListener('click', handleExport);
    refs.resetTrimButton.addEventListener('click', () => resetTrimToFull(true));
    refs.waveform.addEventListener('pointerdown', handleWaveformPointerDown);

    refs.volumeSlider.addEventListener('input', () => {
      state.volume = Number(refs.volumeSlider.value) / 100;
      updateVolumeFields();
      if (wavesurfer) {
        wavesurfer.setVolume(state.volume);
      }
    });

    refs.speedSlider.addEventListener('input', () => {
      state.speed = Number(refs.speedSlider.value) / 100;
      updateSpeedFields();
      if (wavesurfer) {
        wavesurfer.setPlaybackRate(state.speed);
      }
    });

    ['selectionStart', 'selectionEnd'].forEach((id) => {
      refs[id].addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          refs[id].blur();
        }
      });

      refs[id].addEventListener('blur', syncRegionFromTextInputs);
    });

    document.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        handleUndo();
        return;
      }

      if (!isEditingText()) {
        if (event.key === 'ArrowLeft') {
          event.preventDefault();
          seekRelative(event.shiftKey ? -1 : -0.1);
          return;
        }

        if (event.key === 'ArrowRight') {
          event.preventDefault();
          seekRelative(event.shiftKey ? 1 : 0.1);
          return;
        }
      }

      if (event.key.toLowerCase() === 's' && !event.ctrlKey && !event.metaKey && !event.altKey) {
        if (!isEditingText()) {
          event.preventDefault();
          handleSplitSelection();
          return;
        }
      }

      if ((event.key === 'Delete' || event.key === 'Del') && !isEditingText()) {
        event.preventDefault();
        handleDeleteSelection();
        return;
      }

      if (event.code === 'Space' && !isEditingText()) {
        event.preventDefault();
        handlePlayPause();
      }
    });

    if (window.audioAPI?.onExportProgress) {
      window.audioAPI.onExportProgress((progress) => {
        if (!progress) return;

        if (typeof progress.percent === 'number') {
          const percent = Math.max(0, Math.min(100, Math.round(progress.percent)));
          setExportButtonBusy(true, `导出中 ${percent}%`);
        }

        if (progress.message) {
          setStatus(progress.message);
        }
      });
    }
  }

  function initRefs() {
    refs.undoButton = $('undoButton');
    refs.importButton = $('importButton');
    refs.splitButton = $('splitButton');
    refs.deleteButton = $('deleteButton');
    refs.waveform = $('waveform');
    refs.currentFileName = $('currentFileName');
    refs.audioMeta = $('audioMeta');
    refs.statusText = $('statusText');
    refs.waveEmpty = $('waveEmpty');
    refs.playButton = $('playButton');
    refs.skipStartButton = $('skipStartButton');
    refs.skipEndButton = $('skipEndButton');
    refs.timeDisplay = $('timeDisplay');
    refs.selectionStart = $('selectionStart');
    refs.selectionEnd = $('selectionEnd');
    refs.selectionDuration = $('selectionDuration');
    refs.resetTrimButton = $('resetTrimButton');
    refs.volumeSlider = $('volumeSlider');
    refs.volumeValue = $('volumeValue');
    refs.speedSlider = $('speedSlider');
    refs.speedValue = $('speedValue');
    refs.mergeFileName = $('mergeFileName');
    refs.pickMergeButton = $('pickMergeButton');
    refs.clearMergeButton = $('clearMergeButton');
    refs.exportButton = $('exportButton');
  }

  function init() {
    initRefs();
    initIcons();
    initWaveSurfer();
    bindEvents();
    setActiveTool('trim');
    updateTimeDisplay(0);
    updateTrimFields();
    updateVolumeFields();
    updateSpeedFields();
    updateMergeFields();
    setPlayButtonIcon(false);
    updateUndoButtonState();
  }

  window.addEventListener('blur', stopTimelineDrag);
  document.addEventListener('DOMContentLoaded', init);
})();
