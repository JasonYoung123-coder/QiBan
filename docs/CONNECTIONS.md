# 模型与语音连接设置

## 支持的接口

| 选择 | 请求 | 人设 / 系统指令 | 流式文字 |
|---|---|---|---|
| OpenAI / 兼容接口 | `POST {base}/chat/completions` | `messages` 的 system 消息 | `choices[0].delta.content` |
| OpenAI Responses | `POST {base}/responses` | `instructions` | `response.output_text.delta` |
| Anthropic Messages | `POST {base}/messages` | 顶层 `system` | `content_block_delta` 的 `text_delta` |

OpenAI 两种接口使用 Bearer 认证；Anthropic 使用 `x-api-key` 与 `anthropic-version: 2023-06-01`。服务地址通常以 `/v1` 结束，也可粘贴完整请求地址，保存时会规范化。模型名称由用户填写，不固定替换为某个模型。OpenAI Responses 请求默认 `store: false`。

流解析按 SSE 事件边界处理，支持网络字节分片和中英文 UTF-8；忽略心跳、思考和非文字事件。OpenAI Chat 以结束标记/finish_reason，Responses 以 `response.completed`，Anthropic 以 `message_stop` 判断完成。断流或错误事件显示失败，不伪装成正常完成。该适配器面向文字陪伴，不实现工具调用、视觉输入或供应商特定的复杂推理选项。

官方协议文档：

- https://developers.openai.com/api/docs/guides/streaming-responses
- https://platform.claude.com/docs/en/build-with-claude/streaming

## 本地设置接口

- `GET /api/settings`：返回三个独立聊天配置、语音配置和能力状态；密钥仅返回是否已设置。
- `PUT /api/settings`：带当前 revision 保存，成功后递增版本。并发旧版本返回 409。
- `POST /api/settings/test`：使用未保存表单发送一条 `Reply with OK.`，不发送个人聊天历史，也不写入配置文件。

均要求本地会话，执行 Host / Origin 检查且返回 `Cache-Control: no-store`。配置属于当前应用安装目录，与聊天档案不同，不是公网多用户管理接口。

密钥字段：`null` 保留旧值，空字符串清除，非空字符串替换。三种聊天接口的密钥不自动共享。更换服务地址时必须明确重新填写或清除对应旧密钥，防止保留的凭据被发送到新地址。校验失败的响应不回显字段值，连接测试不向界面返回供应商原始错误正文。

设置保存在 `.data/connections.json`，采用同目录临时文件写入后原子替换；这是为单机跨设备迁移使用的明文本地文件，没有声称使用加密保险库。旧 `.env` 首次加载时作为默认值，之后以该文件为准，包括明确清空的密钥。

保存设置会停止活动回复和实时通话租约，下一次聊天/合成使用新配置。实时语音与文字聊天共用同一模型适配器；语音进程每次新会话重新加载设置，但 LiveKit 连接参数修改后仍需重启进程。

## 验证

`tests/test_connections.py` 覆盖三种协议的请求地址、认证和人设映射、中英流分片、断流/错误、语音共用适配器、设置持久化、保留/清除密钥、接口隔离、并发冲突、权限检查与保存时取消生成。

`scripts/smoke-desktop.cjs` 可在隔离测试目录设置 `QIBAN_SMOKE_SETTINGS=1`，通过本机模拟服务操作真实设置页，依次测试和保存三种接口，再验证密钥不回显。该模式会写入虚拟测试配置，只用于测试副本，不用于个人数据目录。
