# 来源、复用边界与素材许可

项目自有代码采用仓库根目录的 Apache-2.0 许可。第三方代码、依赖与素材各自保留其许可；默认角色和 Cubism Core 不随源代码仓库分发。

## AIRI

- 仓库：[moeru-ai/airi](https://github.com/moeru-ai/airi)
- 本次参考提交：`21d0e9d3a7e3623d71e6e1965087cd47a82e5c49`
- 实际保留的源文件：`src/vendor/airi/eye-motions.ts`。
- 该模块原始 MIT 许可完整保存在 `src/vendor/airi/LICENSE`。
- 参考机制：视线微动时间分布、在模型更新末尾应用口型 / 参数、保持模型比例的取景。
- Electron 桌面壳、FastAPI 服务、记忆数据层和语音适配器为本原型独立实现；没有宣称直接使用 AIRI 的完整桌面 App 或私有 workspace 包。

## Live2D Cubism 与 Hiyori

官方 SDK 归档：

- 版本：`CubismSdkForWeb-5-r.3`
- [官方下载地址](https://cubism.live2d.com/sdk-web/bin/CubismSdkForWeb-5-r.3.zip)
- SHA-256：`c70cc086950c7a318515e8ee606d8458a6dd2b96773fc2514ff67bf8a2d9ead7`
- 提取内容：`Core/live2dcubismcore.min.js`、`Samples/Resources/Hiyori` 与官方 LICENSE / NOTICE。
- 本地位置：`public/vendor`、`public/models/Hiyori`。
- 额外核对的官方源码仓库：[Live2D/CubismWebSamples](https://github.com/Live2D/CubismWebSamples)，提交 `b1de66b0b1f1cb881d95fb6158622aeb6a2827bd`。

准备脚本校验归档哈希，并限定提取路径。未把 runtime 或示例素材纳入默认 Git 跟踪；交付本机目录含素材以便直接体验。

Cubism Core 适用 **Live2D Proprietary Software License**；示例模型适用 **Free Material License** 以及各模型页面条件。SDK 发行还涉及独立 Release License。请以随附的 `public/vendor/LICENSE.md` 与官方条款为准：

- [Core 使用许可](https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html)
- [素材使用许可](https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html)
- [各示例模型条件](https://docs.live2d.com/cubism-editor-manual/sample-model/)
- [SDK 发行许可](https://www.live2d.com/en/download/cubism-sdk/release-license/)

Hiyori 用于技术体验；正式产品应选用你有权使用、修改、商业发行的模型及音色。界面保留示例形象署名。

## 主要组件

| 组件 | 官方仓库 / 文档 | 用途 |
|---|---|---|
| Vue | [vuejs/core](https://github.com/vuejs/core) | 前端交互 |
| Electron | [electron/electron](https://github.com/electron/electron) | Windows 桌面窗口 |
| PixiJS | [pixijs/pixijs](https://github.com/pixijs/pixijs) | GPU 图像渲染 |
| pixi-live2d-display | [guansss/pixi-live2d-display](https://github.com/guansss/pixi-live2d-display) | Cubism / Pixi 适配 |
| LiveKit Agents | [livekit/agents](https://github.com/livekit/agents) | 可选实时语音会话 |
| FastAPI | [fastapi/fastapi](https://github.com/fastapi/fastapi) | 本地 API |
| SQLAlchemy | [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) | 数据层 |

精确 Node 依赖由 `package-lock.json` 固定，Python 依赖由 `uv.lock` 固定。依赖包内 LICENSE 均保留；第三方许可不受根目录 Apache-2.0 许可替代。
