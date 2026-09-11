type References = { Moc: string; Textures: string[]; [key: string]: unknown }
export type ModelDefinition = { FileReferences: References; [key: string]: unknown }

/** Resolves only files inside the selected folder. Imported character files never execute scripts or fetch remote URLs. */
export async function importModelFiles(files: File[]): Promise<{ definition: ModelDefinition; dispose: () => void }> {
  if (files.length > 160 || files.reduce((sum, file) => sum + file.size, 0) > 60_000_000) {
    throw new Error('角色包过大：最多 160 个文件、60 MB。')
  }
  const pathFor = (file: File) => file.webkitRelativePath || file.name
  const entries = files.filter(file => file.name.endsWith('.model3.json'))
  if (entries.length !== 1) throw new Error('请选择只包含一个 .model3.json 的角色文件夹。')
  const entry = entries[0]
  const base = pathFor(entry).slice(0, pathFor(entry).lastIndexOf('/') + 1)
  const byPath = new Map(files.map(file => [pathFor(file), file]))
  const urls: string[] = []
  const mapFile = (value: unknown): string => {
    if (typeof value !== 'string' || /(^\/|\\|:|\?|#)/.test(value) || value.split('/').includes('..')) {
      throw new Error('角色包引用了文件夹以外的资源。')
    }
    const file = byPath.get(base + value.replace(/^\.\//, ''))
    if (!file || !/\.(json|moc3|png|jpe?g|webp)$/i.test(file.name)) throw new Error(`缺少或不支持的模型资源：${value}`)
    const url = URL.createObjectURL(file)
    urls.push(url)
    return url
  }
  try {
    const definition = JSON.parse(await entry.text()) as ModelDefinition
    const refs = definition.FileReferences
    if (!refs || !Array.isArray(refs.Textures)) throw new Error('这不是有效的 Cubism 模型文件。')
    refs.Moc = mapFile(refs.Moc)
    refs.Textures = refs.Textures.map(mapFile)
    for (const key of ['Physics', 'Pose', 'UserData', 'DisplayInfo']) {
      if (refs[key]) refs[key] = mapFile(refs[key])
    }
    if (Array.isArray(refs.Expressions)) {
      for (const expression of refs.Expressions as { File: string }[]) expression.File = mapFile(expression.File)
    }
    if (refs.Motions && typeof refs.Motions === 'object') {
      for (const group of Object.values(refs.Motions as Record<string, { File: string; Sound?: string }[]>)) {
        for (const motion of group) { motion.File = mapFile(motion.File); delete motion.Sound }
      }
    }
    definition.url = location.href
    return { definition, dispose: () => urls.forEach(url => URL.revokeObjectURL(url)) }
  } catch (error) {
    urls.forEach(url => URL.revokeObjectURL(url))
    throw error
  }
}
