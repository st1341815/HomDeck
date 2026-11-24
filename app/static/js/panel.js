/* HomDeck 面板：搜索过滤/高亮 + 键盘导航。零依赖、零外链。 */
(function () {
  'use strict';

  const clockEl = document.getElementById('clock');
  const input = document.getElementById('search');
  const countEl = document.getElementById('search-count');
  const noHit = document.getElementById('no-hit');
  const groups = Array.from(document.querySelectorAll('.group'));

  /* 当前查询词：引擎块在 setEngine() 里会立刻调用 applyFilter()，
     所以这个变量必须声明在引擎块之前（否则 TDZ 报错）。 */
  let query = '';

  /* ---------- 搜索范围：本站 / 百度 / 谷歌 ----------
     本站 = 过滤本页面板；百度 / 谷歌 = 回车直接开新标签搜索。
     选择记在 localStorage，下次进来还是上次那个。 */

  const ENGINES = [
    { id: 'local', name: '本站', hint: '过滤本页', placeholder: '搜索本站服务', url: '' },
    { id: 'baidu', name: '百度', hint: '回车搜索', placeholder: '百度搜索…', url: 'https://www.baidu.com/s?wd=' },
    { id: 'google', name: '谷歌', hint: '需能访问', placeholder: '谷歌搜索…', url: 'https://www.google.com/search?q=' }
  ];
  const ENGINE_KEY = 'homedeck.engine';
  const engineBtn = document.getElementById('engine-btn');
  const engineName = document.getElementById('engine-name');
  const engineMenu = document.getElementById('engine-menu');
  let engine = ENGINES[0];

  function renderEngineMenu() {
    if (!engineMenu) return;
    ENGINES.forEach((e) => {
      const li = document.createElement('li');
      li.dataset.id = e.id;
      li.setAttribute('role', 'option');
      li.tabIndex = 0;

      const label = document.createElement('span');
      label.textContent = e.name;
      const right = document.createElement('span');
      right.className = 'engine-hint';
      const tick = document.createElement('span');
      tick.className = 'engine-tick';
      tick.textContent = '✓';
      right.appendChild(tick);
      if (e.hint) right.appendChild(document.createTextNode(' ' + e.hint));
      li.appendChild(label);
      li.appendChild(right);

      li.addEventListener('click', () => {
        setEngine(e.id);
        closeEngineMenu();
        if (input) input.focus();
      });
      li.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          setEngine(e.id);
          closeEngineMenu();
          if (input) input.focus();
        }
      });
      engineMenu.appendChild(li);
    });
  }

  function closeEngineMenu() {
    if (!engineMenu || engineMenu.hidden) return;
    engineMenu.hidden = true;
    if (engineBtn) engineBtn.setAttribute('aria-expanded', 'false');
  }

  function openEngineMenu() {
    if (!engineMenu) return;
    engineMenu.hidden = false;
    if (engineBtn) engineBtn.setAttribute('aria-expanded', 'true');
    const cur = engineMenu.querySelector('li[aria-selected="true"]');
    if (cur) cur.focus();
  }

  function setEngine(id) {
    engine = ENGINES.filter((e) => e.id === id)[0] || ENGINES[0];
    if (engineName) engineName.textContent = engine.name;
    if (input) input.placeholder = engine.placeholder;
    if (engineMenu) {
      Array.prototype.forEach.call(engineMenu.children, (li) => {
        li.setAttribute('aria-selected', String(li.dataset.id === engine.id));
      });
    }
    try { localStorage.setItem(ENGINE_KEY, engine.id); } catch (err) { /* 隐私模式忽略 */ }
    applyFilter();
  }

  function runEngineSearch() {
    if (!input) return;
    const q = (input.value || '').trim();
    if (!q) { input.focus(); return; }
    const target = engine.url ? engine : ENGINES[1];
    window.open(target.url + encodeURIComponent(q), '_blank', 'noopener,noreferrer');
  }

  if (engineBtn) {
    renderEngineMenu();
    engineBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (engineMenu && engineMenu.hidden) openEngineMenu();
      else closeEngineMenu();
    });
    document.addEventListener('click', (e) => {
      if (engineMenu && !engineMenu.hidden && !engineMenu.contains(e.target) && e.target !== engineBtn) {
        closeEngineMenu();
      }
    });
    let saved = '';
    try { saved = localStorage.getItem(ENGINE_KEY) || ''; } catch (err) { saved = ''; }
    setEngine(saved || 'local');
  }

  /* ---------- 搜索过滤 + 高亮 ---------- */

  function paint(node, q) {
    const raw = node.dataset.raw !== undefined ? node.dataset.raw : node.textContent;
    node.dataset.raw = raw;
    if (!q) {
      node.textContent = raw;
      return;
    }
    const idx = raw.toLowerCase().indexOf(q);
    if (idx === -1) {
      node.textContent = raw;
      return;
    }
    node.textContent = '';
    node.appendChild(document.createTextNode(raw.slice(0, idx)));
    const mark = document.createElement('mark');
    mark.textContent = raw.slice(idx, idx + q.length);
    node.appendChild(mark);
    node.appendChild(document.createTextNode(raw.slice(idx + q.length)));
  }

  function applyFilter() {
    // 引擎模式下不做本地过滤：输入框里是要送出去的查询词，不是筛选条件
    const q = engine.url ? '' : query.trim().toLowerCase();
    let total = 0;
    let shown = 0;
    groups.forEach((g) => {
      const cards = Array.from(g.querySelectorAll('.card'));
      let hit = 0;
      cards.forEach((c) => {
        total++;
        const name = c.dataset.name || '';
        const desc = c.dataset.desc || '';
        const ok = !q || (name + ' ' + desc).toLowerCase().indexOf(q) !== -1;
        c.classList.toggle('is-hidden', !ok);
        if (ok) {
          hit++;
          shown++;
        }
        const nameEl = c.querySelector('.card-name');
        if (nameEl) paint(nameEl, q);
      });
      g.classList.toggle('is-hidden', q !== '' && hit === 0);
      const cnt = g.querySelector('.count');
      if (cnt) cnt.textContent = q ? String(hit) : String(cards.length);
    });
    if (countEl) {
      if (engine.url) {
        countEl.hidden = !query.trim();
        countEl.textContent = '⏎ ' + engine.name;
      } else if (q) {
        countEl.hidden = false;
        countEl.textContent = shown + '/' + total;
      } else {
        countEl.hidden = true;
      }
    }
    if (noHit) noHit.hidden = !(q && shown === 0);
  }

  function visibleCards() {
    return Array.from(document.querySelectorAll('.card')).filter(
      (c) => !c.classList.contains('is-hidden')
    );
  }

  /* ---------- 键盘导航 ---------- */

  function columnCount(card) {
    const grid = card ? card.closest('.grid') : document.querySelector('.grid');
    if (!grid) return 1;
    const tpl = getComputedStyle(grid).gridTemplateColumns || '';
    return Math.max(1, tpl.split(' ').filter(Boolean).length);
  }

  function focusCard(card) {
    if (!card) return;
    card.focus();
    card.scrollIntoView({ block: 'nearest' });
  }

  if (input) {
    input.addEventListener('input', () => {
      query = input.value || '';
      applyFilter();
    });

    document.addEventListener('keydown', (e) => {
      const tag = (e.target.tagName || '').toLowerCase();
      const typing = tag === 'input' || tag === 'textarea' || e.target.isContentEditable;

      // / 或 ⌘K / Ctrl+K 聚焦搜索
      if ((e.key === '/' && !typing) || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k')) {
        e.preventDefault();
        input.focus();
        input.select();
        return;
      }

      if (e.key === 'Escape' && document.activeElement === input) {
        if (engineMenu && !engineMenu.hidden) {
          closeEngineMenu();
          return;
        }
        input.value = '';
        query = '';
        applyFilter();
        input.blur();
        return;
      }

      // 搜索框里的键
      if (document.activeElement === input) {
        if (e.key === 'Enter') {
          e.preventDefault();
          // 百度/谷歌模式：回车直接搜；本站模式：Ctrl/⌘+Enter 也算"搜网页"，用百度
          if (engine.url) runEngineSearch();
          else if (e.metaKey || e.ctrlKey) runEngineSearch();
          else {
            const first = visibleCards()[0];
            if (first) focusCard(first);
          }
          return;
        }
        if (e.key === 'ArrowDown' && !engine.url) {
          const first = visibleCards()[0];
          if (first) {
            e.preventDefault();
            focusCard(first);
          }
        }
        return;
      }

      const cur = document.activeElement && document.activeElement.closest
        ? document.activeElement.closest('.card')
        : null;
      if (!cur) return;

      const cards = visibleCards();
      const idx = cards.indexOf(cur);
      if (idx === -1) return;
      const cols = columnCount(cur);
      let next = -1;

      if (e.key === 'ArrowRight') next = idx + 1;
      else if (e.key === 'ArrowLeft') next = idx - 1;
      else if (e.key === 'ArrowDown') next = idx + cols;
      else if (e.key === 'ArrowUp') {
        if (idx - cols < 0) {
          e.preventDefault();
          input.focus();
          input.select();
          return;
        }
        next = idx - cols;
      } else if (e.key === 'Escape') {
        e.preventDefault();
        input.focus();
        return;
      } else {
        return;
      }

      if (next >= 0 && next < cards.length) {
        e.preventDefault();
        focusCard(cards[next]);
      }
    });
  }

  /* ---------- 访问统计埋点 ----------
     卡片是普通 <a href>，跳转交给浏览器；这里只旁听，绝不 preventDefault，
     否则新标签打开、中键、键盘 Enter 全会被破坏。
     sendBeacon 是唯一能在「页面已经在卸载」时稳稳发出去的通道；
     fetch+keepalive 只作老浏览器兜底。 */

  function trackOpen(card) {
    const id = Number(card.dataset.id);
    if (!id) return;
    const payload = JSON.stringify({ id: id });
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon('/api/visit', new Blob([payload], { type: 'application/json' }));
        return;
      }
    } catch (e) {
      /* 落到 fetch */
    }
    fetch('/api/visit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
      keepalive: true
    }).catch(() => {});
  }

  document.addEventListener('click', (e) => {
    const card = e.target && e.target.closest ? e.target.closest('.card') : null;
    if (card) trackOpen(card);
  });

  document.addEventListener('auxclick', (e) => {
    if (e.button !== 1) return; // 只统计中键新标签；右键菜单不算打开
    const card = e.target && e.target.closest ? e.target.closest('.card') : null;
    if (card) trackOpen(card);
  });

  /* ---------- 头部时钟（参考 Sun-Panel 的首页时钟） ---------- */

  let clockTimer = 0;

  function tickClock() {
    if (!clockEl) return;
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const next = pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());
    if (clockEl.textContent !== next) clockEl.textContent = next;
    clockEl.dateTime = now.toISOString();
    clockEl.title = now.toLocaleDateString('zh-CN', {
      year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'
    });
    // 对齐到下一个整秒再跑，而不是死等 1000ms：固定间隔会累积漂移，
    // 表现为偶尔跳一秒或同一秒停两拍。用余数反算延迟，秒数永远踩在整秒边界
    // （标签页在后台被节流后恢复也能立刻对上当前秒）。
    clearTimeout(clockTimer);
    clockTimer = setTimeout(tickClock, 1000 - (Date.now() % 1000));
  }

  tickClock();

  /* ---------- 启动 ---------- */

  applyFilter();

  // 图标加载失败时退回首字母，不显示裂图
  document.querySelectorAll('.card-icon img').forEach((img) => {
    img.addEventListener('error', () => {
      const box = img.parentElement;
      const card = img.closest('.card');
      const initial = (card && card.dataset.name ? card.dataset.name.trim().slice(0, 1) : '?').toUpperCase();
      box.classList.add('is-text');
      box.textContent = initial;
    });
  });
})();