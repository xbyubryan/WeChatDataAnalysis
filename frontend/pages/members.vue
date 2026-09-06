<template>
  <div class="members-page theme-scope flex h-screen overflow-hidden" style="background-color: var(--app-shell-bg)">
    <!-- 左侧：会话导航 -->
    <aside class="flex w-[300px] shrink-0 flex-col border-r border-[#e5e7eb] bg-white">
      <div class="border-b border-[#e5e7eb] px-4 py-3">
        <div class="text-[15px] font-semibold text-[#111827]">成员发言统计</div>
        <div class="relative mt-3">
          <svg class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9ca3af]" fill="none" stroke="currentColor" viewBox="0 0 16 16" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7.333 12.667A5.333 5.333 0 1 0 7.333 2a5.333 5.333 0 0 0 0 10.667ZM14 14l-2.9-2.9" />
          </svg>
          <input
            v-model="sessionKeyword"
            type="text"
            class="w-full rounded-md border border-[#e5e7eb] bg-white py-2 pl-9 pr-3 text-[13px] text-[#111827] outline-none transition placeholder:text-[#9ca3af] focus:border-[#07C160] focus:ring-2 focus:ring-[#07C160]/15"
            placeholder="搜索群聊 / 联系人"
          />
        </div>
      </div>

      <div class="min-h-0 flex-1 overflow-auto">
        <div v-if="sessionsLoading" class="px-4 py-6 text-[13px] text-[#6b7280]">正在加载会话…</div>

        <template v-else>
          <section v-for="group in sessionGroups" :key="group.key" class="py-1">
            <button
              type="button"
              class="flex w-full items-center gap-1.5 px-4 py-1.5 text-left text-[12px] font-medium text-[#6b7280] hover:text-[#111827]"
              @click="toggleGroup(group.key)"
            >
              <svg class="h-3 w-3 transition-transform" :class="{ 'rotate-90': !collapsed[group.key] }" fill="none" stroke="currentColor" viewBox="0 0 12 12" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4.5 2.5 8 6l-3.5 3.5" />
              </svg>
              <span>{{ group.label }}</span>
              <span class="text-[#9ca3af]">{{ group.items.length }}</span>
            </button>

            <button
              v-for="item in collapsed[group.key] ? [] : group.items"
              :key="item.username"
              type="button"
              class="flex w-full items-center gap-2.5 px-4 py-2 text-left transition"
              :class="item.username === selectedUsername ? 'bg-[#f0fdf4]' : 'hover:bg-[#f9fafb]'"
              @click="selectSession(item.username)"
            >
              <div class="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-[#07C160] text-[11px] font-bold text-white">
                {{ group.key === 'groups' ? '群' : sessionInitial(item) }}
              </div>
              <div class="min-w-0 flex-1">
                <div
                  class="truncate text-[13px]"
                  :class="item.username === selectedUsername ? 'font-medium text-[#047857]' : 'text-[#111827]'"
                >
                  {{ sessionName(item) }}
                </div>
              </div>
            </button>

            <div v-if="!collapsed[group.key] && !group.items.length" class="px-4 py-2 text-[12px] text-[#9ca3af]">无匹配项</div>
          </section>
        </template>
      </div>
    </aside>

    <!-- 右侧：成员总览 -->
    <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <header class="border-b border-[#e5e7eb] bg-white px-5 py-4">
        <nav class="flex items-center gap-1.5 text-[12px] text-[#9ca3af]">
          <span>微信</span>
          <span>/</span>
          <span>{{ overview?.isGroup === false ? '联系人' : '群聊' }}</span>
          <span>/</span>
          <span class="text-[#6b7280]">{{ currentSessionName }}</span>
          <span>/</span>
          <span class="font-medium text-[#07C160]">成员发言统计</span>
        </nav>

        <div class="mt-2 flex items-center justify-between gap-4">
          <h1 class="truncate text-[22px] font-semibold tracking-[-0.03em] text-[#111827]">{{ currentSessionName }}</h1>
          <div class="flex shrink-0 items-center gap-2">
            <label class="flex items-center gap-1.5 text-[12px] text-[#6b7280]">
              <span>主题词</span>
              <select v-model.number="topicCount" class="rounded-md border border-[#e5e7eb] bg-white px-2 py-1.5 text-[12px] text-[#111827] outline-none focus:border-[#07C160]">
                <option :value="5">5</option>
                <option :value="8">8</option>
                <option :value="12">12</option>
              </select>
            </label>
            <button
              type="button"
              class="rounded-md border border-[#e5e7eb] px-3 py-1.5 text-[12px] text-[#374151] transition hover:border-[#07C160] hover:text-[#07C160] disabled:opacity-60"
              :disabled="loading"
              @click="loadOverview({ force: true })"
            >
              {{ loading ? '统计中…' : '重新统计' }}
            </button>
          </div>
        </div>

        <div v-if="currentSessionName !== '未选择会话'" class="mt-3 grid gap-3 md:grid-cols-4">
          <div class="rounded-lg border border-[#e5e7eb] bg-white px-4 py-3">
            <div class="text-[12px] text-[#6b7280]">成员数</div>
            <div class="mt-1 text-[22px] font-semibold tabular-nums text-[#111827]">{{ totals.members }}</div>
          </div>
          <div class="rounded-lg border border-[#e5e7eb] bg-white px-4 py-3">
            <div class="text-[12px] text-[#6b7280]">消息总数</div>
            <div class="mt-1 text-[22px] font-semibold tabular-nums text-[#111827]">{{ formatNumber(totals.messages) }}</div>
          </div>
          <div class="rounded-lg border border-[#e5e7eb] bg-white px-4 py-3">
            <div class="text-[12px] text-[#6b7280]">话最多</div>
            <div class="mt-1 truncate text-[15px] font-medium text-[#111827]">{{ topMemberName }}</div>
          </div>
          <div class="rounded-lg border border-[#e5e7eb] bg-white px-4 py-3">
            <div class="text-[12px] text-[#6b7280]">数据范围</div>
            <div class="mt-1 truncate text-[13px] text-[#111827]">{{ rangeText }}</div>
          </div>
        </div>
      </header>

      <div class="min-h-0 flex-1 overflow-auto p-5">
        <div v-if="!selectedUsername" class="rounded-lg border border-[#e5e7eb] bg-white px-4 py-8 text-center text-[13px] text-[#6b7280]">
          从左侧选择一个群聊或联系人，查看其成员发言统计
        </div>

        <div v-else-if="buildMessage" class="mb-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] leading-relaxed text-amber-900">
          {{ buildMessage }}
        </div>

        <ErrorNotice v-else-if="error" :message="error" />

        <div v-if="selectedUsername" class="overflow-hidden rounded-lg border border-[#e5e7eb] bg-white">
          <div class="flex items-center justify-between border-b border-[#e5e7eb] px-4 py-3">
            <div class="text-[14px] font-medium text-[#111827]">成员总览</div>
            <div v-if="overview?.freshness?.message" class="text-[11px] text-[#9ca3af]">{{ overview.freshness.message }}</div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full min-w-[860px] border-collapse text-[13px]">
              <thead>
                <tr class="bg-[#f9fafb] text-left text-[12px] text-[#6b7280]">
                  <th class="w-[60px] px-4 py-2.5 font-medium">#</th>
                  <th class="px-4 py-2.5 font-medium">成员</th>
                  <th class="px-4 py-2.5 font-medium">wxid</th>
                  <th class="w-[120px] px-4 py-2.5 text-right font-medium">索引条目</th>
                  <th class="px-4 py-2.5 font-medium">主题命中概览</th>
                  <th class="px-4 py-2.5 font-medium">当前可见主线</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="loading && !members.length">
                  <td colspan="6" class="px-4 py-8 text-center text-[13px] text-[#6b7280]">正在统计成员发言…</td>
                </tr>
                <tr v-else-if="!members.length">
                  <td colspan="6" class="px-4 py-8 text-center text-[13px] text-[#6b7280]">该会话暂无可统计的消息</td>
                </tr>
                <tr
                  v-for="(member, index) in members"
                  :key="member.wxid"
                  class="border-t border-[#f3f4f6] align-top transition hover:bg-[#fcfffd]"
                >
                  <td class="px-4 py-3 tabular-nums text-[#9ca3af]">{{ index + 1 }}</td>
                  <td class="px-4 py-3">
                    <div class="flex items-center gap-2">
                      <span class="font-medium text-[#111827]">{{ member.displayName || member.wxid }}</span>
                      <span
                        v-if="member.isSelf"
                        class="rounded-full bg-[#f0fdf4] px-1.5 py-0.5 text-[10px] font-medium text-[#047857]"
                      >本人</span>
                    </div>
                    <div class="mt-0.5 text-[11px] text-[#9ca3af]">占全群 {{ member.share }}%</div>
                  </td>
                  <td class="px-4 py-3">
                    <code class="rounded bg-[#f3f4f6] px-1.5 py-0.5 text-[11px] text-[#6b7280]" :class="{ 'privacy-blur': privacyMode }">{{ member.wxid }}</code>
                  </td>
                  <td class="px-4 py-3 text-right">
                    <div class="font-semibold tabular-nums text-[#111827]">{{ formatNumber(member.messageCount) }}</div>
                    <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-[#f3f4f6]">
                      <div class="h-full rounded-full bg-[#07C160]" :style="{ width: barWidth(member.share) }"></div>
                    </div>
                  </td>
                  <td class="px-4 py-3">
                    <div v-if="member.topics && member.topics.length" class="flex flex-wrap gap-1">
                      <span
                        v-for="topic in member.topics"
                        :key="topic.word"
                        class="rounded bg-[#f3f4f6] px-1.5 py-0.5 text-[11px] text-[#374151]"
                      >{{ topic.word }}<span class="ml-1 text-[#9ca3af]">{{ topic.count }}</span></span>
                    </div>
                    <span v-else class="text-[12px] text-[#9ca3af]">无有效文本</span>
                  </td>
                  <td class="px-4 py-3 leading-relaxed text-[#374151]">{{ member.mainThread }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { storeToRefs } from 'pinia'
import { useChatAccountsStore } from '~/stores/chatAccounts'
import { usePrivacyStore } from '~/stores/privacy'

useHead({ title: '成员发言统计 - 微信数据分析助手' })

const api = useApi()
const chatAccounts = useChatAccountsStore()
const { selectedAccount } = storeToRefs(chatAccounts)
const privacyStore = usePrivacyStore()
const { privacyMode } = storeToRefs(privacyStore)

const sessionKeyword = ref('')
const sessions = ref([])
const sessionsLoading = ref(false)
const sessionsError = ref('')
const selectedUsername = ref('')
const collapsed = reactive({ groups: false, contacts: false })

const overview = ref(null)
const loading = ref(false)
const error = ref('')
const topicCount = ref(8)
let requestId = 0

const members = computed(() => (overview.value && Array.isArray(overview.value.members) ? overview.value.members : []))
const totals = computed(() => (overview.value && overview.value.totals) || { members: 0, messages: 0 })

const looksLikeRawId = (value) => {
  const text = String(value || '').trim()
  return !!(text.startsWith('wxid_') || text.endsWith('@chatroom'))
}

const sessionName = (item) => {
  const c = item && typeof item === 'object' ? item : {}
  const raw = String(c.username || '').trim()
  for (const value of [c.displayName, c.name, c.remark, c.nickname]) {
    const text = String(value || '').trim()
    if (text && text !== raw && !looksLikeRawId(text)) return text
  }
  return raw || '未知会话'
}

const sessionInitial = (item) => {
  const name = sessionName(item)
  return name && name !== '未知会话' ? name.slice(0, 1) : '?'
}

const isGroupSession = (item) => String(item?.username || '').endsWith('@chatroom')

const filteredSessions = computed(() => {
  const kw = String(sessionKeyword.value || '').trim().toLowerCase()
  const list = Array.isArray(sessions.value) ? sessions.value : []
  if (!kw) return list
  return list.filter((item) => {
    const hay = `${sessionName(item)} ${item?.username || ''}`.toLowerCase()
    return hay.includes(kw)
  })
})

const sessionGroups = computed(() => [
  { key: 'groups', label: '群聊', items: filteredSessions.value.filter(isGroupSession) },
  { key: 'contacts', label: '联系人', items: filteredSessions.value.filter((item) => !isGroupSession(item)) },
])

const currentSessionName = computed(() => {
  if (!selectedUsername.value) return '未选择会话'
  const hit = sessions.value.find((item) => item?.username === selectedUsername.value)
  return hit ? sessionName(hit) : selectedUsername.value
})

const buildMessage = computed(() => {
  const status = String(overview.value?.status || '')
  if (status === 'index_building') return '消息索引正在构建中，请稍后点击「重新统计」。'
  if (status === 'index_error') return '消息索引构建失败，请到聊天页重建索引后重试。'
  return ''
})

const topMemberName = computed(() => {
  const first = members.value[0]
  if (!first) return '—'
  return first.displayName || first.wxid
})

const rangeText = computed(() => {
  const range = overview.value?.range
  if (!range) return '—'
  const start = Number(range.startTime || 0)
  const end = Number(range.endTime || 0)
  if (!start && !end) return `全部 ${formatNumber(range.messageCount || 0)} 条`
  return `${start ? formatDate(start) : '最早'} ~ ${end ? formatDate(end) : '最新'}`
})

const formatNumber = (value) => Number(value || 0).toLocaleString('zh-CN')

const formatDate = (ts) => {
  const value = Number(ts || 0)
  if (!value) return '—'
  const d = new Date(value * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const barWidth = (share) => {
  const value = Number(share || 0)
  const pct = members.value.length ? Math.min(100, (value / Math.max(1, maxShare.value)) * 100) : 0
  return `${pct.toFixed(1)}%`
}

const maxShare = computed(() => {
  return members.value.reduce((max, item) => Math.max(max, Number(item?.share || 0)), 0)
})

const toggleGroup = (key) => {
  collapsed[key] = !collapsed[key]
}

const selectSession = (username) => {
  const next = String(username || '').trim()
  if (!next || next === selectedUsername.value) return
  selectedUsername.value = next
  loadOverview()
}

const loadSessions = async () => {
  sessionsLoading.value = true
  sessionsError.value = ''
  try {
    const data = await api.listChatSessions({ limit: 500, source: 'auto' })
    const list = Array.isArray(data?.sessions) ? data.sessions : Array.isArray(data?.items) ? data.items : []
    sessions.value = list
    if (!selectedUsername.value) {
      const firstGroup = list.find(isGroupSession)
      selectedUsername.value = String(firstGroup?.username || list[0]?.username || '').trim()
      if (selectedUsername.value) await loadOverview()
    }
  } catch (e) {
    sessionsError.value = String(e?.message || '会话列表加载失败')
    sessions.value = []
  } finally {
    sessionsLoading.value = false
  }
}

const loadOverview = async (options = {}) => {
  if (!selectedUsername.value) return
  const traceId = ++requestId
  loading.value = true
  error.value = ''
  try {
    const data = await api.getChatMemberOverview({
      username: selectedUsername.value,
      account: selectedAccount.value || null,
      topics: topicCount.value,
      refresh: !!options.force,
    })
    if (traceId !== requestId) return
    overview.value = data && typeof data === 'object' ? data : null
  } catch (e) {
    if (traceId !== requestId) return
    overview.value = null
    error.value = String(e?.message || '成员发言统计加载失败')
  } finally {
    if (traceId === requestId) loading.value = false
  }
}

watch(selectedAccount, () => {
  sessions.value = []
  selectedUsername.value = ''
  overview.value = null
  loadSessions()
})

watch(topicCount, () => {
  if (selectedUsername.value) loadOverview()
})

onMounted(() => {
  loadSessions()
})
</script>
