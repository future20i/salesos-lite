// ═══════════════════════════════════════════════
// SalesOS Lite — Pipeline Board & Followup Management
// Dependencies: api(), $(id), esc(), fmtTime(), _tk (all from index.html)
// DOM requirements: #pipeline-cols, #opp-detail-panel, #inbox-panel, #pipeline-panel
// ═══════════════════════════════════════════════

// ── Stage-gating helpers ──

function stageCategory(stage) {
  // Group stages into 4 pipeline columns
  var s = (stage || '').toLowerCase();
  if (s.indexOf('validation') >= 0 || s.indexOf('confirmation') >= 0 || s.indexOf('verify') >= 0 || s.indexOf('validate') >= 0) return 'requirement';
  if (s.indexOf('technical') >= 0 || s.indexOf('tech') >= 0) return 'technical';
  if (s.indexOf('quotation') >= 0 || s.indexOf('negotiation') >= 0 || s.indexOf('quote') >= 0 || s.indexOf('negotiate') >= 0 || s.indexOf('pricing') >= 0) return 'quotation';
  if (s.indexOf('contract') >= 0 || s.indexOf('close') >= 0 || s.indexOf('sign') >= 0 || s.indexOf('won') >= 0 || s.indexOf('deal') >= 0) return 'contract';
  // fallback: treat unknown stages as requirement
  return 'requirement';
}

var STAGE_COLUMNS = [
  { key: 'requirement', label: '需求确认', icon: '🔍' },
  { key: 'technical', label: '技术交流', icon: '⚙️' },
  { key: 'quotation', label: '报价/谈判', icon: '💰' },
  { key: 'contract', label: '合同', icon: '📋' }
];

function formatCurrency(val) {
  if (val == null) return '—';
  var n = Number(val);
  if (isNaN(n)) return '—';
  // ¥{value/10000}万
  if (n >= 10000) {
    var wan = (n / 10000).toFixed(1);
    return '¥' + wan + '万';
  }
  return '¥' + n.toLocaleString();
}

function stageBadge(stage) {
  var label = stage || '未知';
  var cat = stageCategory(stage);
  var colors = {
    requirement: 'rgba(59,130,246,0.12);color:#2563eb',
    technical: 'rgba(245,158,11,0.12);color:#d97706',
    quotation: 'rgba(16,185,129,0.12);color:#059669',
    contract: 'rgba(108,92,231,0.12);color:#6c5ce7'
  };
  return '<span style="display:inline-block;padding:2px 8px;border-radius:9999px;font-size:10px;font-weight:500;' +
    (colors[cat] || colors.requirement) + '">' + esc(label) + '</span>';
}

function followupStatusBadge(status) {
  var map = {
    'todo':           { label: '待办', color: 'rgba(163,163,163,0.12);color:#737373' },
    'in_progress':    { label: '进行中', color: 'rgba(245,158,11,0.12);color:#d97706' },
    'pending_review': { label: '待审核', color: 'rgba(59,130,246,0.12);color:#2563eb' },
    'done':           { label: '已完成', color: 'rgba(16,185,129,0.12);color:#059669' }
  };
  var b = map[status] || { label: status || '未知', color: 'rgba(163,163,163,0.12);color:#737373' };
  return '<span style="display:inline-block;padding:1px 6px;border-radius:9999px;font-size:9px;font-weight:500;' +
    b.color + '">' + b.label + '</span>';
}

// ── Globals ──

var _pipelineOpps = [];
var _currentOppId = null;
var _pipelineEventSource = null;
var _currentPipelinePanel = 'inbox'; // 'inbox' | 'pipeline'

// ═══════════════════════════════════════════
// 1. Pipeline Board
// ═══════════════════════════════════════════

async function loadPipeline() {
  var cols = document.getElementById('pipeline-cols');
  if (!cols) {
    console.error('pipeline: #pipeline-cols not found');
    return;
  }
  cols.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;padding:48px;color:var(--text-quaternary, #a3a3a3);font-size:14px">加载中…</div>';

  try {
    var r = await api('/api/opportunities');
    if (!r) return;
    var data = await r.json();
    _pipelineOpps = data.opportunities || data || [];
  } catch (e) {
    console.error('pipeline load error', e);
    cols.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;padding:48px;color:var(--text-quaternary, #a3a3a3);font-size:14px">⚠ 加载失败，请重试</div>';
    return;
  }

  renderPipelineBoard();
}

function renderPipelineBoard() {
  var cols = document.getElementById('pipeline-cols');
  if (!cols) return;

  if (!_pipelineOpps.length) {
    cols.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;padding:48px;color:var(--text-quaternary, #a3a3a3);font-size:14px">📋 暂无商机<br><span style="font-size:11px">从线索创建商机或通过 API 导入</span></div>';
    return;
  }

  // Group by stage category
  var grouped = {};
  STAGE_COLUMNS.forEach(function(c) { grouped[c.key] = []; });

  _pipelineOpps.forEach(function(opp) {
    var cat = stageCategory(opp.stage);
    if (grouped[cat]) {
      grouped[cat].push(opp);
    } else {
      grouped['requirement'].push(opp);
    }
  });

  var html = '';
  STAGE_COLUMNS.forEach(function(col) {
    var opps = grouped[col.key] || [];
    html += '<div style="flex:1;min-width:220px;background:var(--bg-subtle, #f5f5f5);border-radius:var(--radius-lg, 12px);padding:12px;display:flex;flex-direction:column;gap:8px">';
    html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:0 4px 8px;border-bottom:2px solid rgba(0,0,0,0.06)">';
    html += '<span style="font-size:12px;font-weight:600;color:var(--text-secondary, #4d4d4d)">' + col.icon + ' ' + col.label + '</span>';
    html += '<span style="font-size:11px;color:var(--text-quaternary, #a3a3a3);font-weight:500">' + opps.length + '</span>';
    html += '</div>';

    if (!opps.length) {
      html += '<div style="padding:20px 8px;text-align:center;color:var(--text-quaternary, #a3a3a3);font-size:11px">暂无</div>';
    } else {
      opps.forEach(function(opp) {
        var valueText = formatCurrency(opp.value);
        var leadName = opp.lead_customer_name || opp.name || '—';
        var followupDot = opp.followup_count > 0
          ? '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--accent, #6c5ce7);margin-right:3px"></span>' + opp.followup_count
          : '';

        html += '<div class="pipeline-card" onclick="loadOpportunityDetail(\'' + opp.id + '\')" ' +
          'style="background:var(--bg-surface, #fff);border-radius:var(--radius-md, 8px);padding:10px 12px;cursor:pointer;' +
          'box-shadow:0 0 0 1px rgba(0,0,0,0.06);transition:all 150ms cubic-bezier(0.16,1,0.3,1)" ' +
          'onmouseenter="this.style.boxShadow=\'0 0 0 1px rgba(0,0,0,0.06),0 2px 8px rgba(0,0,0,0.06)\'" ' +
          'onmouseleave="this.style.boxShadow=\'0 0 0 1px rgba(0,0,0,0.06)\'">' +
          '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px">' +
          '<div style="font-size:13px;font-weight:500;color:var(--text-primary, #171717);line-height:1.3;word-break:break-word">' + esc(leadName) + '</div>' +
          '<div style="flex-shrink:0;margin-left:8px">' + stageBadge(opp.stage) + '</div>' +
          '</div>' +
          '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px">' +
          '<span style="font-size:12px;font-weight:600;color:var(--accent, #6c5ce7)">' + valueText + '</span>' +
          (followupDot ? '<span style="font-size:11px;color:var(--text-tertiary, #808080);display:flex;align-items:center">' + followupDot + '</span>' : '') +
          '</div>' +
          '</div>';
      });
    }

    html += '</div>';
  });

  cols.innerHTML = html;
}

// ═══════════════════════════════════════════
// 2. Opportunity Detail
// ═══════════════════════════════════════════

async function loadOpportunityDetail(oppId) {
  _currentOppId = oppId;
  var panel = document.getElementById('opp-detail-panel');
  if (!panel) {
    console.error('pipeline: #opp-detail-panel not found');
    return;
  }
  panel.classList.remove('hidden');

  // Show loading
  panel.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;padding:48px;color:var(--text-quaternary, #a3a3a3);font-size:14px">加载商机详情…</div>';

  try {
    var r = await api('/api/opportunities/' + oppId);
    if (!r) return;
    var opp = await r.json();
  } catch (e) {
    console.error('opportunity detail load error', e);
    panel.innerHTML = '<div style="padding:16px;color:var(--text-quaternary, #a3a3a3)">⚠ 加载失败</div>';
    return;
  }

  renderOpportunityDetail(opp);
}

function renderOpportunityDetail(opp) {
  var panel = document.getElementById('opp-detail-panel');
  if (!panel) return;

  // Close button
  var html = '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px">';
  html += '<div>';
  html += '<h3 style="font-size:18px;font-weight:600;color:var(--text-primary, #171717);margin:0 0 4px">' + esc(opp.name || '—') + '</h3>';
  html += '<div style="font-size:12px;color:var(--text-tertiary, #808080);display:flex;gap:12px;align-items:center;flex-wrap:wrap">';
  html += '<span>客户: ' + esc(opp.lead_customer_name || '—') + '</span>';
  html += stageBadge(opp.stage);
  html += '<span>金额: ' + formatCurrency(opp.value) + '</span>';
  if (opp.probability != null) html += '<span>概率: ' + opp.probability + '%</span>';
  if (opp.expected_close_date) html += '<span>预计关单: ' + esc(opp.expected_close_date) + '</span>';
  html += '</div>';
  html += '</div>';
  html += '<button onclick="closeOpportunityDetail()" style="background:none;border:none;font-size:20px;cursor:pointer;color:var(--text-tertiary, #808080);padding:4px 8px;border-radius:6px;line-height:1" ' +
    'onmouseenter="this.style.background=\'rgba(0,0,0,0.03)\'" onmouseleave="this.style.background=\'none\'">×</button>';
  html += '</div>';

  // ── Followups ──
  var followups = opp.followups || [];
  var fuColumns = [
    { key: 'todo', label: '待办', icon: '📌' },
    { key: 'in_progress', label: '进行中', icon: '🔄' },
    { key: 'pending_review', label: '待审核', icon: '👁' },
    { key: 'done', label: '已完成', icon: '✅' }
  ];

  var fuGrouped = {};
  fuColumns.forEach(function(c) { fuGrouped[c.key] = []; });
  followups.forEach(function(fu) {
    var s = fu.status || 'todo';
    if (fuGrouped[s]) {
      fuGrouped[s].push(fu);
    } else {
      fuGrouped['todo'].push(fu);
    }
  });

  html += '<div style="display:flex;gap:12px;overflow-x:auto;padding-bottom:8px">';

  fuColumns.forEach(function(col) {
    var items = fuGrouped[col.key] || [];
    html += '<div style="flex:1;min-width:200px;background:var(--bg-subtle, #f5f5f5);border-radius:var(--radius-md, 8px);padding:10px;display:flex;flex-direction:column;gap:6px">';
    html += '<div style="font-size:11px;font-weight:600;color:var(--text-tertiary, #808080);padding:0 4px 6px;border-bottom:1px solid rgba(0,0,0,0.05)">' +
      col.icon + ' ' + col.label + ' (' + items.length + ')</div>';

    if (!items.length) {
      html += '<div style="padding:16px 4px;text-align:center;color:var(--text-quaternary, #a3a3a3);font-size:10px">暂无</div>';
    } else {
      items.forEach(function(fu) {
        html += renderFollowupCard(fu);
      });
    }

    html += '</div>';
  });

  html += '</div>';
  panel.innerHTML = html;
}

function renderFollowupCard(fu) {
  var sourceLabel = (fu.source === 'manual') ? '手动' : (fu.source === 'ai') ? 'AI' : (fu.source === 'message') ? '消息' : (fu.source || '—');
  var sourceColor = (fu.source === 'ai') ? 'color:#6c5ce7' : 'color:var(--text-tertiary, #808080)';

  var html = '<div style="background:var(--bg-surface, #fff);border-radius:var(--radius-sm, 6px);padding:8px 10px;' +
    'box-shadow:0 0 0 1px rgba(0,0,0,0.04);font-size:12px">';

  // Title row
  html += '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px">';
  html += '<span style="font-weight:500;color:var(--text-primary, #171717);font-size:12px;line-height:1.3;word-break:break-word">' + esc(fu.title || '—') + '</span>';
  html += followupStatusBadge(fu.status);
  html += '</div>';

  // Meta
  html += '<div style="font-size:10px;' + sourceColor + ';margin-bottom:4px">' +
    '来源: ' + sourceLabel;
  if (fu.created_at) {
    html += ' · ' + fmtTime(fu.created_at);
  }
  html += '</div>';

  // AI draft area (if present)
  if (fu.ai_draft) {
    html += '<div style="background:rgba(108,92,231,0.04);border-radius:4px;padding:6px 8px;margin:6px 0;font-size:11px;color:var(--text-secondary, #4d4d4d);line-height:1.4;max-height:80px;overflow-y:auto" ' +
      'id="draft-' + fu.id + '">' + esc(fu.ai_draft) + '</div>';
  } else {
    html += '<div id="draft-' + fu.id + '"></div>';
  }

  // Actions row
  html += '<div style="display:flex;gap:4px;margin-top:6px;flex-wrap:wrap">';

  // Draft button (any status)
  html += '<button onclick="doFollowupDraft(\'' + fu.id + '\')" ' +
    'style="padding:2px 8px;border:1px solid rgba(108,92,231,0.3);background:rgba(108,92,231,0.04);color:#6c5ce7;border-radius:9999px;font-size:10px;cursor:pointer;font-family:inherit;transition:all 150ms" ' +
    'onmouseenter="this.style.background=\'rgba(108,92,231,0.1)\'" onmouseleave="this.style.background=\'rgba(108,92,231,0.04)\'">🤖 AI草稿</button>';

  // Move actions based on status
  if (fu.status === 'todo') {
    html += '<button onclick="doFollowupMove(\'' + fu.id + '\',\'in_progress\')" ' +
      'style="padding:2px 8px;border:1px solid rgba(245,158,11,0.3);background:rgba(245,158,11,0.04);color:#d97706;border-radius:9999px;font-size:10px;cursor:pointer;font-family:inherit;transition:all 150ms" ' +
      'onmouseenter="this.style.background=\'rgba(245,158,11,0.1)\'" onmouseleave="this.style.background=\'rgba(245,158,11,0.04)\'">▶ 开始</button>';
  }

  if (fu.status === 'in_progress') {
    html += '<button onclick="doFollowupMove(\'' + fu.id + '\',\'pending_review\')" ' +
      'style="padding:2px 8px;border:1px solid rgba(59,130,246,0.3);background:rgba(59,130,246,0.04);color:#2563eb;border-radius:9999px;font-size:10px;cursor:pointer;font-family:inherit;transition:all 150ms" ' +
      'onmouseenter="this.style.background=\'rgba(59,130,246,0.1)\'" onmouseleave="this.style.background=\'rgba(59,130,246,0.04)\'">📤 提交审核</button>';
  }

  if (fu.status === 'pending_review') {
    html += '<button onclick="doFollowupReview(\'' + fu.id + '\',\'approve\')" ' +
      'style="padding:2px 8px;border:1px solid rgba(16,185,129,0.3);background:rgba(16,185,129,0.04);color:#059669;border-radius:9999px;font-size:10px;cursor:pointer;font-family:inherit;transition:all 150ms" ' +
      'onmouseenter="this.style.background=\'rgba(16,185,129,0.1)\'" onmouseleave="this.style.background=\'rgba(16,185,129,0.04)\'">✅ 批准</button>';
    html += '<button onclick="doFollowupReview(\'' + fu.id + '\',\'reject\')" ' +
      'style="padding:2px 8px;border:1px solid rgba(239,68,68,0.3);background:rgba(239,68,68,0.04);color:#ef4444;border-radius:9999px;font-size:10px;cursor:pointer;font-family:inherit;transition:all 150ms" ' +
      'onmouseenter="this.style.background=\'rgba(239,68,68,0.1)\'" onmouseleave="this.style.background=\'rgba(239,68,68,0.04)\'">❌ 拒绝</button>';
  }

  if (fu.status === 'done') {
    html += '<button onclick="doFollowupSend(\'' + fu.id + '\')" ' +
      'style="padding:2px 10px;border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:9999px;font-size:10px;cursor:pointer;font-family:inherit;transition:all 150ms" ' +
      'onmouseenter="this.style.background=\'var(--accent-hover)\'" onmouseleave="this.style.background=\'var(--accent)\'">📨 发送</button>';
  }

  html += '</div>';
  html += '</div>';
  return html;
}

function closeOpportunityDetail() {
  var panel = document.getElementById('opp-detail-panel');
  if (panel) panel.classList.add('hidden');
  _currentOppId = null;
}

// ═══════════════════════════════════════════
// 3. AI Draft
// ═══════════════════════════════════════════

async function doFollowupDraft(fuId) {
  var draftEl = document.getElementById('draft-' + fuId);
  if (draftEl) {
    draftEl.innerHTML = '<span style="color:var(--text-quaternary, #a3a3a3);font-size:10px">⏳ 生成草稿中…</span>';
  }

  try {
    var r = await api('/api/followups/' + fuId + '/draft', { method: 'POST' });
    if (!r) return;
    var data = await r.json();
    var draftText = data.draft || '';

    if (draftEl) {
      if (draftText) {
        draftEl.innerHTML = '<div style="background:rgba(108,92,231,0.04);border-radius:4px;padding:6px 8px;font-size:11px;color:var(--text-secondary, #4d4d4d);line-height:1.4;max-height:80px;overflow-y:auto">' + esc(draftText) + '</div>';
      } else {
        draftEl.innerHTML = '<span style="color:var(--text-quaternary, #a3a3a3);font-size:10px">暂无草稿</span>';
      }
    }
  } catch (e) {
    console.error('followup draft error', e);
    if (draftEl) {
      draftEl.innerHTML = '<span style="color:var(--danger, #ef4444);font-size:10px">生成失败</span>';
    }
  }
}

// ═══════════════════════════════════════════
// 4. Move Followup
// ═══════════════════════════════════════════

async function doFollowupMove(fuId, newStatus) {
  try {
    var r = await api('/api/followups/' + fuId + '/move', {
      method: 'POST',
      body: JSON.stringify({ to: newStatus })
    });
    if (!r) return;
    // Refresh the detail view
    if (_currentOppId) {
      await loadOpportunityDetail(_currentOppId);
    }
  } catch (e) {
    console.error('followup move error', e);
  }
}

// ═══════════════════════════════════════════
// 5. Review Followup
// ═══════════════════════════════════════════

async function doFollowupReview(fuId, action) {
  try {
    var r = await api('/api/followups/' + fuId + '/review', {
      method: 'POST',
      body: JSON.stringify({ action: action })
    });
    if (!r) return;
    // Refresh the detail view
    if (_currentOppId) {
      await loadOpportunityDetail(_currentOppId);
    }
  } catch (e) {
    console.error('followup review error', e);
  }
}

async function doFollowupSend(fuId) {
  if (!confirm('确认发送此消息给客户？')) return;
  var btn = event.target;
  var origText = btn.textContent;
  btn.textContent = '⏳';
  btn.disabled = true;
  try {
    var r = await api('/api/followups/' + fuId + '/send', {method: 'POST'});
    var d = await r.json();
    if (d.status === 'sent') {
      btn.textContent = '✅ 已发送';
      // Reload details to refresh UI
      setTimeout(function() { loadOpportunityDetail(_currentOppId); }, 500);
    } else {
      alert('发送失败: ' + (d.detail || '未知错误'));
      btn.textContent = origText;
      btn.disabled = false;
    }
  } catch(e) {
    console.error('send error', e);
    btn.textContent = origText;
    btn.disabled = false;
  }
}

// ═══════════════════════════════════════════
// 6. Create Opportunity from Lead
// ═══════════════════════════════════════════

async function createOppFromLead(leadId) {
  var name = prompt('请输入商机名称:');
  if (!name || !name.trim()) return;

  try {
    var r = await api('/api/opportunities', {
      method: 'POST',
      body: JSON.stringify({ name: name.trim(), lead_id: leadId })
    });
    if (!r) return;
    var opp = await r.json();

    // toast
    var toast = document.createElement('div');
    toast.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:var(--text-primary, #171717);color:#fff;padding:10px 20px;border-radius:9999px;font-size:13px;z-index:200;box-shadow:0 2px 8px rgba(0,0,0,0.15)';
    toast.textContent = '✅ 商机已创建: ' + name.trim();
    document.body.appendChild(toast);
    setTimeout(function() { toast.remove(); }, 2500);

    // Refresh pipeline if visible
    if (_currentPipelinePanel === 'pipeline') {
      await loadPipeline();
    }
  } catch (e) {
    console.error('create opportunity error', e);
    alert('创建商机失败');
  }
}

// ═══════════════════════════════════════════
// 7. Panel Switching
// ═══════════════════════════════════════════

function switchPanel(panelName) {
  _currentPipelinePanel = panelName;

  var inboxPanel = document.getElementById('inbox-panel');
  var pipelinePanel = document.getElementById('pipeline-panel');
  var oppDetailPanel = document.getElementById('opp-detail-panel');

  if (panelName === 'pipeline') {
    if (inboxPanel) inboxPanel.classList.add('hidden');
    if (pipelinePanel) pipelinePanel.classList.remove('hidden');
    loadPipeline();
  } else {
    // 'inbox' or default
    if (pipelinePanel) pipelinePanel.classList.add('hidden');
    if (oppDetailPanel) oppDetailPanel.classList.add('hidden');
    if (inboxPanel) inboxPanel.classList.remove('hidden');
    _currentOppId = null;
  }

  // Update nav active state
  var navIcons = document.querySelectorAll('.nav-icon');
  navIcons.forEach(function(icon) {
    icon.classList.remove('active');
  });
  // Find pipeline nav icon by title attribute
  var pipelineNavIcon = document.querySelector('.nav-icon[title*="Pipeline"], .nav-icon[title*="管道"], .nav-icon[title*="商机"]');
  if (panelName === 'pipeline' && pipelineNavIcon) {
    pipelineNavIcon.classList.add('active');
  } else {
    var inboxNavIcon = document.querySelector('.nav-icon[title*="收件箱"], .nav-icon[title*="Inbox"]');
    if (inboxNavIcon) inboxNavIcon.classList.add('active');
  }

  // Also update mobile nav
  var mnavItems = document.querySelectorAll('.mnav-item');
  mnavItems.forEach(function(item) {
    item.classList.remove('active');
    if (panelName === 'pipeline' && (item.textContent || '').indexOf('管道') >= 0) {
      item.classList.add('active');
    }
    if (panelName === 'inbox' && (item.textContent || '').indexOf('收件箱') >= 0) {
      item.classList.add('active');
    }
  });
}

// ═══════════════════════════════════════════
// 8. SSE Integration — Pipeline Events
// ═══════════════════════════════════════════

function connectPipelineSSE() {
  if (_pipelineEventSource) {
    _pipelineEventSource.close();
  }
  if (typeof _tk === 'undefined' || !_tk) {
    // No token yet — try again after a delay
    setTimeout(function() { connectPipelineSSE(); }, 2000);
    return;
  }

  // Use EventSource with auth — append token as query param since EventSource doesn't support headers
  _pipelineEventSource = new EventSource('/api/events/stream?token=' + encodeURIComponent(_tk));

  _pipelineEventSource.addEventListener('pipeline', function(e) {
    try {
      var data = JSON.parse(e.data);
      // Refresh pipeline if the panel is visible
      if (_currentPipelinePanel === 'pipeline') {
        loadPipeline();
      }
      // If we're viewing a specific opportunity, refresh that too
      if (_currentOppId && data.opportunity_id === _currentOppId) {
        loadOpportunityDetail(_currentOppId);
      }
    } catch (err) {
      // ignore parse errors
    }
  });

  _pipelineEventSource.addEventListener('followup', function(e) {
    try {
      var data = JSON.parse(e.data);
      // Only refresh if viewing the relevant opportunity
      if (_currentOppId && data.opportunity_id === _currentOppId) {
        loadOpportunityDetail(_currentOppId);
      }
      if (_currentPipelinePanel === 'pipeline') {
        loadPipeline();
      }
    } catch (err) {
      // ignore parse errors
    }
  });

  // Also handle the generic 'message' event as a catch-all
  _pipelineEventSource.addEventListener('message', function(e) {
    try {
      var data = JSON.parse(e.data);
      if (data.type === 'opportunity_created' || data.type === 'opportunity_updated' || data.type === 'opportunity_deleted') {
        if (_currentPipelinePanel === 'pipeline') {
          loadPipeline();
        }
      }
      if (data.type === 'followup_created' || data.type === 'followup_updated' || data.type === 'followup_status_changed') {
        if (_currentOppId && data.opportunity_id === _currentOppId) {
          loadOpportunityDetail(_currentOppId);
        }
        if (_currentPipelinePanel === 'pipeline') {
          loadPipeline();
        }
      }
    } catch (err) {
      // ignore parse errors
    }
  });

  _pipelineEventSource.onerror = function() {
    console.error('pipeline SSE error — reconnecting in 5s');
    // Reconnect after 5s on error
    setTimeout(function() { connectPipelineSSE(); }, 5000);
  };
}

// ── Initialize SSE after login ──
// Hook into the existing init flow — the parent agent will call connectPipelineSSE()
// after login, or we can auto-init on script load with a deferred check.

// Auto-connect if _tk is already available (script loaded after login)
if (typeof _tk !== 'undefined' && _tk) {
  connectPipelineSSE();
}

// Also expose for manual connection by parent
// connectPipelineSSE() — callable from parent SPA

// ═══════════════════════════════════════════
// Seed Pipeline — demo data management
// ═══════════════════════════════════════════
async function seedPipeline() {
  var btn = document.getElementById('btn-seed');
  if (!btn) return;
  var orig = btn.textContent;
  btn.textContent = '⏳';
  btn.disabled = true;
  try {
    var r = await api('/api/seed/pipeline', { method: 'POST' });
    var d = await r.json();
    if (d.status === 'already_seeded') {
      if (confirm('演示数据已存在。是否清除后重新生成？')) {
        await clearSeedPipeline();
        // Retry seed
        var r2 = await api('/api/seed/pipeline', { method: 'POST' });
        var d2 = await r2.json();
        btn.textContent = d2.status === 'seeded' ? '✅ 已生成' : '❌ 失败';
        loadPipeline();
      } else {
        btn.textContent = orig;
        btn.disabled = false;
        return;
      }
    } else {
      btn.textContent = '✅ 已生成';
    }
    // Reload pipeline to show the new data
    loadPipeline();
  } catch(e) {
    btn.textContent = '❌ 失败';
    console.error('Seed failed:', e);
  }
  btn.disabled = false;
  setTimeout(function() { btn.textContent = '🎲 演示'; }, 3000);
}

async function clearSeedPipeline() {
  try {
    var r = await api('/api/seed/pipeline', { method: 'DELETE' });
    var d = await r.json();
    loadPipeline();
    return d;
  } catch(e) {
    console.error('Clear seed failed:', e);
  }
}

async function seedPipelineIfEmpty() {
  // Check if any opportunities exist for this tenant
  try {
    var r = await api('/api/opportunities/?limit=1');
    var opps = await r.json();
    if (!Array.isArray(opps) || opps.length === 0) {
      // Auto-seed silently
      await api('/api/seed/pipeline', { method: 'POST' });
      loadPipeline();
    }
  } catch(e) {
    // Silently fail — seed is optional
  }
}

console.log('SalesOS Pipeline JS loaded — functions: loadPipeline, loadOpportunityDetail, doFollowupDraft, doFollowupMove, doFollowupReview, createOppFromLead, switchPanel, connectPipelineSSE');
