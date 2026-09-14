# 角色、音色与首次配置预设

核对日期：2026-09-14。

## 火山引擎音色

全部使用同一条 V3 单向流接口及 `seed-tts-2.0`。音色名称和 ID 来自[官方音色列表](https://docs.volcengine.com/docs/6561/1257544?lang=zh)中“豆包语音合成模型 2.0”表，避免混用 1.0 或 S2S 专用音色。

| 声音 | 官方名称 | Speaker ID |
|---|---|---|
| 女声 | 撒娇学妹 2.0 | `zh_female_sajiaoxuemei_uranus_bigtts` |
| 女声 | 知性灿灿 2.0 | `zh_female_cancan_uranus_bigtts` |
| 女声 | Vivi 2.0 | `zh_female_vv_uranus_bigtts` |
| 男声 | 温柔小哥 2.0 | `zh_male_wenrouxiaoge_uranus_bigtts` |
| 男声 | 少年梓辛 2.0 | `zh_male_shaonianzixin_uranus_bigtts` |
| 男声 | 深夜播客 2.0 | `zh_male_shenyeboke_uranus_bigtts` |

界面中的简短风格词用于帮助挑选，不代表额外调用的情绪参数。官方说明中文音色亦具备英文能力；英文效果与可用性以账号权限和实际返回为准。保留自定义音色 ID，不覆盖已有自定义声音。默认继续使用撒娇学妹。

## 两个角色

栖栖：女性风格，温柔灵动、认真倾听，使用 Hiyori。

言川：男性风格，沉稳温和、细腻坦诚，使用 Natori。

两套形象均为本地 Live2D 动态模型，保留动作、物理、表情与口型能力；模型来自同一份已锁定哈希的官方 Cubism SDK。具体许可见 [ASSETS.md](ASSETS.md)。名字与人设为本产品配置，不是原模型官方角色设定。

选择预设会填入名字、性格和形象，点击保存后生效。保留对用户的称呼、语言偏好、聊天记录和记忆；切换角色不创建新账号。声音独立选择。`profiles.character_id` 通过仅新增列的迁移加入旧数据库，旧档案默认使用 Hiyori，不改写其原有人设。

## 密钥获取指引

新安装默认 DeepSeek OpenAI 兼容格式，地址 `https://api.deepseek.com`，模型 `deepseek-flash`。该模型名来自当日[官方首次调用文档](https://api-docs.deepseek.com/)，不会替换用户已配置的网关/模型。密钥入口为 <https://platform.deepseek.com/api_keys>。

语音默认豆包火山引擎。按[官方新版控制台指引](https://docs.volcengine.com/docs/6561/2485392?lang=zh)，先在目标项目下开通语音合成模型 2.0，再在同一项目的 API Key 管理页创建密钥。采用 `X-Api-Key` 鉴权，无需旧版 APP ID / Access Token，API Key 与火山方舟其他业务密钥不能随意混用。

点击指引会在系统浏览器打开固定官方链接；桌面进程只允许打开预先列出的完整 HTTPS URL，不接受任意路径、协议或带密钥的附加参数。不会代用户注册、开通付费服务或创建密钥。
