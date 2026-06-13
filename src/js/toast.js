/**
 * MooOS Toast Notification System
 * Usage: showToast('message', 'success|error|info|warning')
 */
(function () {
  // Create container once
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;display:flex;flex-direction:column;gap:10px;pointer-events:none;';
    document.body.appendChild(container);
  }

  const icons = {
    success: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
    error: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    info: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
    warning: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
  };

  const colors = {
    success: { bg: '#ecfdf5', border: '#a7f3d0', text: '#065f46', icon: '#059669' },
    error: { bg: '#fef2f2', border: '#fecaca', text: '#991b1b', icon: '#dc2626' },
    info: { bg: '#eff6ff', border: '#bfdbfe', text: '#1e40af', icon: '#3b82f6' },
    warning: { bg: '#fffbeb', border: '#fde68a', text: '#92400e', icon: '#f59e0b' },
  };

  window.showToast = function (message, type = 'info', duration = 3500) {
    const c = colors[type] || colors.info;
    const toast = document.createElement('div');
    toast.style.cssText = `
      display:flex;align-items:center;gap:10px;padding:12px 18px;
      background:${c.bg};border:1px solid ${c.border};color:${c.text};
      border-radius:12px;font-size:14px;font-weight:500;
      box-shadow:0 4px 20px rgba(0,0,0,0.08);
      pointer-events:auto;min-width:280px;max-width:420px;
      transform:translateX(120%);transition:transform .35s cubic-bezier(.4,0,.2,1),opacity .3s;
      font-family:Inter,system-ui,sans-serif;line-height:1.4;
    `;
    const iconSpan = document.createElement('span');
    iconSpan.style.cssText = `color:${c.icon};display:flex;align-items:center;flex-shrink:0;`;
    iconSpan.innerHTML = icons[type] || icons.info;
    toast.appendChild(iconSpan);
    toast.appendChild(document.createTextNode(message));

    container.appendChild(toast);
    requestAnimationFrame(() => { toast.style.transform = 'translateX(0)'; });

    setTimeout(() => {
      toast.style.transform = 'translateX(120%)';
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 400);
    }, duration);
  };
})();
