<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as PIXI from 'pixi.js'
import type { Cubism4InternalModel, Live2DModel as Model } from 'pixi-live2d-display/cubism4'
import type { AvatarState, Mood } from '../lib/contracts'
import type { ModelDefinition } from '../lib/model-files'
import { randomSaccadeInterval } from '../vendor/airi/eye-motions'

const props = defineProps<{ mouth: number; state: AvatarState; mood: Mood; lowMotion: boolean; petMode: boolean; customModel?: ModelDefinition }>()
const emit = defineEmits<{ ready: [name: string]; error: [message: string]; interact: [] }>()
const host = ref<HTMLDivElement>()
const loading = ref(true)
const error = ref('')
let app: PIXI.Application | undefined
let model: Model<Cubism4InternalModel> | undefined
let resize: ResizeObserver | undefined
let loadEpoch = 0
let disposed = false
let focusX = 0
let focusY = 0
let pointerUntil = 0
let nextSaccade = 0
let previousState: AvatarState = 'idle'
let lastGesture = 0
let moodWeight = 0

async function loadCore(): Promise<void> {
  if ('Live2DCubismCore' in window) return
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = '/vendor/live2dcubismcore.min.js'
    script.onload = () => resolve()
    script.onerror = () => { script.remove(); reject(new Error('尚未准备 Live2D 运行时，请先运行素材准备脚本。')) }
    document.head.append(script)
  })
}

function fit(): void {
  if (!app || !model || !host.value) return
  const { width, height } = host.value.getBoundingClientRect()
  app.renderer.resize(Math.max(width, 1), Math.max(height, 1))
  const original = model.internalModel
  // AIRI's stage frames the character rather than stretching it. Keep the aspect ratio and crop near the knees.
  const scale = Math.min(width * (props.petMode ? 1.3 : 0.92) / original.width,
    height * (props.petMode ? 1.03 : 1.42) / original.height)
  model.scale.set(scale)
  model.anchor.set(0.5, 0.5)
  model.position.set(width / 2, height * (props.petMode ? 0.53 : 0.71))
}

async function loadModel(): Promise<void> {
  if (!app) return
  const epoch = ++loadEpoch
  loading.value = true
  error.value = ''
  try {
    await loadCore()
    const { Live2DModel, config } = await import('pixi-live2d-display/cubism4')
    config.sound = false
    Live2DModel.registerTicker(PIXI.Ticker)
    const next = await Live2DModel.from(props.customModel || '/models/Hiyori/Hiyori.model3.json', {
      autoInteract: false, autoUpdate: false,
    }) as Model<Cubism4InternalModel>
    if (disposed || epoch !== loadEpoch) { next.destroy(); return }
    model?.destroy()
    model = next
    app.stage.addChild(next)
    const internal = next.internalModel
    const core = internal.coreModel
    const parameters = new Set(core.getModel().parameters.ids)
    const set = (name: string, value: number, weight = 1) => {
      if (parameters.has(name)) core.setParameterValueById(name, value, weight)
    }
    const normalMotionUpdate = internal.motionManager.update.bind(internal.motionManager)
    internal.motionManager.update = (current, now) => props.lowMotion ? false : normalMotionUpdate(current, now)
    // The SDK restores motion values after model.update. Apply mouth/expression overrides in its final hook,
    // as AIRI does, so ordinary motion curves cannot overwrite speech-driven mouth values.
    internal.on('beforeModelUpdate', () => {
      const now = performance.now()
      const targetMood = props.mood === 'neutral' ? 0 : 1
      moodWeight += (targetMood - moodWeight) * 0.08
      set('ParamMouthOpenY', props.state === 'speaking' ? props.mouth : 0)
      if (props.mood === 'happy' || props.mood === 'warm') {
        set('ParamMouthForm', props.mood === 'happy' ? 0.85 : 0.3, moodWeight)
        set('ParamCheek', props.mood === 'happy' ? 0.4 : 0.12, moodWeight)
      }
      if (props.mood === 'concerned') {
        set('ParamBrowLY', 0.2, moodWeight)
        set('ParamBrowRY', 0.2, moodWeight)
      }
      if (!props.lowMotion && pointerUntil < now && now > nextSaccade) {
        focusX = (Math.random() - 0.5) * 0.3
        focusY = (Math.random() - 0.5) * 0.18
        nextSaccade = now + randomSaccadeInterval()
      }
      internal.focusController.focus(props.lowMotion ? 0 : focusX, props.lowMotion ? 0 : focusY)
      if (previousState === 'speaking' && props.state !== 'speaking') internal.motionManager.stopAllMotions()
      previousState = props.state
    })
    fit()
    next.update(16.7)
    app.render()
    emit('ready', props.customModel ? '自定义 Live2D' : 'Hiyori · Live2D')
  } catch (cause) {
    if (epoch !== loadEpoch || disposed) return
    error.value = cause instanceof Error ? cause.message : 'Live2D 模型加载失败。'
    emit('error', error.value)
  } finally {
    if (epoch === loadEpoch && !disposed) loading.value = false
  }
}

function point(event: PointerEvent): void {
  if (!host.value) return
  const bounds = host.value.getBoundingClientRect()
  focusX = ((event.clientX - bounds.left) / bounds.width - 0.5) * 0.7
  focusY = -((event.clientY - bounds.top) / bounds.height - 0.4) * 0.55
  pointerUntil = performance.now() + 1600
}

function interact(): void {
  emit('interact')
  const now = performance.now()
  if (!model || props.lowMotion || now - lastGesture < 10000) return
  if (model.internalModel.motionManager.definitions.TapBody?.length) {
    lastGesture = now
    void model.motion('TapBody', 0)
  }
}

onMounted(async () => {
  app = new PIXI.Application({ backgroundAlpha: 0, antialias: true, resolution: Math.min(devicePixelRatio, 2), autoDensity: true })
  host.value?.appendChild(app.view as HTMLCanvasElement)
  app.ticker.maxFPS = 30
  app.ticker.add(() => {
    if (!document.hidden) model?.update(app!.ticker.deltaMS)
  })
  resize = new ResizeObserver(fit)
  if (host.value) resize.observe(host.value)
  await loadModel()
})
watch(() => props.customModel, () => void loadModel())
watch(() => props.petMode, fit)
onBeforeUnmount(() => {
  disposed = true
  loadEpoch += 1
  resize?.disconnect()
  model?.destroy()
  app?.destroy(true, { children: true, texture: true, baseTexture: true })
})
</script>

<template>
  <div ref="host" class="live2d-canvas" role="img" aria-label="Live2D 陪伴角色" @pointermove="point" @click="interact">
    <div v-if="loading" class="avatar-status"><span class="loading-orbit" />角色正在走近…</div>
    <div v-else-if="error" class="avatar-status avatar-error">
      <span>角色暂时未就绪</span><small>{{ error }}</small>
      <button @click.stop="loadModel">重新加载角色</button>
    </div>
  </div>
</template>
