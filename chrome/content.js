/**
 * 58 爬虫助手 — Content Script
 *
 * 在页面右上角注入两个按钮，通过 Shadow DOM 隔离样式。
 * 遵循 ax-ui-kit 设计 token（HTML CDN 模式）。
 *
 * 按钮 1：Browser 抓取 → POST /api/queue (fetch_mode: browser)
 * 按钮 2：HTML 直接解析 → POST /api/queue (fetch_mode: raw, html)
 */

(function () {
  'use strict'

  // —— 仅在顶层窗口运行，避免 iframe 重复注入
  if (window.top !== window.self) return

  const API_BASE = 'http://localhost:5000'

  // =========================================================================
  // API 调用
  // =========================================================================

  /**
   * 将当前页面加入爬虫队列（Browser 模式）
   */
  async function enqueueBrowser() {
    const url = window.location.href

    const res = await fetch(`${API_BASE}/api/queue`, {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
      headers: {
        'accept': 'application/json, text/plain, */*',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ url, fetch_mode: 'browser' }),
    })

    if (!res.ok) {
      const text = await res.text().catch(() => '')
      throw new Error(text || `HTTP ${res.status}`)
    }

    return res.json()
  }

  /**
   * 将当前页面 HTML 直接发送解析（Raw 模式，跳过抓取）
   */
  async function enqueueHtml() {
    const url = window.location.href
    const html = document.documentElement.outerHTML

    const res = await fetch(`${API_BASE}/api/queue`, {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
      headers: {
        'accept': 'application/json, text/plain, */*',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ url, html }),
    })

    if (!res.ok) {
      const text = await res.text().catch(() => '')
      throw new Error(text || `HTTP ${res.status}`)
    }

    return res.json()
  }

  // =========================================================================
  // UI 渲染
  // =========================================================================

  /**
   * 构建 Shadow DOM 内完整 UI
   */
  function buildUI(shadow) {
    // -- 样式（遵循 ax-ui-kit HTML CDN 设计 token） --
    const style = document.createElement('style')
    style.textContent = `
      :host {
        all: initial;
      }

      .crawler-panel {
        position: fixed;
        top: 16px;
        right: 16px;
        z-index: 2147483647;
        display: flex;
        flex-direction: column;
        gap: 8px;                    /* gap-sm */
        font-family: 'Geist', 'PingFang SC', 'Microsoft YaHei', sans-serif;
      }

      /*
       * 按钮 — 模拟 AxButton 规格
       * variant: primary → bg-primary text-on-primary
       * variant: outline → text-primary bg-white border-outline-variant
       * size: md → h-[32px] px-3 text-label-md
       * rounded: lg → 4px
       * shadow: pro-shadow 等价
       */
      .ax-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 4px;                   /* gap-ax-xs */
        height: 32px;               /* control-md */
        padding: 0 12px;
        border: none;
        border-radius: 4px;         /* rounded-lg */
        font-family: 'JetBrains Mono', 'PingFang SC', 'Microsoft YaHei', monospace;
        font-size: 12px;            /* label-md */
        font-weight: 500;
        line-height: 16px;
        letter-spacing: 0.02em;
        cursor: pointer;
        user-select: none;
        white-space: nowrap;
        outline: none;
        transition: opacity 0.15s, background-color 0.15s, box-shadow 0.15s;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);  /* pro-shadow */
      }

      /* primary */
      .ax-btn--primary {
        background: #000000;         /* primary */
        color: #ffffff;              /* on-primary */
      }
      .ax-btn--primary:hover {
        opacity: 0.9;
      }

      /* outline */
      .ax-btn--outline {
        background: #ffffff;
        color: #000000;              /* text-primary */
        border: 1px solid #c8c5ca;   /* outline-variant */
      }
      .ax-btn--outline:hover {
        background: #f3f3f4;         /* surface-container-low */
      }

      /* 加载态 */
      .ax-btn--loading {
        opacity: 0.6;
        cursor: wait;
        pointer-events: none;
      }

      /* SVG 图标容器 */
      .ax-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }

      .ax-icon svg {
        width: 16px;
        height: 16px;
        display: block;
      }

      /* 加载旋转 */
      .ax-spinner {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        animation: ax-spin 0.6s linear infinite;
      }

      .ax-spinner svg {
        width: 14px;
        height: 14px;
        display: block;
      }

      @keyframes ax-spin {
        to { transform: rotate(360deg); }
      }

      /* 状态提示条 */
      .ax-toast {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 6px 12px;
        border-radius: 4px;
        font-family: 'Geist', 'PingFang SC', 'Microsoft YaHei', sans-serif;
        font-size: 12px;
        line-height: 16px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
        opacity: 0;
        transform: translateY(-4px);
        transition: opacity 0.25s, transform 0.25s;
        pointer-events: none;
      }

      .ax-toast--visible {
        opacity: 1;
        transform: translateY(0);
      }

      .ax-toast--success {
        background: #e8f5e9;
        color: #1b5e20;
      }

      .ax-toast--error {
        background: #ffdad6;         /* error-container */
        color: #93000a;              /* on-error-container */
      }
    `

    // =========================================================================
    // SVG 图标（内联，零外部依赖）
    // =========================================================================

    // Globe icon — Browser 模式
    const SVG_GLOBE = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <ellipse cx="12" cy="12" rx="4" ry="10"/>
        <line x1="2" y1="12" x2="22" y2="12"/>
      </svg>`

    // Description/HTML icon — Raw 模式（跳过抓取，直接解析）
    const SVG_RAW = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
      </svg>`

    // Spinner
    const SVG_SPINNER = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round">
        <path d="M12 2a10 10 0 1 0 10 10" stroke-width="2.5"/>
      </svg>`

    // Check — 成功
    const SVG_CHECK = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
        stroke-linecap="round" stroke-linejoin="round">
        <polyline points="20 6 9 17 4 12"/>
      </svg>`

    // Alert — 错误
    const SVG_ALERT = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>`

    // -- 容器 --
    const panel = document.createElement('div')
    panel.className = 'crawler-panel'

    // -- 按钮 1：Browser 抓取 --
    const btnBrowser = document.createElement('button')
    btnBrowser.className = 'ax-btn ax-btn--primary'
    btnBrowser.title = '将当前页面加入 Browser 抓取队列（后端用 Playwright 打开页面）'
    btnBrowser.innerHTML = `<span class="ax-icon">${SVG_GLOBE}</span> Browser 抓取`

    // -- 按钮 2：HTML 直接解析 --
    const btnRaw = document.createElement('button')
    btnRaw.className = 'ax-btn ax-btn--outline'
    btnRaw.title = '将当前页面 HTML 直接发送解析（跳过抓取，直接走 parser + 图片 + workflow）'
    btnRaw.innerHTML = `<span class="ax-icon">${SVG_RAW}</span> HTML 解析`

    // -- 状态提示 --
    const toast = document.createElement('div')
    toast.className = 'ax-toast'

    // -- 组装 DOM --
    panel.appendChild(btnBrowser)
    panel.appendChild(btnRaw)
    panel.appendChild(toast)
    shadow.appendChild(style)
    shadow.appendChild(panel)

    // =========================================================================
    // 交互逻辑
    // =========================================================================

    let toastTimer = null

    /**
     * 显示提示
     */
    function showToast(type, msg) {
      clearTimeout(toastTimer)
      const icon = type === 'success' ? SVG_CHECK : SVG_ALERT
      toast.className = `ax-toast ax-toast--${type} ax-toast--visible`
      toast.innerHTML = `<span class="ax-icon">${icon}</span>${msg}`
      toastTimer = setTimeout(() => {
        toast.classList.remove('ax-toast--visible')
      }, 2500)
    }

    /**
     * 执行入队操作（通用）
     */
    async function handleEnqueue(apiFn, label, btnEl) {
      const originalHTML = btnEl.innerHTML
      btnEl.innerHTML = `<span class="ax-spinner">${SVG_SPINNER}</span> 提交中...`
      btnEl.classList.add('ax-btn--loading')

      try {
        const data = await apiFn()
        showToast('success', `已加入队列 (${label}) — task #${data.queue_id || '?'}`)
      } catch (err) {
        const msg = err.message.includes('fetch')
          ? '无法连接爬虫服务 (localhost:5175)'
          : `入队失败: ${err.message}`
        showToast('error', msg)
      } finally {
        btnEl.innerHTML = originalHTML
        btnEl.classList.remove('ax-btn--loading')
      }
    }

    btnBrowser.addEventListener('click', () => handleEnqueue(enqueueBrowser, 'browser', btnBrowser))
    btnRaw.addEventListener('click', () => handleEnqueue(enqueueHtml, 'raw', btnRaw))
  }

  // =========================================================================
  // 入口
  // =========================================================================

  // 延迟注入，避免阻塞页面初始渲染
  function inject() {
    if (document.getElementById('__crawler_58_ext__')) return

    const container = document.createElement('div')
    container.id = '__crawler_58_ext__'
    const shadow = container.attachShadow({ mode: 'closed' })
    document.body.appendChild(container)
    buildUI(shadow)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject)
  } else {
    inject()
  }
})()
