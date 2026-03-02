/* ============================================================
   app.js — ArXiv 论文翻译系统前端逻辑
   架构：纯 JS + Fetch API，无依赖框架
   ============================================================ */

'use strict';

const API = 'http://localhost:5000';

// ─── 状态 ────────────────────────────────────────────────────
const state = {
    currentPage: 1,
    pageSize: 15,
    currentStatus: '',       // 当前过滤状态
    totalPages: 1,
    pollingTimer: null,      // 队列轮询定时器
    statsTimer: null,        // 统计轮询定时器
    panelCollapsed: false,
    currentDetailId: null,
};

// ─── 状态映射 ─────────────────────────────────────────────────
const STATUS_MAP = {
    discovered: { label: '已发现', cls: 'discovered', icon: '📄' },
    summarizing: { label: '总结中', cls: 'summarizing', icon: '⏳' },
    summarized: { label: '已总结', cls: 'summarized', icon: '✅' },
    summary_failed: { label: '总结失败', cls: 'failed', icon: '❌' },
    translating: { label: '翻译中', cls: 'translating', icon: '⏳' },
    translated: { label: '已翻译', cls: 'translated', icon: '🌐' },
    translation_failed: { label: '翻译失败', cls: 'failed', icon: '❌' },
};

// "处理中" 过滤器对应的 status 值列表
const PENDING_STATUSES = ['summarizing', 'translating', 'discovered'];
const FAILED_STATUSES = ['summary_failed', 'translation_failed'];

// ─── 工具函数 ─────────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
    const res = await fetch(API + path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ error: '请求失败' }));
        throw new Error(err.error || '请求失败');
    }
    return res.json();
}

function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast toast--${type}`;
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    el.textContent = (icons[type] || '') + ' ' + msg;
    document.getElementById('toast-container').appendChild(el);
    setTimeout(() => el.remove(), 3500);
}

function formatDate(iso) {
    if (!iso) return '—';
    return iso.slice(0, 10);
}

function truncate(str, maxLen) {
    if (!str) return '';
    return str.length > maxLen ? str.slice(0, maxLen) + '…' : str;
}

// ─── 页面切换 ─────────────────────────────────────────────────
function showPage(id) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(id).classList.add('active');
}

// ─── 统计卡片 ─────────────────────────────────────────────────
async function loadStats() {
    try {
        const data = await apiFetch('/api/stats');
        // data 可能是 { discovered, summarized, translated, failed, total, ... }
        document.getElementById('stat-num-discovered').textContent =
            (data.discovered ?? data.total ?? '—');
        document.getElementById('stat-num-summarized').textContent =
            (data.summarized ?? '—');
        document.getElementById('stat-num-translated').textContent =
            (data.translated ?? '—');
        document.getElementById('stat-num-failed').textContent =
            (data.failed ?? '—');

        // 隐藏错误态
        document.getElementById('error-state').classList.add('hidden');
    } catch (e) {
        document.getElementById('error-state').classList.remove('hidden');
        document.getElementById('paper-list').innerHTML = '';
        document.getElementById('empty-state').classList.add('hidden');
    }
}

// ─── 论文列表 ─────────────────────────────────────────────────
async function loadPapers(page = 1) {
    state.currentPage = page;
    const params = new URLSearchParams({
        page,
        page_size: state.pageSize,
    });

    // "处理中" 和 "失败" 是前端聚合过滤，不能直接传单个 status
    // 只有单个 status 才直接传参
    const passToBackend = ['translated', 'summarized'];
    if (state.currentStatus && passToBackend.includes(state.currentStatus)) {
        params.set('status', state.currentStatus);
    }

    try {
        const data = await apiFetch(`/api/papers?${params}`);
        let papers = data.papers || [];

        // 前端二次过滤
        if (state.currentStatus === 'pending') {
            papers = papers.filter(p => PENDING_STATUSES.includes(p.status));
        } else if (state.currentStatus === 'failed') {
            papers = papers.filter(p => FAILED_STATUSES.includes(p.status));
        }

        state.totalPages = data.pages || 1;
        renderPaperList(papers, data.total);
        renderPagination(data.total);
        document.getElementById('error-state').classList.add('hidden');
    } catch (e) {
        document.getElementById('error-state').classList.remove('hidden');
        document.getElementById('paper-list').innerHTML = '';
    }
}

function renderPaperList(papers, total) {
    const list = document.getElementById('paper-list');
    const emptyState = document.getElementById('empty-state');

    if (!papers.length) {
        list.innerHTML = '';
        emptyState.classList.remove('hidden');
        return;
    }
    emptyState.classList.add('hidden');

    list.innerHTML = papers.map(p => paperCardHTML(p)).join('');

    // 绑定按钮事件
    list.querySelectorAll('[data-view]').forEach(btn => {
        btn.addEventListener('click', () => openDetail(btn.dataset.view));
    });
    list.querySelectorAll('[data-retry]').forEach(btn => {
        btn.addEventListener('click', () => retryPaper(btn.dataset.retry));
    });
}

function paperCardHTML(p) {
    const st = STATUS_MAP[p.status] || { label: p.status, cls: 'discovered', icon: '📄' };
    const isPending = PENDING_STATUSES.includes(p.status);
    const isFailed = FAILED_STATUSES.includes(p.status);
    const isTranslated = p.status === 'translated';
    const isSummarized = p.status === 'summarized' || isTranslated;

    const dotHTML = isPending ? '<span class="badge-dot"></span>' : '';

    // 摘要 / 错误 / 处理中提示
    let summaryHTML = '';
    if (p.summary_zh && isSummarized) {
        summaryHTML = `<p class="paper-summary"><span class="paper-summary-icon">💬</span>${p.summary_zh}</p>`;
    } else if (isPending) {
        summaryHTML = `<p class="paper-summary" style="color:var(--amber)">⏳ ${st.label}中，请稍候…</p>`;
    } else if (isFailed) {
        const errMsg = p.summary_error || p.translation_error || '未知错误';
        summaryHTML = `<p class="paper-error">⚠️ ${errMsg}</p>`;
    }

    // 作者
    const authors = Array.isArray(p.authors) ? p.authors.join(', ') : (p.authors || '');

    // 操作按钮
    let actionsHTML = '';
    if (isTranslated) {
        actionsHTML += `<button class="btn btn-sm btn-primary" data-view="${p.arxiv_id}">查看详情</button>`;
    } else if (isSummarized) {
        actionsHTML += `<button class="btn btn-sm" data-view="${p.arxiv_id}">查看详情</button>`;
    }
    if (isFailed) {
        actionsHTML += `<button class="btn btn-sm btn-danger" data-retry="${p.arxiv_id}">🔄 重试</button>`;
    }

    return `
  <div class="paper-card" id="card-${p.arxiv_id}">
    <div class="paper-status-col">
      <span class="status-badge status-badge--${st.cls}">
        ${dotHTML}${st.icon} ${st.label}
      </span>
    </div>
    <div class="paper-content-col">
      <div class="paper-title">${escapeHTML(p.title || p.arxiv_id)}</div>
      ${authors ? `<div class="paper-authors">${escapeHTML(truncate(authors, 80))}</div>` : ''}
      ${summaryHTML}
    </div>
    <div class="paper-actions-col">
      <div class="paper-date">${formatDate(p.published_at || p.discovered_at)}</div>
      <div class="paper-actions">${actionsHTML}</div>
    </div>
  </div>`;
}

function escapeHTML(str) {
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(str || ''));
    return d.innerHTML;
}

// ─── 分页 ─────────────────────────────────────────────────────
function renderPagination(total) {
    const pg = document.getElementById('pagination');
    const pages = Math.ceil(total / state.pageSize);
    state.totalPages = pages;

    if (pages <= 1) { pg.innerHTML = ''; return; }

    const cur = state.currentPage;
    let html = '';

    html += `<button class="page-btn" ${cur === 1 ? 'disabled' : ''} onclick="loadPapers(${cur - 1})">‹</button>`;

    // 显示最多 7 个页码
    let start = Math.max(1, cur - 3);
    let end = Math.min(pages, start + 6);
    start = Math.max(1, end - 6);

    if (start > 1) html += `<button class="page-btn" onclick="loadPapers(1)">1</button>${start > 2 ? '<span style="color:var(--text-muted);padding:0 4px">…</span>' : ''}`;

    for (let i = start; i <= end; i++) {
        html += `<button class="page-btn ${i === cur ? 'active' : ''}" onclick="loadPapers(${i})">${i}</button>`;
    }

    if (end < pages) html += `${end < pages - 1 ? '<span style="color:var(--text-muted);padding:0 4px">…</span>' : ''}<button class="page-btn" onclick="loadPapers(${pages})">${pages}</button>`;

    html += `<button class="page-btn" ${cur === pages ? 'disabled' : ''} onclick="loadPapers(${cur + 1})">›</button>`;
    pg.innerHTML = html;
}

// ─── 过滤标签 ─────────────────────────────────────────────────
document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.currentStatus = btn.dataset.status;
        loadPapers(1);
    });
});

// ─── 详情页 ───────────────────────────────────────────────────
async function openDetail(arxivId) {
    state.currentDetailId = arxivId;
    showPage('page-detail');

    const metaEl = document.getElementById('detail-meta');
    const actionsEl = document.getElementById('detail-actions');
    const iframeEl = document.getElementById('pdf-iframe');
    const wrapEl = document.getElementById('pdf-viewer-wrap');
    const phEl = document.getElementById('pdf-placeholder');

    metaEl.innerHTML = '<p style="color:var(--text-muted)">加载中…</p>';
    actionsEl.innerHTML = '';
    iframeEl.src = '';
    wrapEl.classList.add('hidden');
    phEl.classList.add('hidden');
    phEl.innerHTML = '';

    try {
        const p = await apiFetch(`/api/papers/${arxivId}`);
        const st = STATUS_MAP[p.status] || { label: p.status, icon: '📄' };
        const authors = Array.isArray(p.authors) ? p.authors.join(', ') : (p.authors || '');

        metaEl.innerHTML = `
      <div class="detail-title">${escapeHTML(p.title || arxivId)}</div>
      <div class="detail-sub">
        <span>arXiv: <a href="${p.arxiv_url || `https://arxiv.org/abs/${arxivId}`}" target="_blank" style="color:var(--accent)">${arxivId}</a></span>
        ${p.published_at ? `<span>📅 ${formatDate(p.published_at)}</span>` : ''}
        <span>${st.icon} ${st.label}</span>
      </div>
      ${authors ? `<div style="font-size:12px;color:var(--text-muted);margin-top:2px">${escapeHTML(truncate(authors, 100))}</div>` : ''}
    `;

        // 下载按钮
        let actHtml = '';
        if (p.original_pdf_path) actHtml += `<a class="btn btn-sm" href="${API}/api/files/by-arxiv/${arxivId}/original" target="_blank" download>⬇ 原文 PDF</a>`;
        if (p.translated_pdf_path) actHtml += `<a class="btn btn-sm" href="${API}/api/files/by-arxiv/${arxivId}/translated" target="_blank" download>⬇ 译文 PDF</a>`;
        actionsEl.innerHTML = actHtml;

        // PDF 显示
        if (p.status === 'translated' && p.comparison_pdf_path) {
            iframeEl.src = `${API}/api/files/by-arxiv/${arxivId}/comparison`;
            wrapEl.classList.remove('hidden');
        } else {
            phEl.classList.remove('hidden');
            const summaryBlock = p.summary_zh
                ? `<div class="summary-box">${escapeHTML(p.summary_zh)}</div>`
                : '';
            phEl.innerHTML = `
        <div class="pdf-placeholder-icon">📄</div>
        <h3>翻译尚未完成</h3>
        <p>当前状态：${st.icon} ${st.label}${p.translation_error ? `<br><span style="color:var(--red)">${escapeHTML(p.translation_error)}</span>` : ''}</p>
        ${summaryBlock}
        ${FAILED_STATUSES.includes(p.status) ? `<button class="btn btn-danger" onclick="retryPaper('${arxivId}')">🔄 重新翻译</button>` : ''}
      `;
        }
    } catch (e) {
        metaEl.innerHTML = `<p style="color:var(--red)">加载失败: ${e.message}</p>`;
    }
}

document.getElementById('btn-back').addEventListener('click', () => {
    showPage('page-list');
    state.currentDetailId = null;
    loadPapers(state.currentPage);
});

// ─── 重试 ─────────────────────────────────────────────────────
async function retryPaper(arxivId) {
    try {
        const data = await apiFetch(`/api/papers/${arxivId}/retry`, { method: 'POST' });
        toast(data.message || '已加入重试队列', 'success');
        // 刷新列表
        loadPapers(state.currentPage);
        loadStats();
        ensurePolling();
    } catch (e) {
        toast(`重试失败: ${e.message}`, 'error');
    }
}

// ─── 搜索弹窗 ─────────────────────────────────────────────────
const searchOverlay = document.getElementById('search-modal-overlay');

function openSearchModal() {
    searchOverlay.classList.remove('hidden');
    loadSearchHistory();
    document.getElementById('input-query').focus();
}
function closeSearchModal() {
    searchOverlay.classList.add('hidden');
}

document.getElementById('btn-search-panel').addEventListener('click', openSearchModal);
document.getElementById('btn-close-search').addEventListener('click', closeSearchModal);
document.getElementById('btn-cancel-search').addEventListener('click', closeSearchModal);
searchOverlay.addEventListener('click', e => { if (e.target === searchOverlay) closeSearchModal(); });

// 加载搜索历史
async function loadSearchHistory() {
    try {
        const records = await apiFetch('/api/searches?limit=6');
        const row = document.getElementById('search-history-row');
        const chips = document.getElementById('search-history-chips');
        if (!records.length) { row.classList.add('hidden'); return; }
        row.classList.remove('hidden');
        chips.innerHTML = records.map(r => `
      <span class="history-chip" title="${escapeHTML(r.query)}" data-query="${escapeHTML(r.query)}" data-keyword="${escapeHTML(r.keyword)}" data-days="${r.days}" data-max="${r.max_results}">
        ${escapeHTML(truncate(r.query, 25))}
      </span>`).join('');
        chips.querySelectorAll('.history-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                document.getElementById('input-query').value = chip.dataset.query;
                document.getElementById('input-keyword').value = chip.dataset.keyword;
                document.getElementById('input-days').value = chip.dataset.days;
                document.getElementById('input-max').value = chip.dataset.max;
            });
        });
    } catch (_) { }
}

// 提交搜索
document.getElementById('btn-submit-search').addEventListener('click', async () => {
    const query = document.getElementById('input-query').value.trim();
    const keyword = document.getElementById('input-keyword').value.trim();
    const days = parseInt(document.getElementById('input-days').value) || 30;
    const max = parseInt(document.getElementById('input-max').value) || 10;

    if (!query) {
        toast('请填写搜索词', 'error');
        document.getElementById('input-query').focus();
        return;
    }

    const submitBtn = document.getElementById('btn-submit-search');
    submitBtn.disabled = true;
    submitBtn.textContent = '⏳ 搜索中…';

    try {
        const data = await apiFetch('/api/search', {
            method: 'POST',
            body: JSON.stringify({ query, keyword, days, max }),
        });
        toast(`搜索已触发，正在后台爬取论文…`, 'success');
        closeSearchModal();
        // 稍等后刷新列表 + 开始轮询队列
        setTimeout(() => {
            loadPapers(1);
            loadStats();
            ensurePolling();
        }, 1500);
    } catch (e) {
        toast(`搜索失败: ${e.message}`, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '🚀 开始搜索';
    }
});

// Enter 快捷提交
document.getElementById('input-query').addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('btn-submit-search').click();
});

// ─── 队列轮询 & 进度面板 ──────────────────────────────────────
const progressPanel = document.getElementById('progress-panel');

async function pollQueue() {
    try {
        const s = await apiFetch('/api/queue/status');

        if (s.is_idle) {
            progressPanel.classList.add('hidden');
            clearInterval(state.pollingTimer);
            state.pollingTimer = null;
            // 最后刷新一次
            loadPapers(state.currentPage);
            loadStats();
            return;
        }

        progressPanel.classList.remove('hidden');

        const frac = `${s.done ?? 0} / ${s.total ?? 0}`;
        document.getElementById('progress-fraction').textContent = frac;
        document.getElementById('progress-bar-fill').style.width = (s.percent || 0) + '%';

        const cur = s.current;
        if (cur) {
            const taskLabel = cur.task_type === 'summarize' ? '总结' : '翻译';
            document.getElementById('progress-current').textContent =
                `▶ ${taskLabel}：${truncate(cur.title || cur.arxiv_id, 28)}`;
        } else {
            document.getElementById('progress-current').textContent = '等待任务…';
        }

        const pendingEl = document.getElementById('progress-pending');
        if (s.pending_papers && s.pending_papers.length) {
            pendingEl.innerHTML = s.pending_papers.slice(0, 3).map(t =>
                `<span>· ${escapeHTML(truncate(t, 30))}</span>`).join('');
        } else {
            pendingEl.innerHTML = '';
        }

        // 刷新列表（轻量）
        loadPapers(state.currentPage);
        loadStats();
    } catch (_) { }
}

function ensurePolling() {
    if (state.pollingTimer) return;
    state.pollingTimer = setInterval(pollQueue, 3000);
    pollQueue(); // 立即执行一次
}

// 进度面板折叠
document.getElementById('btn-toggle-panel').addEventListener('click', () => {
    state.panelCollapsed = !state.panelCollapsed;
    const body = document.getElementById('progress-panel-body');
    body.style.display = state.panelCollapsed ? 'none' : '';
    document.getElementById('btn-toggle-panel').textContent = state.panelCollapsed ? '+' : '−';
});

// ─── 日志页 ───────────────────────────────────────────────────
async function loadLogs() {
    const el = document.getElementById('log-content');
    el.textContent = '加载中…';
    try {
        // 尝试通过文件服务读取日志（注意：日志不是 PDF，需要后端支持）
        // 或直接读取 /api/queue/worker 等简易状态
        const w = await apiFetch('/api/queue/worker');
        const q = await apiFetch('/api/queue/status');
        el.textContent = [
            `=== 系统状态 ===`,
            `后台 Worker 运行中: ${w.running}`,
            ``,
            `=== 任务队列 ===`,
            `总计: ${q.total}  已完成: ${q.done}  运行中: ${q.running}  等待: ${q.pending}`,
            `进度: ${q.percent ?? 0}%  空闲: ${q.is_idle}`,
            ``,
            `当前任务: ${q.current ? JSON.stringify(q.current, null, 2) : '无'}`,
            ``,
            `待处理论文:`,
            ...(q.pending_papers || []).map(t => `  - ${t}`),
        ].join('\n');
    } catch (e) {
        el.textContent = `无法获取日志: ${e.message}\n\n请查看系统终端查看详细日志（arxiv_translator.log）`;
    }
}

document.getElementById('btn-logs').addEventListener('click', () => {
    showPage('page-logs');
    loadLogs();
});
document.getElementById('btn-back-logs').addEventListener('click', () => showPage('page-list'));
document.getElementById('btn-refresh-logs').addEventListener('click', loadLogs);

// ─── 初始化 ───────────────────────────────────────────────────
async function init() {
    await loadStats();
    await loadPapers(1);

    // 检查是否有进行中的任务，若有则开始轮询
    try {
        const q = await apiFetch('/api/queue/status');
        if (!q.is_idle) ensurePolling();
    } catch (_) { }

    // 每60秒刷新一下统计（低频保活）
    state.statsTimer = setInterval(() => {
        if (document.getElementById('page-list').classList.contains('active')) {
            loadStats();
        }
    }, 60000);
}

init();
