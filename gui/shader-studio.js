// Shader Studio read-only viewer (extracted from gui/app.js).
(() => {
  'use strict';

  const _sh = { page: 0, total: 0, sel: null, busy: false, poll: null };
  const _FREQ_CLASS = { 0: "vtx", 3: "pix", 5: "cmp" };
  let _shQTimer = null;

  function _shEl(id) { return document.getElementById(id); }

  async function openShaderStudio() {
    _shEl("shader-overlay").classList.add("active");
    lucide.createIcons({ nodes: [_shEl("shader-overlay")] });
    await refreshShaderStatus();
  }

  function closeShaderStudio() {
    if (_sh.poll) { clearInterval(_sh.poll); _sh.poll = null; }
    _shEl("shader-overlay").classList.remove("active");
  }

  async function refreshShaderStatus() {
    let st;
    try { st = await api("/api/shaders/status"); }
    catch (e) { toast("Shader status failed: " + e.message, "warning"); return; }
    if (!st.ok || !st.tools_ok) {
      _shEl("shader-build").style.display = "flex";
      _shEl("shader-browser").style.display = "none";
      _shEl("shader-build-title").textContent = "Shader tools not found.";
      _shEl("shader-build-btn").style.display = "none";
      _shEl("shader-build-err").style.display = "flex";
      _shEl("shader-build-err").textContent = "Expected retoc + dxc under Tools/shaders.";
      return;
    }
    if (st.db_ready) { showShaderBrowser(st.libraries || []); }
    else { _shEl("shader-build").style.display = "flex"; _shEl("shader-browser").style.display = "none"; }
  }

  async function startShaderBuild() {
    _shEl("shader-build-btn").style.display = "none";
    _shEl("shader-build-err").style.display = "none";
    _shEl("shader-build-prog").style.display = "block";
    _shEl("shader-bar-fill").style.setProperty("--progress", "0");
    _shEl("shader-build-msg").textContent = "Starting…";
    try { await api("/api/shaders/build", { method: "POST" }); }
    catch (e) { _shBuildError(e.message); return; }
    _sh.poll = setInterval(async () => {
      let st; try { st = await api("/api/shaders/status"); } catch { return; }
      const b = st.build || {};
      if (b.error) { clearInterval(_sh.poll); _sh.poll = null; _shBuildError(b.error); return; }
      _shEl("shader-bar-fill").style.setProperty("--progress", Math.max(0, Math.min(100, b.pct || 0)) / 100);
      _shEl("shader-build-msg").textContent =
        (b.phase || "Working…") + (b.count ? `  (${b.count.toLocaleString()} shaders)` : "");
      if (st.db_ready && b.done) {
        clearInterval(_sh.poll); _sh.poll = null;
        toast("Shader index built", "success");
        showShaderBrowser(st.libraries || []);
      }
    }, 1200);
  }

  function _shBuildError(msg) {
    _shEl("shader-build-prog").style.display = "none";
    _shEl("shader-build-btn").style.display = "";
    _shEl("shader-build-err").style.display = "flex";
    _shEl("shader-build-err").textContent = "Build failed: " + msg;
  }

  function showShaderBrowser(libs) {
    _shEl("shader-build").style.display = "none";
    _shEl("shader-browser").style.display = "flex";
    const sel = _shEl("shader-lib");
    sel.innerHTML = libs.map(l =>
      `<option value="${l.name}">${l.short} — ${l.total.toLocaleString()} shaders</option>`).join("");
    const totalAll = libs.reduce((a, l) => a + l.total, 0);
    _shEl("shader-subtitle").textContent = `${totalAll.toLocaleString()} shaders indexed`;
    _sh.page = 0;
    loadShaderList();
  }

  async function loadShaderList() {
    const lib = _shEl("shader-lib").value;
    const freq = _shEl("shader-freq").value;
    const q = _shEl("shader-q").value.trim();
    const list = _shEl("shader-list");
    list.innerHTML = `<div class="shader-loading"><div class="spinner"></div></div>`;
    let res;
    try {
      res = await api(`/api/shaders/list?lib=${encodeURIComponent(lib)}&freq=${freq}` +
                      `&q=${encodeURIComponent(q)}&page=${_sh.page}&page_size=200`);
    } catch (e) { list.innerHTML = `<div class="muted" style="padding:16px">Error: ${e.message}</div>`; return; }
    if (!res.ok) { list.innerHTML = `<div class="muted" style="padding:16px">${res.error}</div>`; return; }
    _sh.total = res.total;
    if (!res.rows.length) { list.innerHTML = `<div class="muted" style="padding:16px">No shaders match.</div>`; }
    else {
      list.innerHTML = res.rows.map(r => {
        const fc = _FREQ_CLASS[r.freq] || "oth";
        return `<div class="shader-row" data-lib="${r.lib}" data-idx="${r.idx}">
          <span class="sh-badge ${fc}">${r.freq_name}</span>
          <span class="sh-idx">#${r.idx}</span>
          <span class="sh-hash">${r.hash.slice(0, 16)}</span>
          <span class="sh-size">${(r.size / 1024).toFixed(1)}K</span>
        </div>`;
      }).join("");
      list.querySelectorAll(".shader-row").forEach(el =>
        el.addEventListener("click", () => selectShader(el)));
    }
    const start = _sh.total ? _sh.page * 200 + 1 : 0;
    const end = Math.min(_sh.total, (_sh.page + 1) * 200);
    _shEl("shader-count").textContent = `${_sh.total.toLocaleString()} match`;
    _shEl("shader-page").textContent = _sh.total ? `${start.toLocaleString()}–${end.toLocaleString()}` : "0";
    _shEl("shader-prev").disabled = _sh.page === 0;
    _shEl("shader-next").disabled = (_sh.page + 1) * 200 >= _sh.total;
  }

  async function selectShader(el) {
    document.querySelectorAll(".shader-row.sel").forEach(r => r.classList.remove("sel"));
    el.classList.add("sel");
    _sh.cur = { lib: el.dataset.lib, idx: el.dataset.idx };
    _shEl("shader-detail-empty").style.display = "none";
    _shEl("shader-detail-content").style.display = "block";
    _shEl("shader-meta").innerHTML = `<div class="shader-loading"><div class="spinner"></div><span>Extracting & disassembling…</span></div>`;
    _shEl("shader-disasm").textContent = "";
    let res;
    try { res = await api(`/api/shaders/disasm?lib=${encodeURIComponent(el.dataset.lib)}&idx=${el.dataset.idx}`); }
    catch (e) { _shEl("shader-meta").innerHTML = `<div class="warning">${e.message}</div>`; return; }
    if (!res.ok) { _shEl("shader-meta").innerHTML = `<div class="warning">${res.error}</div>`; return; }
    const m = res.meta || {};
    _shEl("shader-meta").innerHTML =
      `<div class="sh-meta-row">
         <b>${m.stage || "Shader"}</b>
         ${m.entry ? `<span class="sh-chip">entry <code>${m.entry}</code></span>` : ""}
         <span class="sh-chip">${(m.dxbc_size || 0).toLocaleString()} B</span>
       </div>`;
    _shEl("shader-disasm").textContent = res.disasm || "";
    renderShaderProps(res.properties || {});
    _shSelectTab("props");
  }

  function _shSelectTab(tab) {
    document.querySelectorAll(".sh-tab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
    _shEl("shader-props").style.display = tab === "props" ? "block" : "none";
    _shEl("shader-disasm").style.display = tab === "raw" ? "block" : "none";
  }

  function renderShaderProps(p) {
    const wrap = _shEl("shader-props");
    const res = p.resources || [];
    const cbufs = res.filter(r => r.type === "cbuffer");
    const other = res.filter(r => r.type !== "cbuffer");
    const sigRows = (arr) => arr.length
      ? arr.map(r => `<tr><td class="pk">${_esc(r.name)}</td><td class="pm">${_esc(r.format)}</td>
          <td class="pm">${_esc(r.mask || "")}</td><td class="pm">reg ${_esc(r.register)}</td></tr>`).join("")
      : `<tr><td colspan="4" class="pm">none</td></tr>`;

    let html = `<div class="sh-note"><i data-lucide="info" size="13"></i>
        These are the shader's live properties. Constant buffers are its parameter banks.</div>`;

    html += `<div class="sh-sec">
        <div class="sh-sec-h"><i data-lucide="box" size="13"></i> Constant buffers (params)
          <span class="pm">${cbufs.length}</span></div>
        <table class="sh-tbl">
          ${cbufs.length ? cbufs.map(r => `<tr>
            <td class="pk">${_esc(r.bind)}</td><td>${_esc(r.name)}</td>
            <td><input class="sh-pval" placeholder="read-only" disabled></td></tr>`).join("")
          : `<tr><td class="pm">none</td></tr>`}
        </table></div>`;

    html += `<div class="sh-sec">
        <div class="sh-sec-h"><i data-lucide="plug" size="13"></i> Textures &amp; samplers
          <span class="pm">${other.length}</span></div>
        <table class="sh-tbl">
          ${other.length ? other.map(r => `<tr>
            <td class="pk">${_esc(r.bind)}</td><td class="pm">${_esc(r.type)}</td>
            <td class="pm">${_esc(r.fmt || "")}</td><td>${_esc(r.name)}</td></tr>`).join("")
          : `<tr><td class="pm">none</td></tr>`}
        </table></div>`;

    html += `<div class="sh-sec">
        <div class="sh-sec-h"><i data-lucide="arrow-down-to-line" size="13"></i> Input signature
          <span class="pm">${(p.input || []).length}</span></div>
        <table class="sh-tbl">${sigRows(p.input || [])}</table></div>
      <div class="sh-sec">
        <div class="sh-sec-h"><i data-lucide="arrow-up-from-line" size="13"></i> Output signature
          <span class="pm">${(p.output || []).length}</span></div>
        <table class="sh-tbl">${sigRows(p.output || [])}</table></div>`;

    wrap.innerHTML = html;
    lucide.createIcons({ nodes: [wrap] });
  }

  _shEl("shader-build-btn")?.addEventListener("click", startShaderBuild);
  _shEl("shader-close")?.addEventListener("click", closeShaderStudio);
  ["shader-lib", "shader-freq"].forEach(id =>
    _shEl(id)?.addEventListener("change", () => { _sh.page = 0; loadShaderList(); }));
  _shEl("shader-q")?.addEventListener("input", () => {
    clearTimeout(_shQTimer);
    _shQTimer = setTimeout(() => { _sh.page = 0; loadShaderList(); }, 250);
  });
  _shEl("shader-prev")?.addEventListener("click", () => { if (_sh.page > 0) { _sh.page--; loadShaderList(); } });
  _shEl("shader-next")?.addEventListener("click", () => {
    if ((_sh.page + 1) * 200 < _sh.total) { _sh.page++; loadShaderList(); }
  });
  document.querySelectorAll(".sh-tab").forEach(b =>
    b.addEventListener("click", () => _shSelectTab(b.dataset.tab)));

  window.openShaderStudio = openShaderStudio;
  window.closeShaderStudio = closeShaderStudio;
})();
