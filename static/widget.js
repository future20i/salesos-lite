/**
 * SalesOS Lite Web Chat Widget
 * 
 * Embed on any website:
 *   <script src="http://198.199.123.43:8001/widget.js" data-tenant="YOUR_TENANT_ID"></script>
 * 
 * Places a chat bubble in the bottom-right corner. Visitors can send messages
 * directly into your SalesOS Lite inbox.
 */
(function () {
  var script = document.currentScript;
  var tenantId = script.getAttribute('data-tenant');
  var baseUrl = script.src.replace(/\/widget\.js.*/, '');

  if (!tenantId) {
    console.warn('[SalesOS Widget] Missing data-tenant attribute');
    return;
  }

  // ── Styles ──────────────────────────────────────────────
  var style = document.createElement('style');
  style.textContent = [
    '#sls-widget *{box-sizing:border-box;margin:0;padding:0}',
    '#sls-widget{position:fixed;bottom:24px;right:24px;z-index:2147483647;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:14px}',
    '#sls-bubble{width:56px;height:56px;border-radius:50%;background:#6c5ce7;color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 16px rgba(108,92,231,0.4);transition:all 0.2s cubic-bezier(0.16,1,0.3,1);position:relative}',
    '#sls-bubble:hover{transform:scale(1.08);box-shadow:0 6px 20px rgba(108,92,231,0.5)}',
    '#sls-bubble:active{transform:scale(0.95)}',
    '#sls-bubble svg{width:24px;height:24px}',
    '#sls-chat{display:none;position:absolute;bottom:72px;right:0;width:360px;height:520px;max-height:calc(100vh - 120px);background:#fff;border-radius:16px;box-shadow:0 0 0 1px rgba(0,0,0,0.06),0 8px 40px rgba(0,0,0,0.12);overflow:hidden;flex-direction:column}',
    '#sls-chat.open{display:flex}',
    '#sls-header{padding:16px 20px;background:#6c5ce7;color:#fff;display:flex;align-items:center;gap:10px;flex-shrink:0}',
    '#sls-header-avatar{width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-weight:600;font-size:14px}',
    '#sls-header-text{flex:1}',
    '#sls-header-name{font-weight:600;font-size:14px;line-height:1.3}',
    '#sls-header-status{font-size:11px;opacity:0.8}',
    '#sls-close{background:none;border:none;color:#fff;cursor:pointer;opacity:0.8;padding:4px;font-size:20px;line-height:1}',
    '#sls-close:hover{opacity:1}',
    '#sls-messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px;background:#fafafa}',
    '#sls-messages::-webkit-scrollbar{width:4px}',
    '#sls-messages::-webkit-scrollbar-thumb{background:rgba(0,0,0,0.1);border-radius:2px}',
    '#sls-messages .sls-msg{max-width:85%;padding:10px 14px;border-radius:14px;font-size:13px;line-height:1.5;word-break:break-word}',
    '#sls-messages .sls-msg.system{max-width:100%;background:none;color:#999;font-size:11px;text-align:center;padding:4px}',
    '#sls-messages .sls-msg.in{background:#fff;color:#333;align-self:flex-start;border-bottom-left-radius:4px;box-shadow:0 0 0 1px rgba(0,0,0,0.04)}',
    '#sls-messages .sls-msg.out{background:#6c5ce7;color:#fff;align-self:flex-end;border-bottom-right-radius:4px}',
    '#sls-messages .sls-time{font-size:10px;opacity:0.6;margin-top:2px;text-align:right}',
    '#sls-input-row{display:flex;gap:8px;padding:12px 16px;border-top:1px solid rgba(0,0,0,0.06);background:#fff;flex-shrink:0}',
    '#sls-input{flex:1;padding:10px 14px;border:none;border-radius:20px;background:#f5f5f5;font-size:13px;font-family:inherit;outline:none;transition:all 0.15s}',
    '#sls-input:focus{background:#fff;box-shadow:0 0 0 2px rgba(108,92,231,0.3)}',
    '#sls-send{width:36px;height:36px;border-radius:50%;background:#6c5ce7;color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all 0.15s}',
    '#sls-send:hover{background:#5a4bd1}',
    '#sls-send:active{transform:scale(0.92)}',
    '#sls-send svg{width:16px;height:16px}',
    '#sls-unread{position:absolute;top:-4px;right:-4px;background:#ef4444;color:#fff;font-size:10px;font-weight:600;min-width:18px;height:18px;border-radius:9px;display:none;align-items:center;justify-content:center;padding:0 5px}',
    '#sls-brand{text-align:center;padding:4px;font-size:10px;color:#ccc}',
    '#sls-brand a{color:#ccc;text-decoration:none}',
    '#sls-brand a:hover{color:#999}',
    '@media (max-width:420px){#sls-chat{width:calc(100vw - 32px);height:calc(100vh - 120px);right:-8px;bottom:68px}}'
  ].join('\n');
  document.head.appendChild(style);

  // ── HTML ────────────────────────────────────────────────
  var container = document.createElement('div');
  container.id = 'sls-widget';
  container.innerHTML = [
    '<button id="sls-bubble" onclick="window.__sls_toggle()">',
    '  <svg id="sls-bubble-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    '  <span id="sls-unread"></span>',
    '</button>',
    '<div id="sls-chat">',
    '  <div id="sls-header">',
    '    <div id="sls-header-avatar">💬</div>',
    '    <div id="sls-header-text">',
    '      <div id="sls-header-name">在线客服</div>',
    '      <div id="sls-header-status">我们通常几分钟内回复</div>',
    '    </div>',
    '    <button id="sls-close" onclick="window.__sls_toggle()">✕</button>',
    '  </div>',
    '  <div id="sls-messages">',
    '    <div class="sls-msg system">👋 你好！有什么可以帮助你的？</div>',
    '  </div>',
    '  <div id="sls-input-row">',
    '    <input id="sls-input" placeholder="输入消息…" autocomplete="off" onkeydown="if(event.key===\'Enter\')window.__sls_send()">',
    '    <button id="sls-send" onclick="window.__sls_send()">',
    '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4 20-7z"/></svg>',
    '    </button>',
    '  </div>',
    '  <div id="sls-brand"><a href="'+baseUrl+'" target="_blank">Powered by SalesOS Lite</a></div>',
    '</div>'
  ].join('\n');
  document.body.appendChild(container);

  // ── State ───────────────────────────────────────────────
  var open = false;
  var sending = false;
  var msgCount = 0;

  window.__sls_toggle = function () {
    open = !open;
    document.getElementById('sls-chat').classList.toggle('open', open);
    if (open) {
      document.getElementById('sls-unread').style.display = 'none';
      document.getElementById('sls-input').focus();
    }
  };

  window.__sls_send = async function () {
    var input = document.getElementById('sls-input');
    var content = input.value.trim();
    if (!content || sending) return;
    sending = true;
    input.value = '';
    input.disabled = true;

    // Show outgoing message
    addMsg(content, 'out');

    try {
      var resp = await fetch(baseUrl + '/api/inbox/incoming', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: 'web',
          customer_name: '网站访客',
          content: content,
          tenant_id: tenantId
        })
      });

      if (!resp.ok) {
        var err = await resp.json();
        addMsg('发送失败: ' + (err.detail || '请稍后重试'), 'system');
      }
    } catch (e) {
      addMsg('发送失败: 网络错误，请检查连接', 'system');
    }

    sending = false;
    input.disabled = false;
    input.focus();
  };

  function addMsg(text, cls) {
    msgCount++;
    var msgs = document.getElementById('sls-messages');
    var div = document.createElement('div');
    div.className = 'sls-msg ' + cls;
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;

    if (!open) {
      var unread = document.getElementById('sls-unread');
      unread.textContent = msgCount;
      unread.style.display = 'flex';
    }
  }
})();
