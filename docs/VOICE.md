# 中英语音接入说明

> 0.2 起，聊天、火山引擎、兼容语音、识别和 LiveKit 的地址、模型及密钥均可在「设置」页填写。正常使用无需修改 `.env`。保存后下一次朗读和聊天立即生效；实时进程需重启，可使用 `scripts/start-voice.cmd`。下面的环境变量示例仅供旧版配置或开发调试，界面保存后的连接配置优先。


## 火山引擎指定音色（2026-09-11 接入）

项目已按用户给出的 V3 单向流式 HTTP 示例接入，默认选择：

```dotenv
TTS_PROVIDER=volcengine
VOLCENGINE_TTS_URL=https://openspeech.bytedance.com/api/v3/tts/unidirectional
VOLCENGINE_TTS_API_KEY=
VOLCENGINE_TTS_RESOURCE_ID=seed-tts-2.0
VOLCENGINE_TTS_SPEAKER=zh_female_sajiaoxuemei_uranus_bigtts
```

只需在项目 `.env` 填写 `VOLCENGINE_TTS_API_KEY` 后，完全退出并重启栖伴，开启「回复朗读」。这个字段对应 **X-Api-Key**，不是聊天网关的 `CHAT_API_KEY`，也不是旧兼容服务的 `TTS_API_KEY`。界面显示「火山引擎语音」表示本次朗读使用该提供方。

密钥留空时不会发起火山引擎请求：维持 Windows / 浏览器系统朗读，并在设置中显示「火山引擎音色待启用」。配置了密钥后，火山引擎错误会明确报错，不会悄悄用系统声音冒充指定音色。若要主动切回本地声音，清空该 key 并重启即可。

请求使用 `X-Api-Key`、`X-Api-Resource-Id`、每次独立的 UUID `X-Api-Request-Id`；JSON 为 `req_params.text`、`speaker` 和 `audio_params={format:mp3,sample_rate:24000}`。实际使用用户指定音色，不使用示例 payload 里的 `zh_female_vv_uranus_bigtts`。

后端按 UTF-8 增量解码，拼接任意网络边界上的 JSON 对象，再逐片校验并解码 base64。支持换行分隔与连续 JSON；状态码流接受 `0` 和最终 `20000000`，错误码、截断、空音频、无效 base64 或超限音频均报错。示例中只带 `data` 的格式也可处理，不会悄悄丢弃坏片段。

桌面回复沿用整条合成后播放，返回 `audio/mpeg`，前端解码 MP3 后以同一播放通道驱动口型与停止操作。LiveKit worker 同步增加了适配器，以 MP3 流送入 SDK 音频解码器；仍需 STT / LiveKit 配置才能实时通话。

本次没有实际 key，验证使用模拟服务与 SDK 适配器检查，尚未真实调用火山引擎或试听该音色。账号资源权限、音色可用性、中英发音质量需要填 key 后确认。中文与英文文本都会原样交给选定音色，不擅自切换其他音色。

## 当前可用：Windows 本地朗读

未填写远程 TTS 时，Windows 默认启用本地 SAPI。后端用独立隐藏进程合成 WAV，文本通过标准输入传递，不拼接到命令，也不发送外网；临时音频返回后删除。前端 AudioContext 播放并计算 RMS，映射到 `ParamMouthOpenY`，停止操作会取消待完成请求并停止播放。

本机已找到中文 Huihui 和英文 Zira，并分别成功合成约 3 秒的 22,050 Hz 音频。浏览器的声音列表只列出中文，因此增加此适配器，以支持现有英文系统声音。

这条链路按整条回复合成后播放，不是逐词语音生成；Windows 进程启动也有开销。它适合无语音账号的体验起步。远程自然语音应在角色、音色和延迟评估后替换。

设置 `WINDOWS_TTS_ENABLED=false` 可关闭该适配器。非 Windows 且无远程 TTS 时，前端使用 `speechSynthesis`；浏览器 API 不暴露 PCM，此时会明确显示「基础口型动画」，不声称声学同步。

## 兼容 HTTP STT / TTS

`.env`：

```dotenv
STT_BASE_URL=https://你的识别服务/v1
STT_MODEL=服务提供的模型名
STT_API_KEY=本地填写
TTS_PROVIDER=openai
TTS_BASE_URL=https://你的合成服务/v1
TTS_MODEL=服务提供的模型名
TTS_VOICE=服务提供的音色名
TTS_API_KEY=本地填写
```

地址只到 `/v1`，不要包含下面的完整资源路径。

| 接口 | 必需契约 |
|---|---|
| POST `/audio/transcriptions` | multipart，`file`、`model`，可选 `language=zh/en`；响应 `{"text":"识别结果"}` |
| POST `/audio/speech` | JSON `model`、`voice`、`input`、`response_format=wav`；响应可解码 WAV |

服务需要明确支持中文、英文；`auto` 会省略 STT 的 language，由服务检测。中英混说质量取决于识别模型；同一段朗读默认只选择一种声音，不做句内换声。文字通道有检测与显式语言切换。

录音由用户点击启动，最多 55 秒、服务侧限制 12 MB。识别结果进入输入框，用户确认后发送；晚到的识别结果不会覆盖新输入或另一段聊天。

可以选择提供上述协议的本地 Whisper / faster-whisper 服务和自然 TTS 网关。Qwen、CosyVoice 等原生服务通常协议不同，需增加适配器，不能仅替换 URL。这里没有默认下载语音大模型，也没有注册付费账号。

## 可选：LiveKit 实时通话

该路径已编写，但本次没有真实服务配置，尚未完成端到端验证。它使用 LiveKit Agents 1.8.0 统一管理麦克风、VAD、识别、生成、合成和打断。

1. 运行或准备可访问的 LiveKit 服务。远程地址应使用 `wss://`，同时保证 UDP/WebRTC 连通。
2. 填齐聊天、STT、TTS 配置；TTS 可选本页的火山引擎或兼容 HTTP 服务。**本地 Windows 朗读不能代替实时 worker 的 TTS**。
3. 在 `.env` 填写：

   ```dotenv
   LIVEKIT_URL=wss://你的房间服务
   LIVEKIT_API_KEY=本地填写
   LIVEKIT_API_SECRET=本地填写
   WORKER_SECRET=本地随机生成的长字符串
   ```

4. 初次为 Silero 准备模型文件，然后启动 worker：

   ```powershell
   .venv\Scripts\python.exe -m backend.voice_worker download-files
   .venv\Scripts\python.exe -m backend.voice_worker dev
   ```

5. 启动 / 重启主程序，点「实时通话」，允许麦克风权限。结束通话关闭麦克风并释放租约。

worker 与 API 必须在同机、同目录、同 `.env` 下运行，API 端口为 18765，数据库必须相同。API 为房间发放限定会话的短时 token；worker 使用 `WORKER_SECRET` 获取当前人设和记忆。不要把此内部接口或该密钥放进前端。

同一用户只允许一段实时通话。文本生成与该会话语音互斥。记忆或人设更新、新建会话、用户结束通话会使旧租约失效；worker 每 750ms 检查，及时停止旧语音上下文。API 重启也会丢弃租约。

VAD 当前使用固定端点参数，不包含语义停顿预测、唤醒词、后台监听或英文专用 turn detector。已说完的 SDK 会话条目写回数据库；被打断的助手条目保守地不放回后续上下文，避免把未播放尾部当成已听到。此选择可能丢失已听前缀；精确对齐留待联调时实现。

## 真实语音服务就绪后的验收

建议各做 10 轮中文、10 轮英文、10 轮混说，记录识别结束到第一声的延迟、误截断、漏识别、打断后停止时延。验证：

- 说话中打断角色，角色停止后不继续播放旧音频。
- 静默时不过早抢话，断网时不误报仍可交谈。
- 切换中文 / 英文后人设一致、名字发音可接受。
- 结束通话后麦克风指示熄灭，文字聊天可立即继续。
- 修改或删除记忆后，旧 worker 不再继续旧回复。
- 分别通过耳机和扬声器测试回声；不能把模型 SDK 的默认参数当作已验证的体验指标。
