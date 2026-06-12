<template>
  <div class="max-w-900px p-4 md:p-8">
    <div class="mb-6">
      <h2 class="text-lg font-semibold text-ink mb-1">系统设置</h2>
      <p class="text-muted text-sm">管理账户、AI 模型配置及系统偏好</p>
    </div>

    <div class="space-y-6">
      <!-- Profile -->
      <div class="bg-canvas border border-hairline rounded-xl p-6">
        <div class="text-sm font-semibold text-ink mb-4">个人信息</div>
        <div class="flex items-center gap-4 mb-6">
          <!-- Clickable avatar -->
          <div class="relative group cursor-pointer" @click="triggerAvatarUpload" title="点击更换头像">
            <div v-if="displayAvatar" class="w-16 h-16 rounded-full overflow-hidden border-2 border-hairline group-hover:border-primary transition-colors">
              <img :src="displayAvatar" class="w-full h-full object-cover" @error="onAvatarError" />
            </div>
            <div v-else class="w-16 h-16 rounded-full bg-ink flex items-center justify-center text-white text-xl font-bold group-hover:bg-primary transition-colors">
              {{ auth.user?.username?.[0]?.toUpperCase() || 'U' }}
            </div>
            <!-- Hover overlay -->
            <div class="absolute inset-0 rounded-full bg-black/30 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
              <span class="text-white text-xs font-medium">📷</span>
            </div>
            <input ref="avatarInput" type="file" accept="image/*" class="hidden" @change="onAvatarFileSelected" />
          </div>
          <div class="flex-1">
            <div class="flex items-center gap-2 mb-1">
              <input v-if="editingName" ref="nameInput" v-model="editName" @keydown.enter="saveName" @blur="saveName"
                class="bg-canvas border border-primary rounded-lg px-3 py-1 text-base font-medium text-ink outline-none" />
              <div v-else class="text-base font-medium text-ink">{{ auth.user?.username || '未登录' }}</div>
              <button @click="startEditName"
                class="text-xs text-muted-soft hover:text-primary transition-colors cursor-pointer">
                ✏️
              </button>
            </div>
            <div class="text-sm text-muted">{{ auth.user?.email || '' }}</div>
            <p v-if="avatarMsg" class="text-xs mt-2" :class="avatarMsgType === 'error' ? 'text-error-text' : 'text-primary'">{{ avatarMsg }}</p>
          </div>
        </div>
      </div>

      <!-- AI Model Config -->
      <div class="bg-canvas border border-hairline rounded-xl p-6">
        <div class="text-sm font-semibold text-ink mb-4">AI 模型配置</div>
        <div class="space-y-4">
          <div>
            <label class="text-sm text-muted block mb-1.5">DeepSeek API Key</label>
            <div class="flex gap-2">
              <input :type="showKey ? 'text' : 'password'" v-model="apiKey"
                class="flex-1 bg-surface-soft border border-hairline rounded-lg px-4 py-2.5 text-sm text-ink outline-none focus:border-ink transition-colors"
                placeholder="sk-..." />
              <button @click="showKey = !showKey"
                class="bg-surface-soft text-muted px-4 py-2.5 rounded-lg text-sm cursor-pointer hover:text-ink transition-colors">
                {{ showKey ? '隐藏' : '显示' }}
              </button>
            </div>
          </div>
          <div>
            <label class="text-sm text-muted block mb-1.5">API Base URL</label>
            <input v-model="baseUrl"
              class="w-full bg-surface-soft border border-hairline rounded-lg px-4 py-2.5 text-sm text-ink outline-none focus:border-ink transition-colors"
              placeholder="https://api.deepseek.com" />
          </div>
          <div>
            <label class="text-sm text-muted block mb-1.5">模型选择</label>
            <select v-model="model"
              class="w-full bg-surface-soft border border-hairline rounded-lg px-4 py-2.5 text-sm text-ink outline-none focus:border-ink transition-colors">
              <option value="deepseek-chat">DeepSeek-V3 — 性价比高，适合日常对话与数据分析</option>
              <option value="deepseek-reasoner">DeepSeek-R1 — 推理增强，适合复杂诊断与策略规划</option>
              <option value="deepseek-v4">DeepSeek-V4 — 最新旗舰，综合能力强</option>
              <option value="deepseek-v4-pro">DeepSeek-V4 Pro — 顶级性能，适合高精度任务</option>
            </select>
            <p class="text-xs text-muted-soft mt-2 leading-relaxed">
              💡 <span class="font-medium text-ink">指引：</span>
              <span v-if="model === 'deepseek-chat'">V3 响应快速、成本低，推荐用于常规分析和文案生成。</span>
              <span v-else-if="model === 'deepseek-reasoner'">R1 会展示详细推理过程（&lt;think&gt;），适合深度诊断和策略制定，但响应较慢。</span>
              <span v-else-if="model === 'deepseek-v4'">V4 综合性能更强，推理与生成兼顾。</span>
              <span v-else>V4 Pro 是当下最强模型，适合对精度要求极高的场景。</span>
            </p>
          </div>
          <button @click="saveConfig"
            class="bg-primary text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-primary-active transition-colors cursor-pointer">
            保存配置
          </button>
          <p v-if="configMsg" class="text-xs" :class="configMsgType === 'error' ? 'text-error-text' : 'text-primary'">{{ configMsg }}</p>
        </div>
      </div>

      <!-- Notification settings -->
      <div class="bg-canvas border border-hairline rounded-xl p-6">
        <div class="text-sm font-semibold text-ink mb-4">通知设置</div>
        <div class="space-y-4">
          <div v-for="setting in notifications" :key="setting.label"
            class="flex items-center justify-between py-2">
            <div>
              <div class="text-sm font-medium text-ink">{{ setting.label }}</div>
              <div class="text-xs text-muted-soft">{{ setting.desc }}</div>
            </div>
            <div class="w-10 h-6 rounded-full cursor-pointer transition-colors relative"
              :class="setting.enabled ? 'bg-primary' : 'bg-hairline'"
              @click="setting.enabled = !setting.enabled">
              <div class="absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform"
                :style="{ left: setting.enabled ? '18px' : '2px' }"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Data import -->
      <div class="bg-canvas border border-hairline rounded-xl p-6">
        <div class="text-sm font-semibold text-ink mb-4">数据导入</div>
        <p class="text-xs text-muted-soft mb-2">上传 CSV 文件导入数据，系统根据文件名自动识别类型：</p>
        <div class="text-xs text-muted-soft mb-4 space-y-1">
          <div>• 文件名含 <span class="font-medium text-ink">store</span> 或 <span class="font-medium text-ink">门店</span> → 导入门店</div>
          <div>• 文件名含 <span class="font-medium text-ink">sku</span> 或 <span class="font-medium text-ink">商品</span> → 导入商品</div>
          <div>• 文件名含 <span class="font-medium text-ink">revenue</span> 或 <span class="font-medium text-ink">营收</span> → 导入经营数据</div>
          <div>• 文件名含 <span class="font-medium text-ink">campaign</span> 或 <span class="font-medium text-ink">活动</span> → 导入营销活动</div>
        </div>
        <div class="flex flex-wrap gap-3 items-center">
          <label class="bg-primary text-white px-4 py-2.5 rounded-lg text-sm font-medium cursor-pointer hover:bg-primary-active transition-colors">
            选择文件上传
            <input type="file" accept=".csv" class="hidden" @change="onImportFile" />
          </label>
          <button @click="downloadTemplate"
            class="bg-surface-soft text-ink px-4 py-2.5 rounded-lg text-sm font-medium cursor-pointer hover:bg-hairline transition-colors">
            下载模板
          </button>
          <span v-if="importFileName" class="text-sm text-ink">{{ importFileName }}</span>
        </div>
        <p v-if="importMsg" class="text-sm mt-3" :class="importMsgType === 'error' ? 'text-error-text' : 'text-muted'">{{ importMsg }}</p>
      </div>

      <!-- Data management -->
      <div class="bg-canvas border border-hairline rounded-xl p-6">
        <div class="text-sm font-semibold text-ink mb-4">数据管理</div>
        <div class="flex flex-wrap gap-3">
          <button @click="exportAllData"
            class="bg-surface-soft text-ink px-4 py-2.5 rounded-lg text-sm font-medium cursor-pointer hover:bg-hairline transition-colors">
            导出全部数据
          </button>
          <button @click="showResetConfirm = true"
            class="bg-surface-soft text-ink px-4 py-2.5 rounded-lg text-sm font-medium cursor-pointer hover:bg-hairline transition-colors">
            重新生成 Demo 数据
          </button>
          <button @click="showClearConfirm = true"
            class="bg-error-text/8 text-error-text px-4 py-2.5 rounded-lg text-sm font-medium cursor-pointer hover:bg-error-text/15 transition-colors">
            清空数据库
          </button>
        </div>
        <p v-if="dataMsg" class="text-sm mt-3 text-muted">{{ dataMsg }}</p>
      </div>

      <!-- Account actions -->
      <div class="bg-canvas border border-hairline rounded-xl p-6">
        <div class="text-sm font-semibold text-ink mb-4">账号操作</div>
        <div class="flex flex-wrap gap-3">
          <button @click="handleLogout"
            class="bg-surface-soft text-ink px-4 py-2.5 rounded-lg text-sm font-medium cursor-pointer hover:bg-hairline transition-colors">
            退出登录
          </button>
          <button @click="handleDeleteAccount"
            class="bg-error-text/8 text-error-text px-4 py-2.5 rounded-lg text-sm font-medium cursor-pointer hover:bg-error-text/15 transition-colors">
            注销账号
          </button>
        </div>
        <p v-if="accountMsg" class="text-sm mt-3" :class="accountMsgType === 'error' ? 'text-error-text' : 'text-muted'">
          {{ accountMsg }}
        </p>
      </div>
    </div>
  </div>

  <!-- Delete confirmation modal -->
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="showDeleteConfirm" class="fixed inset-0 z-100 flex items-center justify-center bg-black/40">
        <div class="bg-white rounded-2xl p-6 w-90 shadow-xl">
          <h3 class="text-base font-semibold text-ink mb-2">确认注销账号？</h3>
          <p class="text-sm text-muted mb-6">此操作不可撤销，您的所有数据将被永久删除。</p>
          <div class="flex gap-3 justify-end">
            <button @click="showDeleteConfirm = false"
              class="px-4 py-2 rounded-lg text-sm font-medium bg-surface-soft text-ink hover:bg-hairline transition-colors cursor-pointer">
              取消
            </button>
            <button @click="confirmDelete" :disabled="deleting"
              class="px-4 py-2 rounded-lg text-sm font-medium bg-red-600 text-white hover:bg-red-700 transition-colors cursor-pointer disabled:opacity-50">
              {{ deleting ? '注销中...' : '确认注销' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- Reset/Clear confirmation modals -->
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="showResetConfirm" class="fixed inset-0 z-100 flex items-center justify-center bg-black/40">
        <div class="bg-white rounded-2xl p-6 w-90 shadow-xl">
          <h3 class="text-base font-semibold text-ink mb-2">重新生成 Demo 数据？</h3>
          <p class="text-sm text-muted mb-6">这将清除现有数据并重新生成模拟数据。</p>
          <div class="flex gap-3 justify-end">
            <button @click="showResetConfirm = false"
              class="px-4 py-2 rounded-lg text-sm font-medium bg-surface-soft text-ink hover:bg-hairline transition-colors cursor-pointer">
              取消
            </button>
            <button @click="regenerateMock"
              class="px-4 py-2 rounded-lg text-sm font-medium bg-primary text-white hover:bg-primary-active transition-colors cursor-pointer">
              确认重新生成
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <Teleport to="body">
    <Transition name="fade">
      <div v-if="showClearConfirm" class="fixed inset-0 z-100 flex items-center justify-center bg-black/40">
        <div class="bg-white rounded-2xl p-6 w-90 shadow-xl">
          <h3 class="text-base font-semibold text-ink mb-2">清空数据库？</h3>
          <p class="text-sm text-muted mb-6">此操作将删除所有数据并重新初始化，不可撤销。</p>
          <div class="flex gap-3 justify-end">
            <button @click="showClearConfirm = false"
              class="px-4 py-2 rounded-lg text-sm font-medium bg-surface-soft text-ink hover:bg-hairline transition-colors cursor-pointer">
              取消
            </button>
            <button @click="clearDatabase"
              class="px-4 py-2 rounded-lg text-sm font-medium bg-red-600 text-white hover:bg-red-700 transition-colors cursor-pointer">
              确认清空
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useUserProfileStore } from '../stores/userProfile'
import { request } from '../utils/request'

const router = useRouter()
const auth = useAuthStore()
const profile = useUserProfileStore()

const showKey = ref(false)
const apiKey = ref(localStorage.getItem('aura_apiKey') || '')
const baseUrl = ref(localStorage.getItem('aura_baseUrl') || 'https://api.deepseek.com')
const model = ref(profile.selectedModel || 'deepseek-chat')

const showDeleteConfirm = ref(false)
const showResetConfirm = ref(false)
const showClearConfirm = ref(false)
const deleting = ref(false)
const accountMsg = ref('')
const accountMsgType = ref('')
const dataMsg = ref('')
const importMsg = ref('')
const importMsgType = ref('')
const importFileName = ref('')
const configMsg = ref('')
const configMsgType = ref('')
const avatarMsg = ref('')
const avatarMsgType = ref('')

// Avatar upload
const avatarInput = ref(null)
const editingName = ref(false)
const editName = ref('')
const nameInput = ref(null)

const displayAvatar = computed(() => {
  return profile.avatarUrl || auth.user?.avatar_url || ''
})

function onAvatarError() {
  profile.setAvatar('')
}

function triggerAvatarUpload() {
  avatarInput.value?.click()
}

async function onAvatarFileSelected(e) {
  const file = e.target.files[0]
  if (!file) return
  avatarMsg.value = '上传中...'
  avatarMsgType.value = ''
  try {
    await profile.uploadAvatar(file)
    avatarMsg.value = '头像已更新'
    avatarMsgType.value = 'success'
    setTimeout(() => { avatarMsg.value = '' }, 2000)
  } catch (err) {
    avatarMsg.value = '上传失败: ' + err.message
    avatarMsgType.value = 'error'
  }
  e.target.value = ''
}

function startEditName() {
  editName.value = auth.user?.username || ''
  editingName.value = true
  nextTick(() => nameInput.value?.focus())
}

async function saveName() {
  editingName.value = false
  if (!editName.value.trim() || editName.value.trim() === auth.user?.username) return
  try {
    await profile.updateProfile({ username: editName.value.trim() })
    auth.user.username = editName.value.trim()
    localStorage.setItem('user', JSON.stringify(auth.user))
    avatarMsg.value = '用户名已更新'
    avatarMsgType.value = 'success'
    setTimeout(() => { avatarMsg.value = '' }, 2000)
  } catch (err) {
    avatarMsg.value = '更新失败: ' + err.message
    avatarMsgType.value = 'error'
  }
}

// Model config
function saveConfig() {
  localStorage.setItem('aura_apiKey', apiKey.value)
  localStorage.setItem('aura_baseUrl', baseUrl.value)
  localStorage.setItem('aura_model', model.value)
  profile.setModel(model.value)
  configMsg.value = '配置已保存'
  configMsgType.value = 'success'
  setTimeout(() => { configMsg.value = '' }, 2000)
}

// File import
async function onImportFile(e) {
  const file = e.target.files[0]
  if (!file) return
  importFileName.value = file.name
  importMsg.value = '上传中...'
  importMsgType.value = ''
  const fd = new FormData()
  fd.append('file', file)
  try {
    const res = await request('/api/import/upload', { method: 'POST', body: fd })
    importMsg.value = res.message || '导入成功'
    importMsgType.value = 'success'
  } catch (err) {
    importMsg.value = '导入失败: ' + err.message
    importMsgType.value = 'error'
  }
  e.target.value = ''
}

function downloadTemplate() {
  const csv = `日期,门店ID,营收,订单数,客单价,毛利率,退单率,净利润
2026-06-01,1,18500,234,79,65,1.2,5200
2026-06-01,2,16800,198,85,62,0.8,4800`
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'revenue_template.csv'
  a.click()
  URL.revokeObjectURL(url)
}

// Notifications
const savedNotifications = (() => {
  try { return JSON.parse(localStorage.getItem('aura_notifications')) } catch { return null }
})()

const notifications = reactive(savedNotifications || [
  { label: '库存预警通知', desc: '当商品库存低于阈值时发送通知', enabled: true },
  { label: '异常数据预警', desc: '当检测到成本或销量异常时通知', enabled: true },
  { label: '营销活动提醒', desc: '活动开始/结束时发送提醒', enabled: false },
  { label: '日报推送', desc: '每日经营数据摘要推送', enabled: true },
  { label: '系统更新通知', desc: '系统版本更新及新功能通知', enabled: false },
])

watch(notifications, (val) => {
  localStorage.setItem('aura_notifications', JSON.stringify(val))
}, { deep: true })

// Data management
async function exportAllData() {
  try {
    const res = await fetch('/api/dashboard/export?format=csv&days=90')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `aura_export_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
    dataMsg.value = '导出成功'
  } catch (err) {
    dataMsg.value = '导出失败: ' + err.message
  }
  setTimeout(() => { dataMsg.value = '' }, 3000)
}

async function regenerateMock() {
  showResetConfirm.value = false
  try {
    await request('/api/admin/regenerate-mock', { method: 'POST' })
    dataMsg.value = 'Demo 数据已重新生成'
  } catch (err) {
    dataMsg.value = '操作失败: ' + err.message
  }
  setTimeout(() => { dataMsg.value = '' }, 3000)
}

async function clearDatabase() {
  showClearConfirm.value = false
  try {
    await request('/api/admin/reset-db', { method: 'POST' })
    dataMsg.value = '数据库已清空并重新初始化'
  } catch (err) {
    dataMsg.value = '操作失败: ' + err.message
  }
  setTimeout(() => { dataMsg.value = '' }, 3000)
}

// Account actions
function handleLogout() {
  auth.logout()
  router.push('/login')
}

function handleDeleteAccount() {
  showDeleteConfirm.value = true
  accountMsg.value = ''
}

async function confirmDelete() {
  deleting.value = true
  try {
    await auth.deleteAccount()
    showDeleteConfirm.value = false
    router.push('/')
  } catch (err) {
    accountMsg.value = err.message
    accountMsgType.value = 'error'
    showDeleteConfirm.value = false
  } finally {
    deleting.value = false
  }
}

onMounted(async () => {
  // Sync with backend profile
  try {
    await profile.fetchProfile()
  } catch { /* ignore */ }
})
</script>

<style scoped>
.fade-enter-active { animation: fadeIn 0.2s ease; }
.fade-leave-active { animation: fadeIn 0.15s ease reverse; }
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
