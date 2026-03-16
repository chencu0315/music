# 音频剪辑工具项目规划

## 1. 项目目标

基于 `readme.md` 的要求，开发一个运行在 Windows 上的轻量级本地音频剪辑工具，核心能力包括：

- 本地音频文件导入
- 波形展示与区间修剪
- 音量调节
- 变速试听
- 双音频合并
- 导出为新的音频文件

技术方向：

- 桌面框架：Electron
- 前端：HTML + CSS + Vanilla JS
- 波形与预览：wavesurfer.js + Regions
- 音频处理：fluent-ffmpeg + ffmpeg-static

---

## 2. 当前建议的实施顺序

为了降低复杂度，建议按 5 个阶段完成，而不是一次性把所有功能写完。

### 阶段 A：前端原型确认

目标：先把界面结构、交互布局、参数面板切换做出来，不接真实音频处理。

本阶段输出：

- `index.html`
- `styles.css`
- `renderer.js`

验收标准：

- 深色风格符合预期
- 左侧工具栏可切换
- 底部参数区会联动切换
- 中央波形区域布局可用
- 播放/暂停、导出按钮位置合理

### 阶段 B：Electron 壳层接入

目标：让当前前端模板跑在 Electron 中。

本阶段输出：

- `package.json`
- `main.js`
- `preload.js`

验收标准：

- Electron 能正常启动
- 主进程与渲染进程分离
- 通过 preload 暴露安全 API
- 可从 Electron 中打开前端页面

### 阶段 C：文件导入与波形渲染

目标：接入 `dialog.showOpenDialog` 与 `wavesurfer.js`。

本阶段输出：

- 文件导入按钮接入 Electron API
- 波形渲染
- Regions 插件修剪区域
- 播放时限制在修剪区间内

验收标准：

- 可导入 `.mp3/.wav`
- 波形正常显示
- 可拖拽选区
- 变速、音量可实时试听

### 阶段 D：ffmpeg 导出能力

目标：把前端参数发送到主进程，用 ffmpeg 真正处理音频。

本阶段输出：

- 导出参数打包
- `ipcRenderer.invoke` -> `ipcMain.handle`
- trim / volume / atempo
- merge / concat
- 保存导出结果

验收标准：

- 能导出修剪后的文件
- 能应用音量变化
- 能应用变速
- 有合并文件时可拼接导出

### 阶段 E：稳定性与发布

目标：补充错误处理、边界情况和打包配置。

本阶段输出：

- 参数校验
- 异常提示
- 忙碌状态/导出进度提示
- Windows 打包配置

验收标准：

- 失败时有提示
- 参数异常不崩溃
- 可打包为可分发应用

---

## 3. 推荐目录结构

```text
music/
├─ readme.md
├─ project-plan.md
├─ package.json
├─ main.js
├─ preload.js
├─ index.html
├─ styles.css
├─ renderer.js
└─ assets/
```

后续如果功能继续增多，再拆成：

```text
src/
├─ main/
├─ renderer/
└─ shared/
```

但当前第一版不建议过早拆得太细。

---

## 4. 功能拆分建议

### 4.1 文件导入

- 主进程打开系统文件选择框
- preload 暴露 `selectAudioFile()`
- 渲染进程拿到路径后调用 `wavesurfer.load(filePath)`

### 4.2 修剪

- 使用 Regions 插件维护唯一选区
- 保存 `trimStart` / `trimEnd`
- 播放时监听时间，到达终点后暂停或回到起点

### 4.3 音量

- 前端试听：`wavesurfer.setVolume(value)`
- 导出处理：ffmpeg `volume=...`

### 4.4 变速

- 前端试听：`wavesurfer.setPlaybackRate(value)`
- 导出处理：ffmpeg `atempo=...`

### 4.5 合并

- 主文件 + 待合并文件
- 导出阶段生成 concat 文件列表
- ffmpeg 执行拼接

### 4.6 导出

- 导出前收集所有参数：
  - `filePath`
  - `trimStart`
  - `trimEnd`
  - `volume`
  - `speed`
  - `mergeFilePath`
  - `outputPath`

---

## 5. 技术风险与注意点

### 5.1 Electron 安装位置

你当前项目在 `D:\\Code\\github\\music`，只要在这个目录执行本地安装，`electron` 会安装到：

```text
D:\Code\github\music\node_modules
```

不会默认装到 C 盘。

### 5.2 你的环境现状

我已检查到：

- `node` 可用：`v24.14.0`
- `npm` 可用，但 PowerShell 里直接输入 `npm` 会被执行策略拦住

因此你在 PowerShell 下建议直接使用：

```powershell
npm.cmd
```

比如：

```powershell
npm.cmd install electron --save-dev
```

### 5.3 ffmpeg 变速限制

`atempo` 对单次倍率有范围限制，极端倍速时可能需要链式处理。

### 5.4 本地文件直载

Electron 中加载本地文件、预览音频时，要注意：

- preload 安全桥接
- 不要直接打开不可信的 Node 能力
- 尽量开启 `contextIsolation`

---

## 6. 接下来最合理的推进方式

建议按下面顺序继续：

1. 先确认前端模板样式是否满意
2. 再生成 `package.json`
3. 接着补 `main.js` / `preload.js`
4. 然后接入 `wavesurfer.js`
5. 最后接入 `ffmpeg` 导出

---

## 7. 本次已优先处理的内容

本次先完成：

- 项目规划文档
- 前端界面模板

下一步如果你确认这个 UI 方向没问题，我可以直接继续为你补全：

- `package.json`
- `main.js`
- `preload.js`
- 带真实 IPC 的 `renderer.js`
- 接入 wavesurfer 的版本
