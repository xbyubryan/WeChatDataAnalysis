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
              class="rounded-md border px-3 py-1.5 text-[12px] transition disabled:opacity-60"
              :class="aiMainThread
                ? 'border-[#07C160] bg-[#f0fdf4] text-[#047857]'
                : 'border-[#e5e7eb] text-[#374151] hover:border-[#07C160] hover:text-[#07C160]'"
              :disabled="loading"
              :title="aiMainThread ? '已开启：由配置的 LLM 生成主线（会把截断的发言样本发到模型端点）' : '开启后由 LLM 生成主线'"
              @click="aiMainThread = !aiMainThread"
            >
              AI 主线{{ aiMainThread ? '·开' : '' }}
            </button>
            <button
              type="button"
              class="rounded-md border border-[#e5e7eb] px-3 py-1.5 text-[12px] text-[#374151] transition hover:border-[#07C160] hover:text-[#07C160] disabled:opacity-60"
              :disabled="loading"
              @click="handleRefresh"
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

        <!-- AI 群聊总结报告 -->
        <div v-if="selectedUsername && aiMainThread && (summaryLoading || summary)" class="mb-4 overflow-hidden rounded-lg border border-[#e5e7eb] bg-white">
          <div class="flex items-center justify-between border-b border-[#e5e7eb] px-4 py-3">
            <div class="flex items-center gap-2">
              <span class="rounded bg-[#f0fdf4] px-1.5 py-0.5 text-[10px] font-medium text-[#047857]">AI</span>
              <span class="text-[14px] font-medium text-[#111827]">群聊总结报告</span>
            </div>
            <div class="flex items-center gap-3">
              <span v-if="exportError" class="text-[11px] text-amber-600">{{ exportError }}</span>
              <span v-if="summaryNotice" class="text-[11px]" :class="summary?.llm?.error ? 'text-amber-600' : 'text-[#9ca3af]'">{{ summaryNotice }}</span>
              <button
                v-if="summaryReport && !summaryLoading"
                type="button"
                class="rounded-md border border-[#e5e7eb] px-2.5 py-1 text-[11px] text-[#374151] transition hover:border-[#07C160] hover:text-[#07C160] disabled:opacity-60"
                :disabled="exporting"
                @click="handleExportPoster"
              >
                {{ exporting ? '生成中…' : '导出图片' }}
              </button>
            </div>
          </div>

          <div v-if="summaryLoading" class="px-4 py-10 text-center text-[13px] text-[#6b7280]">
            正在生成群聊总结报告，首次生成约需 10~30 秒…
          </div>

          <template v-else-if="summaryReport">
            <div class="border-b border-[#f3f4f6] px-5 py-4">
              <div class="text-[16px] font-semibold leading-snug text-[#111827]">{{ summaryReport.headline }}</div>
              <p v-if="summaryReport.overview" class="mt-2 text-[13px] leading-relaxed text-[#374151]">{{ summaryReport.overview }}</p>
            </div>

            <div class="grid md:grid-cols-2">
              <div v-if="summaryReport.topics?.length" class="border-b border-[#f3f4f6] px-5 py-4 md:border-r">
                <div class="text-[12px] font-medium text-[#6b7280]">主要话题</div>
                <div v-for="(topic, ti) in summaryReport.topics" :key="ti" class="mt-3">
                  <div class="flex items-center gap-1.5 text-[13px] font-medium text-[#111827]">
                    <span class="inline-block h-1.5 w-1.5 rounded-full bg-[#07C160]"></span>{{ topic.title }}
                  </div>
                  <p class="mt-1 pl-3 text-[12px] leading-relaxed text-[#4b5563]">{{ topic.summary }}</p>
                </div>
              </div>

              <div v-if="summaryReport.timeline?.length" class="border-b border-[#f3f4f6] px-5 py-4">
                <div class="text-[12px] font-medium text-[#6b7280]">时间线</div>
                <div v-for="(seg, si) in summaryReport.timeline" :key="si" class="mt-3 flex items-start gap-2.5">
                  <span class="shrink-0 rounded bg-[#f0fdf4] px-1.5 py-0.5 text-[11px] font-medium text-[#047857]">{{ seg.period }}</span>
                  <ul class="min-w-0">
                    <li v-for="(point, pi) in seg.points" :key="pi" class="text-[12px] leading-relaxed text-[#4b5563]">· {{ point }}</li>
                  </ul>
                </div>
              </div>
            </div>

            <div v-if="summaryReport.highlights?.length" class="border-b border-[#f3f4f6] px-5 py-4">
              <div class="text-[12px] font-medium text-[#6b7280]">值得关注的原话</div>
              <div v-for="(h, hi) in summaryReport.highlights" :key="hi" class="mt-2 rounded-md bg-[#f9fafb] px-3 py-2">
                <div class="text-[12px] leading-relaxed text-[#111827]">"{{ h.text }}"</div>
                <div class="mt-1 text-[11px] text-[#9ca3af]">
                  —— {{ h.sender || '未知' }}<span v-if="h.reason" class="ml-2 text-[#047857]">{{ h.reason }}</span>
                </div>
              </div>
            </div>

            <div v-if="summaryTopMembers.length" class="px-5 py-4">
              <div class="text-[12px] font-medium text-[#6b7280]">活跃成员 Top {{ summaryTopMembers.length }}</div>
              <div class="mt-2.5 flex flex-wrap gap-2">
                <div
                  v-for="(m, mi) in summaryTopMembers"
                  :key="m.wxid || mi"
                  class="flex items-center gap-2 rounded-full border border-[#e5e7eb] px-3 py-1.5"
                >
                  <span class="text-[11px] tabular-nums text-[#9ca3af]">{{ mi + 1 }}</span>
                  <span class="text-[12px] font-medium text-[#111827]">{{ m.displayName || m.wxid }}</span>
                  <span class="text-[11px] tabular-nums text-[#6b7280]">{{ formatNumber(m.messageCount) }} 条 · {{ m.share }}%</span>
                </div>
              </div>
            </div>
          </template>

          <div v-else class="px-4 py-6 text-center text-[13px] text-[#6b7280]">
            {{ summary?.llm?.error || '总结报告生成失败，请稍后重试' }}
          </div>
        </div>

        <div v-if="selectedUsername" class="overflow-hidden rounded-lg border border-[#e5e7eb] bg-white">
          <div class="flex items-center justify-between border-b border-[#e5e7eb] px-4 py-3">
            <div class="text-[14px] font-medium text-[#111827]">成员总览</div>
            <div class="flex items-center gap-3">
              <div v-if="llmNotice" class="text-[11px]" :class="overview?.llm?.error ? 'text-amber-600' : 'text-[#047857]'">{{ llmNotice }}</div>
              <div v-if="overview?.freshness?.message" class="text-[11px] text-[#9ca3af]">{{ overview.freshness.message }}</div>
            </div>
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
                  <td class="px-4 py-3 leading-relaxed text-[#374151]">
                    <span
                      v-if="member.mainThreadSource === 'llm'"
                      class="mr-1.5 rounded-full bg-[#f0fdf4] px-1.5 py-0.5 text-[10px] font-medium text-[#047857]"
                    >AI</span>{{ member.mainThread }}
                  </td>
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
import { downloadReportPoster } from '~/utils/reportPoster'

useHead({ title: '成员发言统计 - 微信数据分析助手' })

const api = useApi()
const route = useRoute()
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
const aiMainThread = ref(false)
const summary = ref(null)
const summaryLoading = ref(false)
const exporting = ref(false)
let requestId = 0
let summaryRequestId = 0

const members = computed(() => (overview.value && Array.isArray(overview.value.members) ? overview.value.members : []))
const totals = computed(() => (overview.value && overview.value.totals) || { members: 0, messages: 0 })
const summaryReport = computed(() => (summary.value && summary.value.report) || null)
const summaryTopMembers = computed(() => (Array.isArray(summary.value?.topMembers) ? summary.value.topMembers : []))
const summaryNotice = computed(() => {
  const llm = summary.value && summary.value.llm
  if (!llm) return ''
  if (llm.error) return String(llm.error)
  if (!llm.configured) return ''
  return `${llm.model || 'LLM'} 生成${llm.cached ? '（缓存）' : ''}`
})
const llmNotice = computed(() => {
  const meta = overview.value && overview.value.llm
  if (!meta) return ''
  if (meta.error) return String(meta.error)
  if (meta.generated != null) return `AI 主线：${meta.model || 'LLM'} 生成 ${meta.generated} 条${meta.cached ? '（缓存）' : ''}`
  return ''
})

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
  summary.value = null
  loadOverview()
  if (aiMainThread.value) loadGroupSummary()
}

const loadSessions = async () => {
  sessionsLoading.value = true
  sessionsError.value = ''
  try {
    const data = await api.listChatSessions({ limit: 500, source: 'auto' })
    const list = Array.isArray(data?.sessions) ? data.sessions : Array.isArray(data?.items) ? data.items : []
    sessions.value = list
    if (!selectedUsername.value) {
      // 从群聊工具栏跳转进来时带 ?username=，优先预选该会话
      const fromQuery = String(route.query.username || '').trim()
      const hit = fromQuery ? list.find((item) => String(item?.username || '').trim() === fromQuery) : null
      const fallback = list.find(isGroupSession)
      // query 指定的会话即使不在列表前 500 条里也直接选中
      selectedUsername.value = String(hit?.username || fromQuery || (fallback || list[0])?.username || '').trim()
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
      main_thread: aiMainThread.value ? 'llm' : 'rule',
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

const loadGroupSummary = async () => {
  if (!selectedUsername.value) return
  const traceId = ++summaryRequestId
  summaryLoading.value = true
  try {
    const data = await api.getChatGroupSummary({
      username: selectedUsername.value,
      account: selectedAccount.value || null,
    })
    if (traceId !== summaryRequestId) return
    summary.value = data && typeof data === 'object' ? data : null
  } catch (e) {
    if (traceId !== summaryRequestId) return
    summary.value = { report: null, llm: { configured: false, error: String(e?.message || '群聊总结加载失败') } }
  } finally {
    if (traceId === summaryRequestId) summaryLoading.value = false
  }
}

const handleRefresh = () => {
  loadOverview({ force: true })
  if (aiMainThread.value) loadGroupSummary()
}

const exportError = ref('')

const handleExportPoster = async () => {
  if (!summaryReport.value || exporting.value) return
  exporting.value = true
  exportError.value = ''
  try {
    await downloadReportPoster({
      groupName: summary.value?.groupName || currentSessionName.value,
      report: summaryReport.value,
      topMembers: summaryTopMembers.value,
      totals: totals.value,
      rangeText: rangeText.value,
      model: summary.value?.llm?.model || 'AI',
    })
  } catch (e) {
    exportError.value = String(e?.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

watch(selectedAccount, () => {
  sessions.value = []
  selectedUsername.value = ''
  overview.value = null
  summary.value = null
  loadSessions()
})

watch(topicCount, () => {
  if (selectedUsername.value) loadOverview()
})

watch(aiMainThread, (enabled) => {
  summary.value = null
  if (!selectedUsername.value) return
  loadOverview()
  if (enabled) loadGroupSummary()
})

onMounted(() => {
  loadSessions()
})
</script>
