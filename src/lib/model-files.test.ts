import { afterEach, describe, expect, it, vi } from 'vitest'
import { importModelFiles } from './model-files'

function file(name: string, text: string) { return new File([text], name) }
afterEach(() => vi.unstubAllGlobals())
describe('local character package boundary', () => {
  it.each(['../escape.moc3', 'https://untrusted.test/actor.moc3', 'C:\\secret.moc3'])(
    'rejects an external reference: %s', async ref => {
      await expect(importModelFiles([file('test.model3.json', JSON.stringify({FileReferences:{Moc:ref, Textures:[]}}))]))
        .rejects.toThrow('文件夹以外')
    },
  )
  it('rewrites local dependencies, removes motion audio and releases every blob URL', async () => {
    vi.stubGlobal('location', {href:'http://localhost/'})
    const revoke = vi.spyOn(URL, 'revokeObjectURL')
    const result = await importModelFiles([
      file('test.model3.json', JSON.stringify({FileReferences:{Moc:'test.moc3',Textures:['test.png'],
        Motions:{Idle:[{File:'idle.motion3.json',Sound:'remote.mp3'}]}}})),
      file('test.moc3','model'),file('test.png','texture'),file('idle.motion3.json','{}'),
    ])
    expect(result.definition.FileReferences.Moc.startsWith('blob:')).toBe(true)
    expect(JSON.stringify(result.definition)).not.toContain('remote.mp3')
    result.dispose()
    expect(revoke).toHaveBeenCalledTimes(3)
    revoke.mockRestore()
  })
})
