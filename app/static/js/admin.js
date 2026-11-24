/* HomDeck 管理台：原生 JS，无框架、无外链。 */
(function () {
  'use strict';

  const state = { groups: [], items: [], icons: [], settings: {}, selected: null };

  /* ---------- 基础工具 ---------- */

  function csrf() {
    const hit = document.cookie.split('; ').find((c) => c.startsWith('hd_csrf='));
    return hit ? decodeURIComponent(hit.slice(8)) : '';
  }

  async function api(method, url, body) {
    const opt = { method, headers: { 'X-CSRF-Token': csrf() } };
    if (body instanceof FormData) {
      opt.body = body;
    } else if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    const res = await fetch(url, opt);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || data.detail || '请求失败(' + res.status + ')');
    return data;
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function iconNode(icon) {
    const span = el('span', 'ii');
    if (icon && icon.startsWith('/')) {
      const img = el('img');
      img.src = icon;
      img.alt = '';
      span.appendChild(img);
    } else {
      span.textContent = icon || '🔗';
    }
    return span;
  }

  /* ---------- 加载 ---------- */

  async function load() {
    const data = await api('GET', '/api/admin/overview');
    state.groups = data.groups;
    state.items = data.items;
    state.icons = data.icons;
    state.settings = data.settings;
    if (state.selected === null && state.groups.length) state.selected = state.groups[0].id;
    renderGroups();
    renderItems();
    renderIcons();
    fillSettings();
    renderAudit(data.audit);
  }

  /* ---------- 分组 ---------- */

  function renderGroups() {
    const ul = document.getElementById('group-list');
    ul.innerHTML = '';
    const counts = {};
    state.items.forEach((it) => {
      counts[it.group_id] = (counts[it.group_id] || 0) + 1;
    });
    state.groups.forEach((g, idx) => {
      const li = el('li');
      li.draggable = true;
      li.dataset.gid = String(g.id);
      li.dataset.idx = String(idx);
      if (g.id === state.selected) li.classList.add('active');
      li.appendChild(el('span', 'gdrag', '⠿'));
      li.appendChild(el('span', 'gname', (g.icon ? g.icon + ' ' : '') + g.name));
      li.appendChild(el('span', 'gcount', String(counts[g.id] || 0)));
      const ops = el('span', 'gops');
      const up = el('button', 'icon-btn', '↑');
      up.type = 'button';
      up.title = '上移';
      up.addEventListener('click', (e) => { e.stopPropagation(); moveGroup(idx, -1); });
      const down = el('button', 'icon-btn', '↓');
      down.type = 'button';
      down.title = '下移';
      down.addEventListener('click', (e) => { e.stopPropagation(); moveGroup(idx, 1); });
      const ren = el('button', 'icon-btn', '✎');
      ren.type = 'button';
      ren.title = '改名';
      ren.addEventListener('click', (e) => { e.stopPropagation(); renameGroup(g); });
      const del = el('button', 'icon-btn', '✕');
      del.type = 'button';
      del.title = '删除';
      del.addEventListener('click', (e) => { e.stopPropagation(); removeGroup(g); });
      [up, down, ren, del].forEach((b) => ops.appendChild(b));
      li.appendChild(ops);
      li.addEventListener('click', () => { state.selected = g.id; renderGroups(); renderItems(); });
      ul.appendChild(li);
    });
    if (!state.groups.length) ul.appendChild(el('li', 'dim', '还没有分组'));
  }

  async function moveGroup(idx, delta) {
    const target = idx + delta;
    if (target < 0 || target >= state.groups.length) return;
    const ids = state.groups.map((g) => g.id);
    [ids[idx], ids[target]] = [ids[target], ids[idx]];
    await api('POST', '/api/admin/groups/reorder', { ids });
    await load();
  }

  async function renameGroup(g) {
    const name = prompt('分组名称', g.name);
    if (name === null || !name.trim()) return;
    const icon = prompt('分组图标（emoji，可留空）', g.icon || '');
    await api('PATCH', '/api/admin/groups/' + g.id, { name: name.trim(), icon: icon || '' });
    await load();
  }

  async function removeGroup(g) {
    if (!confirm('删除分组「' + g.name + '」及其下所有卡片？')) return;
    await api('DELETE', '/api/admin/groups/' + g.id);
    if (state.selected === g.id) state.selected = null;
    await load();
  }

  /* ---------- 卡片 ---------- */

  function groupIds(gid) {
    return state.items.filter((i) => i.group_id === gid).map((i) => i.id);
  }

  async function commitItemOrder(layout) {
    await api('POST', '/api/admin/items/reorder', { layout });
    await load();
  }

  async function moveItem(idx, delta) {
    const gid = state.selected;
    const ids = groupIds(gid);
    const t = idx + delta;
    if (t < 0 || t >= ids.length) return;
    [ids[idx], ids[t]] = [ids[t], ids[idx]];
    await commitItemOrder({ [gid]: ids });
  }

  async function moveItemToGroup(itemId, targetGid) {
    const it = state.items.find((x) => x.id === itemId);
    if (!it || it.group_id === targetGid) return;
    const srcIds = groupIds(it.group_id).filter((id) => id !== itemId);
    const dstIds = groupIds(targetGid).concat([itemId]);
    await commitItemOrder({ [it.group_id]: srcIds, [targetGid]: dstIds });
  }

  function renderItems() {
    const box = document.getElementById('item-list');
    const title = document.getElementById('items-title');
    box.innerHTML = '';
    const g = state.groups.find((x) => x.id === state.selected);
    title.textContent = g ? '卡片 · ' + g.name : '卡片';
    const list = state.items.filter((it) => it.group_id === state.selected);
    if (!list.length) {
      box.appendChild(el('p', 'hint', g ? '这个分组还没有卡片，点右上角新增。' : '先在左侧选一个分组。'));
      return;
    }
    list.forEach((it, idx) => {
      const row = el('div', 'item-row');
      row.draggable = true;
      row.dataset.iid = String(it.id);
      row.dataset.idx = String(idx);
      row.appendChild(el('span', 'gdrag', '⠿'));
      row.appendChild(iconNode(it.icon));
      const meta = el('div', 'meta');
      meta.appendChild(el('div', 'iname', it.name));
      const url = it.url_lan || it.url_wan || '';
      meta.appendChild(el('div', 'iurl', url));
      row.appendChild(meta);
      const ops = el('div', 'ops');
      const up = el('button', 'icon-btn', '↑');
      up.type = 'button';
      up.title = '上移';
      up.addEventListener('click', () => moveItem(idx, -1));
      const down = el('button', 'icon-btn', '↓');
      down.type = 'button';
      down.title = '下移';
      down.addEventListener('click', () => moveItem(idx, 1));
      const edit = el('button', 'icon-btn', '✎');
      edit.type = 'button';
      edit.addEventListener('click', () => openItemDialog(it));
      const del = el('button', 'icon-btn', '✕');
      del.type = 'button';
      del.addEventListener('click', async () => {
        if (!confirm('删除卡片「' + it.name + '」？')) return;
        await api('DELETE', '/api/admin/items/' + it.id);
        await load();
      });
      [up, down, edit, del].forEach((b) => ops.appendChild(b));
      row.appendChild(ops);
      box.appendChild(row);
    });
  }

  /* ---------- 弹窗 ---------- */

  const dlg = document.getElementById('dlg');
  const dlgForm = document.getElementById('dlg-form');
  const dlgBody = document.getElementById('dlg-body');
  const dlgTitle = document.getElementById('dlg-title');
  let editing = null;

  function field(label, name, value, opts) {
    const o = opts || {};
    const wrap = el('label', 'field' + (o.wide ? ' wide' : ''));
    wrap.appendChild(el('span', null, label));
    let input;
    if (o.type === 'select') {
      input = el('select');
      o.options.forEach(([v, t]) => {
        const op = el('option', null, t);
        op.value = v;
        input.appendChild(op);
      });
      input.value = value === undefined || value === null ? '' : String(value);
    } else {
      input = el('input');
      input.type = o.type || 'text';
      input.value = value === undefined || value === null ? '' : value;
      if (o.placeholder) input.placeholder = o.placeholder;
      if (o.maxlength) input.maxLength = o.maxlength;
    }
    input.name = name;
    wrap.appendChild(input);
    if (o.hint) wrap.appendChild(el('span', 'hint', o.hint));
    return wrap;
  }

  function openItemDialog(item) {
    editing = item || null;
    dlgTitle.textContent = item ? '编辑卡片' : '新增卡片';
    dlgBody.innerHTML = '';
    const gOptions = state.groups.map((g) => [String(g.id), g.name]);
    dlgBody.appendChild(field('名称', 'name', item ? item.name : '', { maxlength: 60 }));
    dlgBody.appendChild(field('分组', 'group_id', item ? item.group_id : (state.selected || ''), { type: 'select', options: gOptions }));
    const urlLanField = field('内网地址', 'url_lan', item ? item.url_lan : '', { wide: true, placeholder: 'http://192.168.1.10:8090' });
    dlgBody.appendChild(urlLanField);
    dlgBody.appendChild(field('外网地址', 'url_wan', item ? item.url_wan : '', { wide: true, placeholder: 'https://home.example.com' }));
    /* 图标：可以手填 emoji / /i/xxx.webp，也可以直接"从网址获取"。
       新增卡片时，地址填完停手 900ms 就自动抓一次——这是用户要的一步到位。 */
    const iconField = field('图标（emoji 或 /i/xxx.webp）', 'icon', item ? item.icon : '', { wide: true });
    const iconInput = iconField.querySelector('input');
    dlgBody.appendChild(iconField);

    const iconBar = el('div', 'icon-bar wide');
    const grabBtn = el('button', 'btn mini', '⤓ 从网址获取');
    grabBtn.type = 'button';
    const iconStatus = el('span', 'hint icon-status', '');
    const iconPreview = el('img', 'icon-preview');
    iconPreview.alt = '';
    iconPreview.hidden = true;
    iconBar.appendChild(grabBtn);
    iconBar.appendChild(iconPreview);
    iconBar.appendChild(iconStatus);
    dlgBody.appendChild(iconBar);

    function syncPreview() {
      const v = (iconInput.value || '').trim();
      const show = v && (v.startsWith('/') || /^https?:\/\//i.test(v));
      iconPreview.hidden = !show;
      if (show) iconPreview.src = v;
    }
    function setIconStatus(text, kind) {
      iconStatus.textContent = text || '';
      iconStatus.className = 'hint icon-status' + (kind ? ' ' + kind : '');
    }

    iconInput.addEventListener('input', () => {
      iconInput.dataset.auto = '';   // 手动改过就不再自动覆盖
      syncPreview();
      setIconStatus('');
    });
    syncPreview();

    let grabbing = false;
    async function grabIcon(silent) {
      if (grabbing) return;
      const lan = dlgBody.querySelector('input[name="url_lan"]');
      const wan = dlgBody.querySelector('input[name="url_wan"]');
      const target = ((lan && lan.value) || (wan && wan.value) || '').trim();
      if (!target) {
        if (!silent) setIconStatus('先填内网或外网地址', 'bad');
        return;
      }
      grabbing = true;
      grabBtn.disabled = true;
      setIconStatus('正在抓图标…');
      try {
        const r = await api('POST', '/api/admin/icon-from-url', { url: target });
        iconInput.value = r.icon;
        iconInput.dataset.auto = '1';
        syncPreview();
        let host = '';
        try { host = new URL(r.source).host; } catch (e) { host = r.source; }
        if (r.reused) {
          setIconStatus('图标库里已有这张，直接复用', 'ok');
        } else {
          setIconStatus('已从 ' + host + ' 取到 ' + Math.round((r.bytes || 0) / 1024) + ' KB', 'ok');
        }
      } catch (ex) {
        setIconStatus(ex.message, 'bad');
      } finally {
        grabbing = false;
        grabBtn.disabled = false;
      }
    }
    grabBtn.addEventListener('click', () => grabIcon(false));

    // 自动模式只在"新增"时启用；编辑老卡片不擅自换掉人家选过的图标
    if (!item) {
      const lanInput = urlLanField.querySelector('input');
      let timer = 0;
      lanInput.addEventListener('input', () => {
        clearTimeout(timer);
        const typed = (lanInput.value || '').trim();
        if (!/^https?:\/\//i.test(typed) && !/^[\w.-]+(:\d+)?(\/|$)/.test(typed)) return;
        timer = setTimeout(() => {
          if (iconInput.dataset.auto === '1' || !iconInput.value) grabIcon(true);
        }, 900);
      });
      lanInput.addEventListener('blur', () => {
        clearTimeout(timer);
        if (iconInput.dataset.auto === '1' || !iconInput.value) grabIcon(true);
      });
    }
    const picker = el('div', 'wide');
    const pickBtn = el('button', 'btn mini', '从图标库选');
    pickBtn.type = 'button';
    pickBtn.addEventListener('click', () => {
      const grid = el('div', 'icon-grid');
      state.icons.forEach((ic) => {
        const cell = el('div', 'icon-cell');
        const img = el('img');
        img.src = ic.url;
        img.alt = ic.name;
        cell.appendChild(img);
        cell.addEventListener('click', () => {
          const input = dlgBody.querySelector('input[name="icon"]');
          input.value = ic.url;
          grid.remove();
        });
        grid.appendChild(cell);
      });
      if (!state.icons.length) grid.appendChild(el('p', 'hint', '图标库还是空的'));
      dlgBody.appendChild(grid);
    });
    picker.appendChild(pickBtn);
    dlgBody.appendChild(picker);
    dlgBody.appendChild(field('描述', 'description', item ? item.description : '', { wide: true, maxlength: 200 }));
    dlgBody.appendChild(field('打开方式', 'target', item ? item.target : '_blank', {
      type: 'select',
      options: [['_blank', '新标签页'], ['_self', '当前页']],
    }));
    dlg.showModal();
  }

  dlgForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(dlgForm);
    const body = Object.fromEntries(fd.entries());
    body.group_id = Number(body.group_id);
    try {
      if (editing) {
        await api('PATCH', '/api/admin/items/' + editing.id, body);
      } else {
        await api('POST', '/api/admin/items', body);
      }
      dlg.close();
      await load();
    } catch (ex) {
      alert(ex.message);
    }
  });

  document.getElementById('dlg-cancel').addEventListener('click', () => dlg.close());
  document.getElementById('btn-add-item').addEventListener('click', () => {
    if (!state.groups.length) return alert('请先创建一个分组');
    openItemDialog(null);
  });
  document.getElementById('btn-add-group').addEventListener('click', async () => {
    const name = prompt('新分组名称');
    if (!name || !name.trim()) return;
    await api('POST', '/api/admin/groups', { name: name.trim() });
    await load();
  });

  /* ---------- 图标库 ---------- */

  function renderIcons() {
    const grid = document.getElementById('icon-grid');
    if (!grid) return;
    grid.innerHTML = '';
    if (!state.icons.length) {
      grid.appendChild(el('p', 'hint', '还没有上传过图标。'));
      return;
    }
    state.icons.forEach((ic) => {
      const cell = el('div', 'icon-cell');
      const img = el('img');
      img.src = ic.url;
      img.alt = ic.name;
      cell.appendChild(img);
      const nm = el('span', 'nm', ic.name);
      nm.title = '点击改名';
      nm.addEventListener('click', () => startRename(cell, ic));
      cell.appendChild(nm);
      if (ic.used) cell.appendChild(el('span', 'used', '被 ' + ic.used + ' 张卡片使用'));
      else cell.appendChild(el('span', 'used empty', '未使用'));
      const ops = el('div', 'ops');
      const copy = el('button', 'icon-btn', '⧉');
      copy.type = 'button';
      copy.title = '复制地址';
      copy.addEventListener('click', () => {
        navigator.clipboard.writeText(location.origin + ic.url).then(() => {
          copy.textContent = '✓';
          setTimeout(() => { copy.textContent = '⧉'; }, 1200);
        });
      });
      const del = el('button', 'icon-btn', '✕');
      del.type = 'button';
      del.title = '删除';
      del.addEventListener('click', async () => {
        if (!confirm('删除图标 ' + ic.name + '？')) return;
        try {
          await api('DELETE', '/api/admin/icons/' + ic.id);
          await load();
        } catch (ex) {
          alert(ex.message);
        }
      });
      ops.appendChild(copy);
      ops.appendChild(del);
      cell.appendChild(ops);
      grid.appendChild(cell);
    });
  }

  /* 行内改名：点名字变输入框，Enter/失焦保存，Esc 放弃 */
  function startRename(cell, ic) {
    if (cell.querySelector('.rename')) return;
    const nm = cell.querySelector('.nm');
    if (!nm) return;
    const inp = el('input', 'rename');
    inp.type = 'text';
    inp.value = ic.name;
    inp.maxLength = 80;
    nm.replaceWith(inp);
    inp.focus();
    inp.select();
    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      const v = inp.value.trim();
      if (!save || !v || v === ic.name) {
        // 没改动就原地还原，不触整表重渲染（免得滚动位置被重置）
        const back = el('span', 'nm', ic.name);
        back.title = '点击改名';
        back.addEventListener('click', () => startRename(cell, ic));
        inp.replaceWith(back);
        return;
      }
      try {
        await api('PATCH', '/api/admin/icons/' + ic.id, { name: v });
        ic.name = v;
        await load();
      } catch (ex) {
        alert(ex.message);
        await load();
      }
    };
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    });
    inp.addEventListener('blur', () => finish(true));
  }

  document.getElementById('icon-file').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await api('POST', '/api/admin/icons', fd);
      e.target.value = '';
      await load();
      if (r && r.reused) alert('这张图标库里已经有了，直接复用，没有重复保存。');
    } catch (ex) {
      alert(ex.message);
    }
  });

  /* ---------- 设置 ---------- */

  function fillSettings() {
    const f = document.getElementById('settings-form');
    Object.entries(state.settings).forEach(([k, v]) => {
      const input = f.querySelector('[name="' + k + '"]');
      if (input) input.value = v;
    });
  }

  document.getElementById('settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = Object.fromEntries(fd.entries());
    try {
      await api('PUT', '/api/admin/settings', body);
      const ok = document.getElementById('settings-ok');
      ok.hidden = false;
      setTimeout(() => { ok.hidden = true; }, 2000);
      await load();
    } catch (ex) {
      alert(ex.message);
    }
  });

  /* ---------- 备份 ---------- */

  document.getElementById('btn-restore').addEventListener('click', async () => {
    const input = document.getElementById('restore-file');
    if (!input.files[0]) return alert('先选一个 zip 备份包');
    if (!confirm('确认恢复？当前数据库会先另存为 app.db.bak.*')) return;
    const fd = new FormData();
    fd.append('file', input.files[0]);
    try {
      await api('POST', '/api/admin/restore', fd);
      alert('恢复完成，建议重启容器后刷新');
      location.reload();
    } catch (ex) {
      alert(ex.message);
    }
  });

  /* ---------- 日志 ---------- */

  function renderAudit(rows) {
    const tb = document.querySelector('#audit-table tbody');
    if (!tb) return;
    tb.innerHTML = '';
    (rows || []).forEach((r) => {
      const tr = el('tr');
      [r.created_at, r.user_id || '-', r.action, r.target || '-', r.ip || '-'].forEach((v) => {
        tr.appendChild(el('td', null, String(v)));
      });
      tb.appendChild(tr);
    });
  }

  /* ---------- 拖拽排序 ---------- */

  let drag = null;

  function clearMarks() {
    document
      .querySelectorAll('.dz-before,.dz-after,.dz-target,.dragging')
      .forEach((n) => n.classList.remove('dz-before', 'dz-after', 'dz-target', 'dragging'));
  }

  function dropSide(e, node) {
    const r = node.getBoundingClientRect();
    return e.clientY - r.top < r.height / 2 ? 'before' : 'after';
  }

  document.addEventListener('dragstart', (e) => {
    const li = e.target.closest('#group-list li[data-gid]');
    if (li) {
      drag = { kind: 'group', gid: Number(li.dataset.gid) };
      li.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', li.dataset.gid);
      return;
    }
    const row = e.target.closest('.item-row[data-iid]');
    if (row) {
      drag = { kind: 'item', iid: Number(row.dataset.iid) };
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', row.dataset.iid);
    }
  });

  document.addEventListener('dragover', (e) => {
    if (!drag) return;
    if (drag.kind === 'group') {
      const li = e.target.closest('#group-list li[data-gid]');
      if (!li) return;
      e.preventDefault();
      const side = dropSide(e, li);
      clearMarks();
      li.classList.add(side === 'before' ? 'dz-before' : 'dz-after');
      return;
    }
    // 卡片：既可拖到另一张卡片上排序，也可拖到左侧分组实现跨组
    const gLi = e.target.closest('#group-list li[data-gid]');
    if (gLi) {
      e.preventDefault();
      clearMarks();
      gLi.classList.add('dz-target');
      return;
    }
    const row = e.target.closest('.item-row[data-iid]');
    if (row) {
      e.preventDefault();
      const side = dropSide(e, row);
      clearMarks();
      row.classList.add(side === 'before' ? 'dz-before' : 'dz-after');
    }
  });

  document.addEventListener('drop', async (e) => {
    if (!drag) return;
    e.preventDefault();
    const snapshot = drag;
    drag = null;

    if (snapshot.kind === 'group') {
      const li = e.target.closest('#group-list li[data-gid]');
      if (!li) return clearMarks();
      const before = dropSide(e, li) === 'before';
      const from = state.groups.findIndex((g) => g.id === snapshot.gid);
      const anchor = state.groups.findIndex((g) => g.id === Number(li.dataset.gid));
      if (from < 0 || anchor < 0 || from === anchor) return clearMarks();
      const [moved] = state.groups.splice(from, 1);
      let insert = anchor + (before ? 0 : 1);
      if (from < insert) insert -= 1;
      state.groups.splice(insert, 0, moved);
      try {
        await api('POST', '/api/admin/groups/reorder', { ids: state.groups.map((g) => g.id) });
        await load();
      } catch (ex) {
        alert(ex.message);
        await load();
      }
      return;
    }

    const gLi = e.target.closest('#group-list li[data-gid]');
    if (gLi) {
      try {
        await moveItemToGroup(snapshot.iid, Number(gLi.dataset.gid));
      } catch (ex) {
        alert(ex.message);
        await load();
      }
      return;
    }

    const row = e.target.closest('.item-row[data-iid]');
    if (!row) return clearMarks();
    const before = dropSide(e, row) === 'before';
    const targetId = Number(row.dataset.iid);
    if (targetId === snapshot.iid) return clearMarks();
    const ids = groupIds(state.selected);
    const from = ids.indexOf(snapshot.iid);
    let to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return clearMarks();
    ids.splice(from, 1);
    if (!before) to += 1;
    if (from < to) to -= 1;
    ids.splice(to, 0, snapshot.iid);
    try {
      await commitItemOrder({ [state.selected]: ids });
    } catch (ex) {
      alert(ex.message);
      await load();
    }
  });

  document.addEventListener('dragend', () => {
    drag = null;
    clearMarks();
  });

  /* ---------- 退出 ---------- */

  document.getElementById('btn-logout').addEventListener('click', async () => {
    try { await api('POST', '/api/auth/logout'); } catch (e) { /* ignore */ }
    location.href = '/';
  });

  /* ---------- Tab ---------- */

  document.getElementById('tabs').addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === btn));
    document.querySelectorAll('.pane').forEach((p) => {
      p.classList.toggle('active', p.id === 'pane-' + btn.dataset.tab);
    });
  });

  load().catch((ex) => {
    console.error(ex);
    if (String(ex.message).indexOf('401') !== -1) location.href = '/login';
  });
})();
