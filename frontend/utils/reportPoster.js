// 群聊总结报告海报导出（纯 Canvas 手绘，零依赖）。
// 风格：浅色长图报告，主色微信绿 #07C160，适配 1080 宽 2x 高清导出。

const FONT = '"PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif'

const C = {
  bg: '#f5f6f8',
  card: '#ffffff',
  ink: '#111827',
  sub: '#4b5563',
  faint: '#9ca3af',
  brand: '#07C160',
  brandDark: '#047857',
  brandBg: '#eafaf1',
  line: '#eceef1',
  quoteBg: '#f7f8fa',
}

const W = 1080
const PAD = 64
const CW = W - PAD * 2
const SCALE = 2

function roundRectPath(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + rr, y)
  ctx.arcTo(x + w, y, x + w, y + h, rr)
  ctx.arcTo(x + w, y + h, x, y + h, rr)
  ctx.arcTo(x, y + h, x, y, rr)
  ctx.arcTo(x, y, x + w, y, rr)
  ctx.closePath()
}

function wrapText(ctx, text, maxWidth) {
  const lines = []
  const paragraphs = String(text || '').split('\n')
  for (const para of paragraphs) {
    if (!para) {
      lines.push('')
      continue
    }
    let line = ''
    for (const ch of para) {
      const test = line + ch
      if (line && ctx.measureText(test).width > maxWidth) {
        lines.push(line)
        line = ch
      } else {
        line = test
      }
    }
    if (line) lines.push(line)
  }
  return lines.length ? lines : ['']
}

// 统一渲染入口：dry=true 时只测量不绘制。
// 返回 { totalH, cardX, cardTop, cardW, cardH } 供外部先铺卡片底。
function render(ctx, data, dry) {
  const { groupName, report, topMembers, totals, rangeText, model } = data

  const cardX = 40
  const cardTop = 40
  const cardW = W - 80
  const innerX = cardX + PAD - 24
  const innerW = cardW - (PAD - 24) * 2

  const draw = (fn) => {
    if (!dry) fn()
  }

  // ---------- 头部 ----------
  let cy = cardTop
  cy += 52
  draw(() => {
    ctx.fillStyle = C.brand
    ctx.font = `600 15px ${FONT}`
    ctx.textBaseline = 'alphabetic'
    ctx.fillText('WECHAT GROUP SUMMARY', innerX, cy)
  })
  cy += 15 + 26

  draw(() => {
    ctx.fillStyle = C.ink
    ctx.font = `700 40px ${FONT}`
    ctx.fillText(String(groupName || '群聊总结'), innerX, cy)
  })
  cy += 40 + 18

  draw(() => {
    ctx.fillStyle = C.faint
    ctx.font = `400 14px ${FONT}`
    ctx.fillText(`${rangeText || ''} · 由 ${model || 'AI'} 生成`, innerX, cy)
  })
  cy += 14 + 34

  // ---------- 统计条 ----------
  const stats = [
    { label: '发言成员', value: `${totals?.members ?? '—'}` },
    { label: '消息总数', value: Number(totals?.messages || 0).toLocaleString('zh-CN') },
    { label: '话题数', value: `${(report?.topics || []).length}` },
    { label: '精选原话', value: `${(report?.highlights || []).length}` },
  ]
  const colW = innerW / stats.length
  draw(() => {
    ctx.strokeStyle = C.line
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(innerX, cy)
    ctx.lineTo(innerX + innerW, cy)
    ctx.stroke()
  })
  cy += 30
  stats.forEach((s, i) => {
    const x = innerX + i * colW
    draw(() => {
      ctx.fillStyle = C.faint
      ctx.font = `400 13px ${FONT}`
      ctx.fillText(s.label, x, cy)
      ctx.fillStyle = C.ink
      ctx.font = `700 30px ${FONT}`
      ctx.fillText(s.value, x, cy + 40)
      if (i > 0) {
        ctx.strokeStyle = C.line
        ctx.beginPath()
        ctx.moveTo(x - 18, cy - 8)
        ctx.lineTo(x - 18, cy + 40)
        ctx.stroke()
      }
    })
  })
  cy += 40 + 44

  // ---------- 定调 + 摘要 ----------
  ctx.font = `700 26px ${FONT}`
  const headlineLines = wrapText(ctx, report?.headline || '', innerW - 28)
  draw(() => {
    ctx.fillStyle = C.brand
    roundRectPath(ctx, innerX, cy - 20, 6, headlineLines.length * 36 - 8, 3)
    ctx.fill()
    ctx.fillStyle = C.ink
    ctx.font = `700 26px ${FONT}`
    headlineLines.forEach((ln, i) => ctx.fillText(ln, innerX + 20, cy + i * 36))
  })
  cy += headlineLines.length * 36 + 12

  ctx.font = `400 15px ${FONT}`
  const overviewLines = wrapText(ctx, report?.overview || '', innerW)
  draw(() => {
    ctx.fillStyle = C.sub
    ctx.font = `400 15px ${FONT}`
    overviewLines.forEach((ln, i) => ctx.fillText(ln, innerX, cy + i * 27))
  })
  cy += overviewLines.length * 27 + 40

  const sectionTitle = (text) => {
    draw(() => {
      ctx.fillStyle = C.faint
      ctx.font = `600 13px ${FONT}`
      ctx.fillText(text, innerX, cy)
      ctx.strokeStyle = C.line
      ctx.beginPath()
      ctx.moveTo(innerX, cy + 12)
      ctx.lineTo(innerX + innerW, cy + 12)
      ctx.stroke()
    })
    cy += 13 + 12 + 22
  }

  // ---------- 主要话题 ----------
  const topics = (report?.topics || []).slice(0, 6)
  if (topics.length) {
    sectionTitle('主要话题')
    for (const t of topics) {
      ctx.font = `700 17px ${FONT}`
      const titleLines = wrapText(ctx, t.title || '', innerW - 24)
      ctx.font = `400 14px ${FONT}`
      const sumLines = wrapText(ctx, t.summary || '', innerW - 24)
      draw(() => {
        ctx.fillStyle = C.brand
        ctx.beginPath()
        ctx.arc(innerX + 5, cy - 5, 5, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = C.ink
        ctx.font = `700 17px ${FONT}`
        titleLines.forEach((ln, i) => ctx.fillText(ln, innerX + 24, cy + i * 25))
        ctx.fillStyle = C.sub
        ctx.font = `400 14px ${FONT}`
        sumLines.forEach((ln, i) => ctx.fillText(ln, innerX + 24, cy + titleLines.length * 25 + 4 + i * 24))
      })
      cy += titleLines.length * 25 + (sumLines.length ? 4 + sumLines.length * 24 : 0) + 22
    }
    cy += 18
  }

  // ---------- 时间线 ----------
  const timeline = (report?.timeline || []).slice(0, 8)
  if (timeline.length) {
    sectionTitle('时间线')
    for (const seg of timeline) {
      ctx.font = `600 13px ${FONT}`
      const period = String(seg.period || '时段')
      const chipW = Math.min(innerW, ctx.measureText(period).width + 24)
      const points = (seg.points || []).slice(0, 5)
      const pointLines = []
      ctx.font = `400 14px ${FONT}`
      for (const p of points) {
        for (const ln of wrapText(ctx, p, innerW - chipW - 20)) pointLines.push(ln)
      }
      const blockH = Math.max(28, pointLines.length * 24)
      draw(() => {
        ctx.fillStyle = C.brandBg
        roundRectPath(ctx, innerX, cy - 18, chipW, 28, 14)
        ctx.fill()
        ctx.fillStyle = C.brandDark
        ctx.font = `600 13px ${FONT}`
        ctx.fillText(period, innerX + 12, cy + 1)
        ctx.fillStyle = C.sub
        ctx.font = `400 14px ${FONT}`
        pointLines.forEach((ln, i) => ctx.fillText(`· ${ln}`, innerX + chipW + 14, cy - 16 + 19 + i * 24))
      })
      cy += blockH + 16
    }
    cy += 18
  }

  // ---------- 值得关注的原话 ----------
  const highlights = (report?.highlights || []).slice(0, 8)
  if (highlights.length) {
    sectionTitle('值得关注的原话')
    for (const h of highlights) {
      ctx.font = `400 14px ${FONT}`
      const textIndent = 48
      const textLines = wrapText(ctx, `"${h.text || ''}"`, innerW - textIndent - 24)
      const boxH = textLines.length * 25 + 58
      draw(() => {
        ctx.fillStyle = C.quoteBg
        roundRectPath(ctx, innerX, cy, innerW, boxH, 12)
        ctx.fill()
        ctx.fillStyle = C.brand
        ctx.font = `700 30px ${FONT}`
        ctx.fillText('“', innerX + 14, cy + 34)
        ctx.fillStyle = C.ink
        ctx.font = `400 14px ${FONT}`
        textLines.forEach((ln, i) => ctx.fillText(ln, innerX + textIndent, cy + 28 + i * 25))
        ctx.fillStyle = C.faint
        ctx.font = `400 12px ${FONT}`
        const meta = `—— ${h.sender || '未知'}`
        ctx.fillText(meta, innerX + textIndent, cy + boxH - 16)
        if (h.reason) {
          ctx.fillStyle = C.brandDark
          const metaW = ctx.measureText(meta).width
          ctx.fillText(h.reason, innerX + textIndent + metaW + 14, cy + boxH - 16)
        }
      })
      cy += boxH + 14
    }
    cy += 18
  }

  // ---------- 活跃成员 ----------
  const members = (topMembers || []).slice(0, 10)
  if (members.length) {
    sectionTitle(`活跃成员 Top ${members.length}`)
    const maxCount = Math.max(1, ...members.map((m) => Number(m.messageCount || 0)))
    const barX = innerX + 360
    const statReserve = 170 // 右侧统计文字预留区
    const maxBarW = innerW - 360 - statReserve
    for (let i = 0; i < members.length; i++) {
      const m = members[i]
      const name = String(m.displayName || m.wxid || '未知')
      const barW = Math.max(6, Math.round((Number(m.messageCount || 0) / maxCount) * maxBarW))
      draw(() => {
        ctx.fillStyle = C.faint
        ctx.font = `600 14px ${FONT}`
        ctx.fillText(String(i + 1).padStart(2, '0'), innerX, cy)
        ctx.fillStyle = C.ink
        ctx.font = `500 15px ${FONT}`
        const nameMax = 300
        let shown = name
        while (shown.length > 1 && ctx.measureText(shown).width > nameMax) shown = shown.slice(0, -1)
        if (shown !== name) shown += '…'
        ctx.fillText(shown, innerX + 44, cy)
        ctx.fillStyle = C.brandBg
        roundRectPath(ctx, barX, cy - 11, maxBarW, 8, 4)
        ctx.fill()
        ctx.fillStyle = C.brand
        roundRectPath(ctx, barX, cy - 11, barW, 8, 4)
        ctx.fill()
        ctx.fillStyle = C.sub
        ctx.font = `400 13px ${FONT}`
        const stat = `${Number(m.messageCount || 0).toLocaleString('zh-CN')} 条 · ${m.share ?? 0}%`
        const statW = ctx.measureText(stat).width
        ctx.fillText(stat, innerX + innerW - statW, cy)
      })
      cy += 34
    }
    cy += 18
  }

  // ---------- 页脚 ----------
  draw(() => {
    ctx.strokeStyle = C.line
    ctx.beginPath()
    ctx.moveTo(innerX, cy)
    ctx.lineTo(innerX + innerW, cy)
    ctx.stroke()
    ctx.fillStyle = C.faint
    ctx.font = `400 12px ${FONT}`
    const now = new Date()
    const pad2 = (n) => String(n).padStart(2, '0')
    const stamp = `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())} ${pad2(now.getHours())}:${pad2(now.getMinutes())}`
    ctx.fillText(`由 WeChatDataAnalysis 生成 · ${stamp} · AI 内容仅供参考`, innerX, cy + 28)
  })
  cy += 28 + 46

  // ---------- 收尾：返回卡片尺寸 ----------
  const cardH = cy - cardTop
  return { totalH: cardTop + cardH + 40, cardX, cardTop, cardW, cardH }
}

export async function downloadReportPoster(data) {
  // 第一遍：测量总高度与卡片位置
  const measureCanvas = document.createElement('canvas')
  measureCanvas.width = W
  measureCanvas.height = 10
  const measureCtx = measureCanvas.getContext('2d')
  const m = render(measureCtx, data, true)

  // 第二遍：正式绘制（2x 高清）
  const canvas = document.createElement('canvas')
  canvas.width = W * SCALE
  canvas.height = Math.ceil(m.totalH) * SCALE
  const ctx = canvas.getContext('2d')
  ctx.scale(SCALE, SCALE)

  // 外背景
  ctx.fillStyle = C.bg
  ctx.fillRect(0, 0, W, m.totalH)

  // 卡片白底 + 顶部色带（按卡片圆角裁切，避免色带溢出圆角）
  ctx.save()
  roundRectPath(ctx, m.cardX, m.cardTop, m.cardW, m.cardH, 20)
  ctx.fillStyle = C.card
  ctx.fill()
  ctx.clip()
  ctx.fillStyle = C.brand
  ctx.fillRect(m.cardX, m.cardTop, m.cardW, 8)
  ctx.restore()

  // 内容
  render(ctx, data, false)

  const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
  if (!blob) throw new Error('图片生成失败')

  const safeName = String(data.groupName || '群聊').replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 40)
  const now = new Date()
  const pad2 = (n) => String(n).padStart(2, '0')
  const stamp = `${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `群聊总结_${safeName}_${stamp}.png`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}
