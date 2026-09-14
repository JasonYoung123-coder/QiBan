// Only fixed setup destinations can be opened by the renderer. Never allow arbitrary URL schemes.
const allowed = new Set([
  'https://platform.deepseek.com/api_keys',
  'https://api-docs.deepseek.com/',
  'https://console.volcengine.com/speech/new/setting/apikeys?ResourceID=volc.seedicl.default&projectName=default',
  'https://console.volcengine.com/speech/new/setting/activate?ResourceID=volc.seedicl.default&projectName=default',
  'https://docs.volcengine.com/docs/6561/2485392?lang=zh',
  'https://docs.volcengine.com/docs/6561/1257544?lang=zh',
  'https://platform.openai.com/api-keys',
  'https://console.anthropic.com/settings/keys',
])
exports.allowedGuide = url => typeof url === 'string' && allowed.has(url)
