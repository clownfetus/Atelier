"use strict";

// ── icons ─────────────────────────────────────────────────────────────────────
lucide.createIcons();

// ── state ─────────────────────────────────────────────────────────────────────
const NAV_ROOT    = { path: "" };
let   nav         = { ...NAV_ROOT };
let   history     = [{ ...NAV_ROOT }];
let   histIdx     = 0;
let   allItems    = [];      // current grid items (raw from server)
let   sidebarData = {};      // token -> {name, game_rel, skin_id, char_name, skin_name, selected}
let   importing   = false;
let   pendingImport = null;
let   pendingClear  = null;
let   pendingImportAll = null;
let   suppressChangeToastUntil = Date.now() + 5000;
let   suppressedImportGameRels = new Set();
let   _pathLabels = {};      // "Characters/1234" -> "1234 — Spider-Man" (cached from browse results)
let   _modsFolderSet   = false; // whether a mods folder is configured (gates "Copy to %s/")
let   _modsFolderPath  = "";    // configured mods folder, for the "Copy to %s/" label
let   _protectionPassword = ""; // Settings → Protection Password (gates "Password Protect")
let   _pathsMode     = false; // setup overlay opened as the editable Settings panel (vs first-run)
let   _pendingOverwriteConfirm = null;

// ── handler registry ──────────────────────────────────────────────────────────
const ASSET_HANDLERS = {
  texture:  { import_endpoint: "/api/import_texture",  preview: true,  icon: "image"        },
  material: { import_endpoint: "/api/import_material", preview: false, icon: "circle-star"  },
  vfx:      { import_endpoint: "/api/import_vfx",      preview: false, icon: "sparkles"     },
  mesh:     { import_endpoint: null,                   preview: false, icon: "scan-box"     },
  curve:    { import_endpoint: "/api/curve_params",    preview: false, icon: "spline"       },
  text:     { import_endpoint: "/api/text_params",     preview: false, icon: "type-outline" },
};
function handlerFor(ft) { return ASSET_HANDLERS[ft] || { import_endpoint: "/api/import", preview: false, icon: "file-question" }; }

const ASSET_ICON_CLS = {
  texture:  "texture-icon",
  vfx:      "vfx-icon",
  material: "material-icon",
  mesh:     "mesh-icon",
  curve:    "curve-icon",
  text:     "text-icon",
};
function assetIconCls(ft) { return ASSET_ICON_CLS[ft] || "unhandled-icon"; }

const FOLDER_ICON_PATTERNS = [
  [/^characters?$/i,    "char-icon"],
  [/^ui$/i,             "ui-folder-icon"],
  [/^textures?$/i,      "texture-folder-icon"],
  [/^materials?$/i,     "material-folder-icon"],
  [/^(vfx|effects?)$/i, "vfx-folder-icon"],
  [/^meshes?$/i,        "mesh-folder-icon"],
  [/^(text|stringtables?)$/i, "text-folder-icon"],
];
function folderIconCls(name) {
  const hit = FOLDER_ICON_PATTERNS.find(([re]) => re.test(name));
  return hit ? hit[1] : "folder-icon";
}

const ICON_CLS_TO_LUCIDE = {
  "folder-icon":          "folder",
  "texture-folder-icon":  "image",
  "material-folder-icon": "circle-star",
  "vfx-folder-icon":      "sparkles",
  "mesh-folder-icon":     "scan-box",
  "text-folder-icon":     "type-outline",
  "char-icon":            "square-user-round",
  "ui-folder-icon":       "swatch-book",
  "texture-icon":         "image",
  "vfx-icon":             "sparkles",
  "material-icon":        "circle-star",
  "mesh-icon":            "scan-box",
  "curve-icon":           "spline",
  "text-icon":            "type-outline",
  "unhandled-icon":       "file-question",
};

// ── helpers ───────────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  try {
    return await res.json();
  } catch {
    return { ok: false, error: `server error (${res.status})` };
  }
}

function toastSpinner(msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<div class="spinner"></div><span>${msg}</span>`;
  document.getElementById("toast-area").appendChild(el);
  return el;
}

function toast(msg, type = "info", duration = 3200) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const icon = type === "success" ? "check-circle"
             : type === "warning" ? "alert-triangle"
             : "info";
  el.innerHTML = `<i data-lucide="${icon}" size="14"></i><span>${msg}</span>`;
  document.getElementById("toast-area").appendChild(el);
  lucide.createIcons({ nodes: [el] });
  let remaining = duration, start = Date.now(), t = setTimeout(() => el.remove(), duration);
  el.addEventListener("mouseenter", () => { clearTimeout(t); remaining -= Date.now() - start; });
  el.addEventListener("mouseleave", () => { start = Date.now(); t = setTimeout(() => el.remove(), remaining); });
  el.addEventListener("click", () => { clearTimeout(t); el.remove(); });
}

function setStatus(msg) {
  document.getElementById("status-msg").textContent = msg;
}

function skinIdFromPath(path) {
  const m = (path || "").match(/^Characters\/\d{4}\/(\d{7})/i);
  return m ? m[1] : null;
}

// ── navigation ────────────────────────────────────────────────────────────────
function pushNav(newNav) {
  history = history.slice(0, histIdx + 1);
  history.push({ ...newNav });
  histIdx = history.length - 1;
  nav = { ...newNav };
  updateNavBtns();
  document.getElementById("search-input").value = "";
  renderGrid();
  renderBreadcrumbs();
  renderSidebar();
}

function updateNavBtns() {
  document.getElementById("btn-back").disabled    = histIdx <= 0;
  document.getElementById("btn-forward").disabled = histIdx >= history.length - 1;
}

document.getElementById("btn-back").addEventListener("click", () => {
  if (histIdx <= 0) return;
  histIdx--;
  nav = { ...history[histIdx] };
  document.getElementById("search-input").value = "";
  updateNavBtns();
  renderGrid();
  renderBreadcrumbs();
  renderSidebar();
});
document.getElementById("btn-forward").addEventListener("click", () => {
  if (histIdx >= history.length - 1) return;
  histIdx++;
  nav = { ...history[histIdx] };
  document.getElementById("search-input").value = "";
  updateNavBtns();
  renderGrid();
  renderBreadcrumbs();
  renderSidebar();
});

// ── breadcrumbs ───────────────────────────────────────────────────────────────
function renderBreadcrumbs() {
  const bc = document.getElementById("breadcrumbs");
  bc.innerHTML = "";

  const crumb = (label, navState) => {
    const el = document.createElement("span");
    el.className = "crumb" + (navState === null ? " active" : "");
    el.textContent = label;
    if (navState !== null) el.addEventListener("click", () => pushNav(navState));
    return el;
  };
  const sep = () => {
    const el = document.createElement("span");
    el.className = "sep";
    el.innerHTML = '<i data-lucide="chevron-right" size="12"></i>';
    return el;
  };

  const parts = nav.path ? nav.path.split("/") : [];
  const homeCrumb = document.createElement("span");
  homeCrumb.className = "crumb" + (parts.length === 0 ? " active" : "");
  homeCrumb.title = "Import";
  homeCrumb.innerHTML = '<i data-lucide="house" size="12"></i>';
  if (parts.length > 0) homeCrumb.addEventListener("click", () => pushNav({ path: "" }));
  bc.appendChild(homeCrumb);

  let accumulated = "";
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    accumulated = accumulated ? `${accumulated}/${part}` : part;
    const isLast = i === parts.length - 1;
    const label  = _pathLabels[accumulated] || part;
    bc.appendChild(sep());
    bc.appendChild(crumb(label, isLast ? null : { path: accumulated }));
  }

  lucide.createIcons({ nodes: [bc] });
}

// ── grid rendering ────────────────────────────────────────────────────────────
function _makeCard(item) {
  if (item.type === "folder") {
    return {
      type:    "folder",
      label:   item.label || item.name,
      iconCls: folderIconCls(item.name),
      onClick: () => pushNav({ path: item.rel_path }),
    };
  }
  const ft = item.file_type || "other";
  return {
    type:      "asset",
    file_type: ft,
    label:     item.name,
    iconCls:   assetIconCls(ft),
    imported:  item.imported,
    token:     item.token,
    game_rel:  item.game_rel,
    rel_path:  item.rel_path,
    onClick:   () => handleAssetClick(item),
  };
}

async function renderGrid() {
  const area = document.getElementById("grid-area");
  area.innerHTML = '<div id="empty-state"><div class="spinner" style="margin:0 auto 12px"></div><div>Loading…</div></div>';
  document.getElementById("import-all-btn").disabled = true;

  try {
    const data = await api(`/api/browse?path=${encodeURIComponent(nav.path || "")}`);
    if (data.error) throw new Error(data.error);
    allItems = data;

    // Cache folder labels for breadcrumbs
    for (const item of data) {
      if (item.type === "folder" && item.label && item.label !== item.name) {
        _pathLabels[item.rel_path] = item.label;
      }
    }

    buildGrid(data.map(_makeCard));

    const importable = data.filter(d => d.type === "asset" && d.file_type === "texture");
    document.getElementById("import-all-btn").disabled = importable.length === 0;

    const unimportedTextures = data.filter(d => d.type === "asset" && d.file_type === "texture" && !d.imported);
    if (unimportedTextures.length) {
      try {
        const pf = await api("/api/prefetch_thumbs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ game_rels: unimportedTextures.map(t => t.game_rel) }),
        });
        (pf.cached || []).forEach(gr => {
          document.querySelectorAll(`img[data-game-rel="${CSS.escape(gr)}"]`).forEach(img => {
            img.src = `/api/thumb?game_rel=${encodeURIComponent(gr)}`;
          });
        });
      } catch (_) {}
    }
  } catch (e) {
    area.innerHTML = `<div id="empty-state" style="color:var(--acc)">${e.message}</div>`;
  }
}

function buildGrid(cards) {
  const area = document.getElementById("grid-area");
  const q = document.getElementById("search-input").value.trim().toLowerCase();

  let filtered = q ? cards.filter(c => c.label.toLowerCase().includes(q)) : cards;

  if (!nav.path) {
    const isPinned = c => c.type === "folder" && c.iconCls && c.iconCls !== "folder-icon";
    filtered = [...filtered.filter(isPinned), ...filtered.filter(c => !isPinned(c))];
  }

  if (!filtered.length) {
    area.innerHTML = `<div id="empty-state">
      <i data-lucide="${q ? "search-x" : "folder-open"}" size="32" style="color:var(--muted)"></i>
      <div style="margin-top:8px">${q ? "No matches" : "Empty folder"}</div>
    </div>`;
    lucide.createIcons({ nodes: [area] });
    return;
  }

  const grid = document.createElement("div");
  grid.className = "grid";

  filtered.forEach(card => {
    const el = document.createElement("div");
    el.className = "card" + (card.imported ? " imported" : "");
    el.title = card.label;

    const thumb = document.createElement("div");
    thumb.className = "card-thumb";

    if (card.type === "asset" && handlerFor(card.file_type).preview && card.game_rel) {
      const img = document.createElement("img");
      img.dataset.gameRel = card.game_rel;
      img.alt = card.label;
      if (card.imported) {
        if (card.token) img.dataset.token = card.token;
        img.src    = `/api/thumb?game_rel=${encodeURIComponent(card.game_rel)}`;
        img.onerror = () => {
          img.style.display = "none";
          const icon = makeIcon(card);
          thumb.appendChild(icon);
          lucide.createIcons({ nodes: [thumb] });
        };
      } else {
        img.style.display = "none";
        const spin = document.createElement("div");
        spin.className = "spinner";
        thumb.appendChild(spin);
        img.onload  = () => { img.style.display = ""; spin.style.display = "none"; };
        img.onerror = () => {
          img.style.display = "none";
          spin.replaceWith(makeIcon(card));
          lucide.createIcons({ nodes: [thumb] });
        };
      }
      thumb.appendChild(img);
    } else {
      thumb.appendChild(makeIcon(card));
    }

    const name = document.createElement("div");
    name.className = "card-name";
    name.textContent = card.label;

    el.appendChild(thumb);
    el.appendChild(name);
    el.addEventListener("click", card.onClick);
    if (card.type === "asset") {
      el.addEventListener("contextmenu", e => _ctxShow(e, _ctxItemsCard(card)));
    }
    grid.appendChild(el);
  });

  area.innerHTML = "";
  area.appendChild(grid);
  lucide.createIcons({ nodes: [grid] });
}

function makeIcon(card) {
  const i = document.createElement("i");
  i.dataset.lucide = ICON_CLS_TO_LUCIDE[card.iconCls] || "file-question";
  i.className = `card-icon ${card.iconCls || ""}`;
  i.setAttribute("size", "40");
  return i;
}

// ── search ────────────────────────────────────────────────────────────────────
document.getElementById("search-input").addEventListener("input", () => {
  if (allItems.length) {
    buildGrid(allItems.map(_makeCard));
  }
  renderSidebar();
});

document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "f") {
    e.preventDefault();
    const si = document.getElementById("search-input");
    si.focus();
    si.select();
  }
});

// ── asset click / single import ───────────────────────────────────────────────
function handleImportedFileAction(item) {
  const ft = item.file_type || "texture";
  switch (ft) {
    case "material":
      openMaterialEditor(item);
      return;
    case "curve":
      openCurveEditor(item);
      return;
    case "vfx":
      openVfxEditor(item);
      return;
    case "world":
      openWorldEditor(item);
      return;
    case "text":
      openTextEditor(item);
      return;
    case "mesh":
      openBlend(item.game_rel);   // the edit lives in a .blend, not a .png
      return;
    default:
      fetch(`/api/open_with?game_rel=${encodeURIComponent(item.game_rel)}`);
  }
}

// ── Blender mesh editing ──────────────────────────────────────────────────────
// Extract is slow (asset extraction + every material's textures + a headless Blender run), so it
// gets a spinner toast and the result is summarised rather than silently finishing.
async function meshBlendExtract(game_rel, name, force = false) {
  const t = toastSpinner(`Preparing ${name} for Blender…`);
  setStatus(`Preparing ${name} for Blender…`);
  try {
    const res = await api("/api/mesh_blend_extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel, force: force ? 1 : 0 }),
    });
    t.remove();
    setStatus("");
    if (!res.ok) {
      if (res.can_force) {
        // The preflight refuses formats the rebuilder can't pack. Extracting anyway is useful for
        // INSPECTING such a mesh, so offer it -- but say plainly that a build will not work.
        if (confirm(`${res.error}\n\nExtract it anyway for inspection? A build will fail.`))
          return meshBlendExtract(game_rel, name, true);
        return;
      }
      toast(res.error || "extract failed", "warning", 8000);
      return;
    }
    const n = (res.textures || []).length, m = (res.materials || []).length;
    toast(`${name} ready in Blender — ${m} material${m === 1 ? "" : "s"}, ${n} texture${n === 1 ? "" : "s"}`, "success", 6000);
    // Blender keeps painted pixels only in memory for LINKED images: saving the .blend does not
    // save them, and reopening silently restores the original. Say so once, up front, because
    // the failure is invisible until the user has already lost the work.
    toast("Painted textures must be saved in Blender (Image ▸ Save) — saving the .blend alone isn't enough", "info", 12000);
    (res.warnings || []).slice(0, 4).forEach(w => toast(w, "warning", 9000));
    refreshSidebarEntry(game_rel, name, skinIdFromPath(nav.path));
    renderGrid();
    openBlend(game_rel);   // queuing a mesh means editing it now, same as a texture's auto "Open With"
  } catch (e) {
    t.remove();
    setStatus("");
    toast(`Error: ${e.message}`, "warning");
  }
}

function openBlend(game_rel) {
  api(`/api/open_blend?game_rel=${encodeURIComponent(game_rel)}`).then(r => {
    if (r && !r.ok) toast(r.error || "could not open the .blend", "warning");
  });
}

function handleAssetClick(item) {
  if ((item.file_type || "") === "mesh") {
    if (window.AtelierViewport) window.AtelierViewport.openMesh(item.game_rel, item.name, skinIdFromPath(nav.path));
    else toast("3D viewport failed to load", "warning");
    return;
  }
  if (item.imported && item.token) {
    handleImportedFileAction(item);
    return;
  }
  const ft   = item.file_type || "other";
  const kind = ft.charAt(0).toUpperCase() + ft.slice(1);
  const sid  = skinIdFromPath(nav.path);
  document.getElementById("confirm-title").textContent = `Edit ${kind}?`;
  document.getElementById("confirm-msg").textContent =
    `Edit ${ft} "${item.name}"${sid ? ` from skin ${sid}` : ""}?`;
  pendingImport = { skin_id: sid, rel_path: item.rel_path, game_rel: item.game_rel, name: item.name, file_type: ft };
  document.getElementById("confirm-overlay").classList.add("active");
}

document.getElementById("confirm-cancel").addEventListener("click", () => {
  document.getElementById("confirm-overlay").classList.remove("active");
  pendingImport = null;
});

document.getElementById("confirm-ok").addEventListener("click", async () => {
  document.getElementById("confirm-overlay").classList.remove("active");
  if (!pendingImport) return;
  const item = pendingImport; pendingImport = null;
  suppressedImportGameRels.add(item.game_rel);
  const loadingToast = toastSpinner(`Loading ${item.name}…`);
  setStatus(`Loading ${item.name}…`);
  try {
    let res;
    if (item.file_type === "material") {
      // materials: api_material_params triggers mat_json (extraction) for any game_rel path
      res = await api(`/api/material_params?game_rel=${encodeURIComponent(item.game_rel)}`);
    } else if (item.file_type === "curve") {
      // curves: api_curve_params triggers extraction + to_json for any game_rel path
      res = await api(`/api/curve_params?game_rel=${encodeURIComponent(item.game_rel)}`);
    } else if (item.file_type === "vfx") {
      // vfx: api_vfx_params triggers extraction + niagara_details for any game_rel path
      res = await api(`/api/vfx_params?game_rel=${encodeURIComponent(item.game_rel)}`);
    } else if (item.file_type === "world") {
      // world: api_world_params triggers extraction + to_json for the level sublevel
      res = await api(`/api/world_params?game_rel=${encodeURIComponent(item.game_rel)}`);
    } else if (item.file_type === "text") {
      // text: api_text_params triggers extraction + to_json for the StringTable
      res = await api(`/api/text_params?game_rel=${encodeURIComponent(item.game_rel)}`);
    } else {
      res = await api(handlerFor(item.file_type).import_endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skin_id: item.skin_id, rel_path: item.rel_path, game_rel: item.game_rel }),
      });
    }
    loadingToast.remove();
    if (res.ok) {
      suppressChangeToastUntil = Date.now() + 1500;
      suppressedImportGameRels.delete(item.game_rel);
      toast(`Loaded: ${item.name}`, "success");
      setStatus("");
      refreshSidebarEntry(item.game_rel, item.name, item.skin_id);
      const gridArea   = document.getElementById("grid-area");
      const savedScroll = gridArea.scrollTop;
      await renderGrid();
      gridArea.scrollTop = savedScroll;
      const importedItem = allItems.find(i => i.game_rel === item.game_rel) || item;
      handleImportedFileAction(importedItem);
    } else {
      suppressedImportGameRels.delete(item.game_rel);
      toast(`Edit failed: ${res.error}`, "warning");
      setStatus("");
    }
  } catch (e) {
    loadingToast.remove();
    suppressedImportGameRels.delete(item.game_rel);
    toast(`Error: ${e.message}`, "warning");
    setStatus("");
  }
});

// ── material parameter editor ──────────────────────────────────────────────────
let matEditor = null;

function _hx2(c) { return ("0" + Math.round(Math.min(255, Math.max(0, c * 255))).toString(16)).slice(-2); }
function _rgbHex(r, g, b, inten) { const n = Math.max(inten, 1e-6); return "#" + _hx2(r / n) + _hx2(g / n) + _hx2(b / n); }

function _seedColors(arr) {
  return (arr || []).map(c => ({ name: c.name, rgba: c.rgba.slice(),
                                 inten: Math.max(c.rgba[0], c.rgba[1], c.rgba[2], 1) }));
}
function _seedScalars(arr) {
  return (arr || []).map(s => ({ name: s.name, value: s.value, orig: s.value,
                                 max: Math.max(Math.abs(s.value) * 3, 1) }));
}

async function openMaterialEditor(item) {
  const ov = document.getElementById("material-overlay");
  document.getElementById("mat-title").textContent = item.name;
  document.getElementById("mat-sub").textContent = item.game_rel || "";
  document.getElementById("mat-status").textContent = "";
  document.getElementById("mat-body").innerHTML = '<div class="spinner" style="margin:44px auto"></div>';
  ov.classList.add("active");
  let res;
  try { res = await api(`/api/material_params?game_rel=${encodeURIComponent(item.game_rel)}`); }
  catch (e) { document.getElementById("mat-body").innerHTML = `<div class="mat-empty">Error: ${e.message}</div>`; return; }
  if (!res.ok) { document.getElementById("mat-body").innerHTML = `<div class="mat-empty">${res.error || "failed to read material"}</div>`; return; }
  matEditor = { game_rel: item.game_rel, name: item.name,
                colors: _seedColors(res.colors), scalars: _seedScalars(res.scalars) };
  renderMatEditor();
  loadSidebar();
  // Dyeing materials (chromas) recolour through the ColorID mask, so the "Region N" pickers below
  // do nothing visible on their own — attach a live composite so the user can see what they're doing.
  try {
    const di = await api(`/api/dye_info?game_rel=${encodeURIComponent(item.game_rel)}`);
    if (di && di.dyeable && matEditor && matEditor.game_rel === item.game_rel) {
      matEditor.dyeable = true;
      matEditor.dyeUsed = Object.keys(di.used || {}).filter(k => k !== "0").sort();
      renderMatEditor();
      dyeRefresh(0);
    }
  } catch (e) { /* preview is a bonus; never block the editor on it */ }
}

// ── dye preview ───────────────────────────────────────────────────────────────
function _dyeOverrides() {
  // the editor's live (unsaved) "Region N - Param" colours, shaped for the compositor
  const ov = {};
  (matEditor && matEditor.colors || []).forEach(c => {
    const m = /^Region\s+(\d+)\s*-\s*(.+)$/.exec(c.name || "");
    if (!m) return;
    (ov[m[1]] = ov[m[1]] || {})[m[2].trim()] = c.rgba;
  });
  return ov;
}

let _dyeTimer = null;
function dyeRefresh(delay = 140) {
  if (!matEditor || !matEditor.dyeable) return;
  clearTimeout(_dyeTimer);
  // debounce: a colour drag fires oninput continuously; the composite is ~80ms server-side
  _dyeTimer = setTimeout(async () => {
    const img = document.getElementById("dye-prev");
    if (!img || !matEditor) return;
    const gr = matEditor.game_rel;
    try {
      const r = await fetch("/api/dye_preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game_rel: gr, size: 512, overrides: _dyeOverrides() }),
      });
      if (!r.ok || !matEditor || matEditor.game_rel !== gr) return;   // editor closed/switched
      const b = await r.blob();
      if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
      const u = URL.createObjectURL(b);
      img.dataset.url = u; img.src = u;
    } catch (e) { /* leave the last good preview up */ }
  }, delay);
}

async function dyeDownload() {
  if (!matEditor) return;
  const st = document.getElementById("mat-status");
  st.textContent = "Baking dyed texture…";
  try {
    const r = await fetch("/api/dye_download", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: matEditor.game_rel, size: 2048, overrides: _dyeOverrides() }),
    });
    if (!r.ok) { st.textContent = "Download failed"; return; }
    const b = await r.blob();
    const u = URL.createObjectURL(b);
    const a = document.createElement("a");
    a.href = u; a.download = matEditor.name + "_dyed.png";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(u), 8000);
    st.textContent = "Downloaded " + a.download;
    toast("Baked dyed texture", "success");
  } catch (e) { st.textContent = "Error: " + e.message; }
}

function renderMatEditor() {
  const m = matEditor; if (!m) return;
  let h = "";
  if (m.dyeable) {
    const used = (m.dyeUsed || []).length ? `regions ${m.dyeUsed.join(", ")}` : "no regions in mask";
    h += `<div class="mat-section">Dye preview <span class="mat-tag">${used}</span></div>
      <div class="mat-row" style="align-items:flex-start;gap:14px">
        <img id="dye-prev" alt="dye preview"
             style="width:230px;height:230px;object-fit:contain;background:#0d0d10;border:1px solid var(--bd);border-radius:6px">
        <div style="flex:1;font-size:12px;line-height:1.5" class="muted">
          This skin recolours through its <b>ColorID</b> mask — the diffuse is shared across chromas,
          so the <b>Region N</b> colours below are what actually change its look.
          Edit any of them to see this update live.
          <div style="margin-top:12px">
            <button class="btn" onclick="dyeDownload()"><i data-lucide="download" size="13"></i> Download dyed texture</button>
          </div>
        </div>
      </div>`;
  }
  if (m.colors.length) {
    h += `<div class="mat-section">Colors</div>`;
    m.colors.forEach((c, i) => {
      h += `<div class="mat-row">
        <label title="${c.name}">${c.name}</label>
        <input type="color" value="${_rgbHex(c.rgba[0], c.rgba[1], c.rgba[2], c.inten)}" oninput="matColor(${i},this.value)">
        <span class="mat-tag">intensity</span>
        <input type="range" id="mir${i}" min="0" max="10" step="0.05" value="${Math.min(c.inten, 10)}" oninput="matInten(${i},this.value,1)">
        <input class="mat-num" id="min${i}" type="number" step="0.05" value="${+c.inten.toFixed(3)}" oninput="matInten(${i},this.value,0)">
        <span class="mat-tag">A</span>
        <input class="mat-num" type="number" step="0.01" value="${+c.rgba[3].toFixed(3)}" oninput="matAlpha(${i},this.value)">
      </div>`;
    });
  }
  if (m.scalars.length) {
    h += `<div class="mat-section">Scalars</div>`;
    m.scalars.forEach((s, i) => {
      h += `<div class="mat-row">
        <label title="${s.name}">${s.name}</label>
        <input type="range" id="msr${i}" min="${Math.min(0, s.orig)}" max="${s.max}" step="${s.max / 1000}" value="${s.value}" oninput="matScalar(${i},this.value,1)">
        <input class="mat-num wide" id="msn${i}" type="number" step="any" value="${s.value}" oninput="matScalar(${i},this.value,0)">
      </div>`;
    });
  }
  if (!m.colors.length && !m.scalars.length)
    h = `<div class="mat-empty">This material exposes no editable color or scalar parameters.</div>`;
  document.getElementById("mat-body").innerHTML = h;
}

function matColor(i, hex) {
  const c = matEditor.colors[i], n = Math.max(c.inten, 1e-6);
  c.rgba[0] = parseInt(hex.substr(1, 2), 16) / 255 * n;
  c.rgba[1] = parseInt(hex.substr(3, 2), 16) / 255 * n;
  c.rgba[2] = parseInt(hex.substr(5, 2), 16) / 255 * n;
  dyeRefresh();
}
function matInten(i, v, fromRange) {
  const c = matEditor.colors[i], o = Math.max(c.inten, 1e-6), nv = parseFloat(v) || 0;
  c.rgba[0] = c.rgba[0] / o * nv; c.rgba[1] = c.rgba[1] / o * nv; c.rgba[2] = c.rgba[2] / o * nv; c.inten = nv;
  const other = document.getElementById((fromRange ? "min" : "mir") + i); if (other) other.value = v;
  dyeRefresh();
}
function matAlpha(i, v) { matEditor.colors[i].rgba[3] = parseFloat(v) || 0; dyeRefresh(); }
function matScalar(i, v, fromRange) {
  matEditor.scalars[i].value = parseFloat(v) || 0;
  const other = document.getElementById((fromRange ? "msn" : "msr") + i); if (other) other.value = v;
}

async function saveMaterial() {
  if (!matEditor) return;
  const colors = {}, scalars = {};
  matEditor.colors.forEach(c => { colors[c.name] = [c.rgba[0], c.rgba[1], c.rgba[2], c.rgba[3]]; });
  matEditor.scalars.forEach(s => { scalars[s.name] = s.value; });
  document.getElementById("mat-status").textContent = "Saving…";
  try {
    const res = await api("/api/material_save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: matEditor.game_rel, colors, scalars }),
    });
    if (res.ok) {
      toast(`Saved: ${matEditor.name}`, "success");
      loadSidebar();
      closeMaterialEditor();
    } else {
      document.getElementById("mat-status").textContent = "Error: " + (res.error || "save failed");
    }
  } catch (e) { document.getElementById("mat-status").textContent = "Error: " + e.message; }
}

async function resetMaterial() {
  if (!matEditor) return;
  document.getElementById("mat-status").textContent = "Resetting…";
  try {
    const res = await api("/api/material_reset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: matEditor.game_rel }),
    });
    if (res.ok) {
      matEditor.colors = _seedColors(res.colors); matEditor.scalars = _seedScalars(res.scalars);
      renderMatEditor();
      document.getElementById("mat-status").textContent = "Reset to vanilla.";
      toast(`Reset: ${matEditor.name}`, "info");
    } else { document.getElementById("mat-status").textContent = "Error: " + (res.error || "reset failed"); }
  } catch (e) { document.getElementById("mat-status").textContent = "Error: " + e.message; }
}

function closeMaterialEditor() { document.getElementById("material-overlay").classList.remove("active"); matEditor = null; }

document.getElementById("mat-save").addEventListener("click", saveMaterial);
document.getElementById("mat-reset").addEventListener("click", resetMaterial);
document.getElementById("mat-close").addEventListener("click", closeMaterialEditor);
document.getElementById("material-overlay").addEventListener("click", e => {
  if (e.target.id === "material-overlay") closeMaterialEditor();
});

// ── curve editor (CurveLinearColor R/G/B/A key values) ────────────────────────
let curveEditor = null;
const CURVE_CH = ["R", "G", "B", "A"];

function _c01(v) { return Math.min(1, Math.max(0, v)); }
function _curveGradCss(stops) {
  if (!stops || !stops.length) return "#222";
  const t0 = stops[0].time, t1 = stops[stops.length - 1].time, span = (t1 - t0) || 1;
  const parts = stops.map(s => {
    const [r, g, b] = s.rgba;
    const pct = (((s.time - t0) / span) * 100).toFixed(1);
    return `rgb(${Math.round(_c01(r) * 255)},${Math.round(_c01(g) * 255)},${Math.round(_c01(b) * 255)}) ${pct}%`;
  });
  return `linear-gradient(to right, ${parts.join(", ")})`;
}
function _evalCh(keys, t) {
  if (!keys || !keys.length) return 0;
  if (t <= keys[0].time) return keys[0].value;
  if (t >= keys[keys.length - 1].time) return keys[keys.length - 1].value;
  for (let i = 1; i < keys.length; i++) {
    const a = keys[i - 1], b = keys[i];
    if (t <= b.time) { const sp = b.time - a.time; return a.value + (b.value - a.value) * (sp ? (t - a.time) / sp : 0); }
  }
  return keys[keys.length - 1].value;
}
function _resampleStops(channels) {
  const ts = new Set();
  const sorted = {};
  for (const ch of CURVE_CH) { sorted[ch] = [...(channels[ch] || [])].sort((a, b) => a.time - b.time); sorted[ch].forEach(k => ts.add(k.time)); }
  return [...ts].sort((a, b) => a - b).map(t => ({ time: t, rgba: CURVE_CH.map(ch => _evalCh(sorted[ch], t)) }));
}

async function openCurveEditor(item) {
  const ov = document.getElementById("curve-overlay");
  document.getElementById("curve-title").textContent = item.name;
  document.getElementById("curve-sub").textContent = item.game_rel || "";
  document.getElementById("curve-status").textContent = "";
  document.getElementById("curve-body").innerHTML = '<div class="spinner" style="margin:44px auto"></div>';
  ov.classList.add("active");
  let res;
  try { res = await api(`/api/curve_params?game_rel=${encodeURIComponent(item.game_rel)}`); }
  catch (e) { document.getElementById("curve-body").innerHTML = `<div class="mat-empty">Error: ${e.message}</div>`; return; }
  if (!res.ok) { document.getElementById("curve-body").innerHTML = `<div class="mat-empty">${res.error || "failed to read curve"}</div>`; return; }
  curveEditor = { game_rel: item.game_rel, name: item.name, channels: res.channels || {}, stops: res.stops || [], dirty: {} };
  renderCurveEditor();
  loadSidebar();
}

const CURVE_INTERP = ["RCIM_Linear", "RCIM_Cubic", "RCIM_Constant"];

function renderCurveEditor() {
  const c = curveEditor; if (!c) return;
  let h = `<div class="curve-preview" id="curve-grad"></div>`;
  for (const ch of CURVE_CH) {
    const keys = c.channels[ch] || (c.channels[ch] = []);
    h += `<div class="mat-section" style="display:flex;align-items:center;gap:8px">
      <span>${ch} channel — ${keys.length} key${keys.length !== 1 ? "s" : ""}</span>
      <button class="btn" style="padding:2px 9px;font-size:11px" onclick="curveAddKey('${ch}')">+ key</button></div>`;
    keys.forEach((k, i) => {
      const cubic = (k.interp || "RCIM_Linear") === "RCIM_Cubic";
      h += `<div style="display:flex;gap:6px;align-items:center;padding:3px 0;flex-wrap:wrap;font-size:12px">
        <input type="number" step="any" title="time" style="width:72px" value="${k.time}" oninput="curveKeyField('${ch}',${i},'time',this.value)">
        <input type="number" step="any" title="value" style="width:88px" value="${k.value}" oninput="curveKeyField('${ch}',${i},'value',this.value)">
        <select title="interpolation" onchange="curveKeyField('${ch}',${i},'interp',this.value)">
          ${CURVE_INTERP.map(m => `<option value="${m}" ${m === (k.interp || "RCIM_Linear") ? "selected" : ""}>${m.slice(5)}</option>`).join("")}
        </select>
        ${cubic ? `<input type="number" step="any" title="arrive tangent" style="width:62px" value="${k.arriveTangent || 0}" oninput="curveKeyField('${ch}',${i},'arriveTangent',this.value)">
        <input type="number" step="any" title="arrive tangent WEIGHT" style="width:58px" value="${k.arriveTangentWeight || 0}" oninput="curveKeyField('${ch}',${i},'arriveTangentWeight',this.value)">
        <input type="number" step="any" title="leave tangent" style="width:62px" value="${k.leaveTangent || 0}" oninput="curveKeyField('${ch}',${i},'leaveTangent',this.value)">
        <input type="number" step="any" title="leave tangent WEIGHT" style="width:58px" value="${k.leaveTangentWeight || 0}" oninput="curveKeyField('${ch}',${i},'leaveTangentWeight',this.value)">` : ""}
        <button class="sb-clear" title="remove key" onclick="curveRemoveKey('${ch}',${i})"><i data-lucide="x" size="13"></i></button>
      </div>`;
    });
  }
  document.getElementById("curve-body").innerHTML = h;
  lucide.createIcons({ nodes: [document.getElementById("curve-body")] });
  const g = document.getElementById("curve-grad"); if (g) g.style.background = _curveGradCss(c.stops);
}

function _curveTouch(ch) {
  curveEditor.dirty[ch] = true;
  curveEditor.stops = _resampleStops(curveEditor.channels);
  const g = document.getElementById("curve-grad"); if (g) g.style.background = _curveGradCss(curveEditor.stops);
}

function curveKeyField(ch, i, field, v) {
  const c = curveEditor; if (!c || !c.channels[ch] || !c.channels[ch][i]) return;
  if (field === "interp") { c.channels[ch][i].interp = v; _curveTouch(ch); renderCurveEditor(); return; }
  const val = parseFloat(v); if (isNaN(val)) return;
  c.channels[ch][i][field] = val;
  _curveTouch(ch);
}

function curveAddKey(ch) {
  const c = curveEditor; const keys = c.channels[ch] || (c.channels[ch] = []);
  const t = keys.length ? Math.min(1, (+keys[keys.length - 1].time || 0) + 0.1) : 0;
  keys.push({ time: t, value: 0, interp: "RCIM_Linear", arriveTangent: 0, arriveTangentWeight: 0, leaveTangent: 0, leaveTangentWeight: 0 });
  _curveTouch(ch); renderCurveEditor();
}

function curveRemoveKey(ch, i) {
  const c = curveEditor; if (!c.channels[ch]) return;
  c.channels[ch].splice(i, 1); _curveTouch(ch); renderCurveEditor();
}

async function saveCurve() {
  const c = curveEditor; if (!c) return;
  const edits = {};
  for (const ch of Object.keys(c.dirty)) if (c.dirty[ch]) edits[ch] = c.channels[ch];   // full key list per changed channel
  if (!Object.keys(edits).length) { document.getElementById("curve-status").textContent = "No changes to save."; return; }
  document.getElementById("curve-status").textContent = "Saving…";
  try {
    const res = await api("/api/curve_save", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: c.game_rel, edits }) });
    if (res.ok) { toast(`Saved: ${c.name}`, "success"); loadSidebar(); closeCurveEditor(); }
    else document.getElementById("curve-status").textContent = "Error: " + (res.error || "save failed");
  } catch (e) { document.getElementById("curve-status").textContent = "Error: " + e.message; }
}

async function resetCurve() {
  const c = curveEditor; if (!c) return;
  document.getElementById("curve-status").textContent = "Resetting…";
  try {
    const res = await api("/api/curve_reset", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: c.game_rel }) });
    if (res.ok) { c.channels = res.channels || {}; c.stops = res.stops || []; c.dirty = {}; renderCurveEditor();
      document.getElementById("curve-status").textContent = "Reset to vanilla."; toast(`Reset: ${c.name}`, "info"); }
    else document.getElementById("curve-status").textContent = "Error: " + (res.error || "reset failed");
  } catch (e) { document.getElementById("curve-status").textContent = "Error: " + e.message; }
}

function closeCurveEditor() { document.getElementById("curve-overlay").classList.remove("active"); curveEditor = null; }

document.getElementById("curve-save").addEventListener("click", saveCurve);
document.getElementById("curve-reset").addEventListener("click", resetCurve);
document.getElementById("curve-close").addEventListener("click", closeCurveEditor);
document.getElementById("curve-overlay").addEventListener("click", e => {
  if (e.target.id === "curve-overlay") closeCurveEditor();
});

// ── Niagara VFX editor (color-curve group recolor) ────────────────────────────
let vfxEditor = null;

function _vfxInten(g) {                       // HDR curves keep magnitude via a group intensity
  let m = 1e-6;
  for (const s of g.stops) m = Math.max(m, s[0], s[1], s[2]);
  return g.is_hdr ? Math.max(m, 1) : 1;
}
function _vhex(c) { return ("0" + Math.round(Math.min(255, Math.max(0, c * 255))).toString(16)).slice(-2); }
function _vStopHex(s, inten) { const n = Math.max(inten, 1e-6); return "#" + _vhex(s[0] / n) + _vhex(s[1] / n) + _vhex(s[2] / n); }
function _vfxGradCss(g) {
  const n = g.stops.length; if (!n) return "#222";
  const inten = Math.max(g.inten, 1e-6);
  const parts = g.stops.map((s, i) => {
    const a = s.length > 3 ? Math.min(1, Math.max(0, s[3])) : 1;
    return `rgba(${Math.round(Math.min(1, s[0] / inten) * 255)},${Math.round(Math.min(1, s[1] / inten) * 255)},${Math.round(Math.min(1, s[2] / inten) * 255)},${a.toFixed(3)}) ${(i / (n - 1) * 100).toFixed(1)}%`;
  });
  // checkerboard underlay so alpha reads visually
  return `linear-gradient(to right, ${parts.join(", ")}), repeating-conic-gradient(#5a5a5a 0% 25%, #888 0% 50%) 0 0 / 14px 14px`;
}

async function openVfxEditor(item) {
  const ov = document.getElementById("vfx-overlay");
  document.getElementById("vfx-title").textContent = item.name;
  document.getElementById("vfx-sub").textContent = item.game_rel || "";
  document.getElementById("vfx-status").textContent = "";
  document.getElementById("vfx-body").innerHTML = '<div class="spinner" style="margin:44px auto"></div>';
  ov.classList.add("active");
  let res;
  try { res = await api(`/api/vfx_params?game_rel=${encodeURIComponent(item.game_rel)}`); }
  catch (e) { document.getElementById("vfx-body").innerHTML = `<div class="mat-empty">Error: ${e.message}</div>`; return; }
  if (!res.ok) { document.getElementById("vfx-body").innerHTML = `<div class="mat-empty">${res.error || "failed to read VFX"}</div>`; return; }
  vfxEditor = { game_rel: item.game_rel, name: item.name,
                groups: (res.groups || []).map(g => ({ ...g, inten: _vfxInten(g) })) };
  renderVfxEditor();
  loadSidebar();
}

const _VFX_CHAN_COLS = ["#e05a5a", "#5ae06a", "#5a8ae0", "#cccccc"];
function _vfxSpark(g) {                                    // SVG line preview for scalar/vector curves
  const W = 300, H = 56, pad = 5, n = g.stops.length; if (!n) return "";
  let mn = Infinity, mx = -Infinity;
  g.stops.forEach(s => { for (let c = 0; c < g.channels; c++) { mn = Math.min(mn, s[c]); mx = Math.max(mx, s[c]); } });
  if (!isFinite(mn)) { mn = 0; mx = 1; }
  if (mx - mn < 1e-6) { mx = mn + 1; mn -= 0; }
  const x = i => pad + (n === 1 ? 0 : i / (n - 1) * (W - 2 * pad));
  const y = val => H - pad - (val - mn) / (mx - mn) * (H - 2 * pad);
  let paths = "";
  for (let c = 0; c < g.channels; c++) {
    const pts = g.stops.map((s, i) => `${x(i).toFixed(1)},${y(s[c]).toFixed(1)}`).join(" ");
    paths += `<polyline points="${pts}" fill="none" stroke="${_VFX_CHAN_COLS[c % 4]}" stroke-width="1.5"/>`;
  }
  return `<svg class="vfx-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${paths}` +
         `<text x="4" y="11" fill="#888" font-size="9">${mn.toFixed(2)} … ${mx.toFixed(2)}</text></svg>`;
}

function renderVfxEditor() {
  const v = vfxEditor; if (!v) return;
  if (!v.groups.length) { document.getElementById("vfx-body").innerHTML = `<div class="mat-empty">This VFX exposes no editable curves.</div>`; return; }
  let h = "";
  v.groups.forEach((g, gi) => {
    const owners = g.label ? g.label : `${g.export_indices.length} emitter${g.export_indices.length !== 1 ? "s" : ""}`;
    const extra  = g.export_indices.length > 1 ? ` ×${g.export_indices.length}` : "";
    h += `<div class="mat-section">${g.kind} curve — ${owners}${extra}${g.is_hdr ? " · HDR" : ""}</div>`;
    if (g.channels === 4) {                               // color / emission: gradient + swatches + alpha
      h += `<div class="curve-preview" id="vgrad${gi}"></div>`;
      if (g.is_hdr) {
        h += `<div class="mat-row"><label>intensity</label>
          <input type="range" id="vint${gi}" min="0" max="20" step="0.1" value="${Math.min(g.inten, 20)}" oninput="vfxInten(${gi},this.value,1)">
          <input class="mat-num" id="vinn${gi}" type="number" step="0.1" value="${+g.inten.toFixed(2)}" oninput="vfxInten(${gi},this.value,0)"></div>`;
      }
      h += `<div class="vfx-stops">`;
      g.stops.forEach((s, si) => {
        const a = s.length > 3 ? s[3] : 1;
        h += `<div class="vfx-stop">
          <input type="color" value="${_vStopHex(s, g.inten)}" oninput="vfxStop(${gi},${si},this.value)">
          <input class="vfx-alpha" type="number" min="0" max="1" step="0.05" value="${+(+a).toFixed(2)}" title="alpha (opacity)" oninput="vfxAlpha(${gi},${si},this.value)">
        </div>`;
      });
      h += `</div>`;
    } else {                                              // scalar / vector: line preview + value inputs
      h += `<div class="vfx-spark-wrap" id="vspark${gi}">${_vfxSpark(g)}</div>`;
      h += `<div class="vfx-vals">`;
      g.stops.forEach((s, si) => {
        h += `<div class="vfx-val">`;
        for (let c = 0; c < g.channels; c++)
          h += `<input type="number" step="any" value="${s[c]}" oninput="vfxVal(${gi},${si},${c},this.value)">`;
        h += `</div>`;
      });
      h += `</div>`;
    }
  });
  document.getElementById("vfx-body").innerHTML = h;
  v.groups.forEach((g, gi) => {
    if (g.channels === 4) { const el = document.getElementById("vgrad" + gi); if (el) el.style.background = _vfxGradCss(g); }
  });
}

function vfxVal(gi, si, ci, val) {
  const g = vfxEditor.groups[gi], x = parseFloat(val);
  if (isNaN(x)) return;
  g.stops[si][ci] = x;
  const el = document.getElementById("vspark" + gi); if (el) el.innerHTML = _vfxSpark(g);
}

function vfxStop(gi, si, hex) {
  const g = vfxEditor.groups[gi], n = Math.max(g.inten, 1e-6), s = g.stops[si];
  s[0] = parseInt(hex.substr(1, 2), 16) / 255 * n;
  s[1] = parseInt(hex.substr(3, 2), 16) / 255 * n;
  s[2] = parseInt(hex.substr(5, 2), 16) / 255 * n;
  const el = document.getElementById("vgrad" + gi); if (el) el.style.background = _vfxGradCss(g);
}
function vfxAlpha(gi, si, v) {
  const g = vfxEditor.groups[gi], s = g.stops[si], a = parseFloat(v);
  if (isNaN(a)) return;
  while (s.length < 4) s.push(1);
  s[3] = Math.min(1, Math.max(0, a));
  const el = document.getElementById("vgrad" + gi); if (el) el.style.background = _vfxGradCss(g);
}
function vfxInten(gi, val, fromRange) {
  const g = vfxEditor.groups[gi], o = Math.max(g.inten, 1e-6), nv = parseFloat(val) || 0, k = nv / o;
  g.stops.forEach(s => { s[0] *= k; s[1] *= k; s[2] *= k; });
  g.inten = nv;
  const other = document.getElementById((fromRange ? "vinn" : "vint") + gi); if (other) other.value = val;
  const el = document.getElementById("vgrad" + gi); if (el) el.style.background = _vfxGradCss(g);
}

async function saveVfx() {
  const v = vfxEditor; if (!v) return;
  document.getElementById("vfx-status").textContent = "Saving…";
  const groups = v.groups.map(g => ({ export_indices: g.export_indices, stops: g.stops,
                                      sample_count: g.sample_count, channels: g.channels }));
  try {
    const res = await api("/api/vfx_save", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: v.game_rel, groups }) });
    if (res.ok) { toast(`Saved: ${v.name}`, "success"); loadSidebar(); closeVfxEditor(); }
    else document.getElementById("vfx-status").textContent = "Error: " + (res.error || "save failed");
  } catch (e) { document.getElementById("vfx-status").textContent = "Error: " + e.message; }
}
async function resetVfx() {
  const v = vfxEditor; if (!v) return;
  document.getElementById("vfx-status").textContent = "Resetting…";
  try {
    const res = await api("/api/vfx_reset", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: v.game_rel }) });
    if (res.ok) { v.groups = (res.groups || []).map(g => ({ ...g, inten: _vfxInten(g) })); renderVfxEditor();
      document.getElementById("vfx-status").textContent = "Reset to vanilla."; toast(`Reset: ${v.name}`, "info"); }
    else document.getElementById("vfx-status").textContent = "Error: " + (res.error || "reset failed");
  } catch (e) { document.getElementById("vfx-status").textContent = "Error: " + e.message; }
}
function closeVfxEditor() { document.getElementById("vfx-overlay").classList.remove("active"); vfxEditor = null; }

document.getElementById("vfx-save").addEventListener("click", saveVfx);
document.getElementById("vfx-reset").addEventListener("click", resetVfx);
document.getElementById("vfx-close").addEventListener("click", closeVfxEditor);
document.getElementById("vfx-overlay").addEventListener("click", e => {
  if (e.target.id === "vfx-overlay") closeVfxEditor();
});

// ── import all ────────────────────────────────────────────────────────────────
function _shownTextures() {
  const q = document.getElementById("search-input").value.trim().toLowerCase();
  return allItems.filter(i => i.type === "asset" && i.file_type === "texture"
    && (!q || (i.name || i.label || "").toLowerCase().includes(q)));
}

document.getElementById("view3d-fab").addEventListener("click", () => {
  const sid = skinIdFromPath(nav.path);
  if (!sid) { toast("Open a skin folder first", "info"); return; }
  if (window.AtelierViewport) window.AtelierViewport.open(sid, `3D Preview — ${sid}`);
  else toast("3D viewport failed to load", "warning");
});

document.getElementById("import-all-btn").addEventListener("click", () => {
  const shown   = _shownTextures();
  const pending = shown.filter(i => !i.imported);
  const q       = document.getElementById("search-input").value.trim();
  if (!pending.length) { toast(q ? "All shown textures already edited" : "All textures already edited", "success"); return; }
  const sid = skinIdFromPath(nav.path);
  pendingImportAll = pending;
  document.getElementById("confirm-all-msg").textContent =
    `Extract and decode ${pending.length} texture${pending.length !== 1 ? "s" : ""}`
    + (pending.length < shown.length ? ` (${shown.length - pending.length} already edited)` : "")
    + (q ? ` matching "${q}"` : "")
    + (sid ? ` from "${sid}"` : "") + "?";
  document.getElementById("confirm-all-overlay").classList.add("active");
});

document.getElementById("confirm-all-cancel").addEventListener("click", () => {
  document.getElementById("confirm-all-overlay").classList.remove("active");
});

document.getElementById("confirm-all-ok").addEventListener("click", async () => {
  document.getElementById("confirm-all-overlay").classList.remove("active");
  const textures = pendingImportAll || [];
  pendingImportAll = null;
  if (!textures.length) return;

  const sid   = skinIdFromPath(nav.path);
  const items = textures.map(t => ({
    skin_id:  sid,
    rel_path: t.rel_path,
    game_rel: t.game_rel,
    name:     t.name || t.label,
  }));

  importing = true;
  showProgress(0, items.length);
  document.getElementById("prog-overlay").classList.add("active");

  const res = await api("/api/import_all", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!res.ok) {
    document.getElementById("prog-overlay").classList.remove("active");
    importing = false;
    toast(`Edit failed: ${res.error}`, "warning");
  }
});

function showProgress(current, total) {
  document.getElementById("prog-counter").textContent = `Downloading ${current} / ${total} assets…`;
}

// ── prevent accidental close during import ────────────────────────────────────
window.addEventListener("beforeunload", e => {
  if (importing) {
    e.preventDefault();
    e.returnValue = "An edit is in progress. Closing may leave assets incomplete.";
    return e.returnValue;
  }
});

// ── SSE ───────────────────────────────────────────────────────────────────────
function connectSSE() {
  const es = new EventSource("/api/events");
  es.addEventListener("message", e => {
    try {
      const d = JSON.parse(e.data);
      handleSSE(d);
    } catch {}
  });
  es.onerror = () => setTimeout(connectSSE, 3000);
}

function handleSSE(d) {
  if (d.usmap_updated) {
    const ov = document.getElementById("usmap-update-overlay");
    document.getElementById("usmap-update-name").textContent = d.name || "";
    ov.classList.add("active");
    lucide.createIcons({ nodes: [ov] });
    return;
  }
  if (d.toast) {
    toast(d.toast, d.toast_type || "info", 5000);
    return;
  }
  if (d.thumb_ready && d.game_rel) {
    const sel = `img[data-game-rel="${CSS.escape(d.game_rel)}"]`;
    document.querySelectorAll(sel).forEach(img => {
      img.src = `/api/thumb?game_rel=${encodeURIComponent(d.game_rel)}&_t=${Date.now()}`;
    });
    return;
  }
  if (d.file_changed) {
    const bust = `?token=${d.token}&gr=${encodeURIComponent(d.game_rel)}&t=${Date.now()}`;
    document.querySelectorAll(`img[data-token="${d.token}"]`).forEach(img => {
      img.src = `/api/preview${bust}`;
    });
    document.querySelectorAll(`#sidebar-list .sb-item[data-token="${d.token}"] .sb-thumb img`).forEach(img => {
      img.src = `/api/preview${bust}`;
    });
    if (!importing && !suppressedImportGameRels.has(d.game_rel) && Date.now() >= suppressChangeToastUntil) {
      toast("Asset edited", "warning", 4000);
    }
    return;
  }
  if (!d.done && importing) {
    showProgress(d.current, d.total);
    return;
  }
  if (d.done && importing) {
    importing = false;
    suppressChangeToastUntil = Date.now() + 2500;
    document.getElementById("prog-overlay").classList.remove("active");
    if (d.error) {
      toast(`Load failed: ${d.error}`, "warning", 8000);
    } else {
      toast(`Loaded ${d.current} texture${d.current !== 1 ? "s" : ""}`, "success");
    }
    setStatus("");
    loadSidebar();
    const gridArea   = document.getElementById("grid-area");
    const savedScroll = gridArea.scrollTop;
    renderGrid().then(() => { gridArea.scrollTop = savedScroll; }).catch(() => {});
  }
}

connectSSE();

// ── sidebar / export ──────────────────────────────────────────────────────────
async function loadSidebar() {
  const data = await api("/api/imported");
  data.forEach(item => {
    if (!sidebarData[item.token]) {
      sidebarData[item.token] = { ...item, selected: true };
    } else {
      Object.assign(sidebarData[item.token], item);
    }
  });
  const live = new Set(data.map(d => d.token));
  Object.keys(sidebarData).forEach(t => { if (!live.has(t)) delete sidebarData[t]; });
  renderSidebar();
}

function refreshSidebarEntry(game_rel, name, skin_id) {
  api("/api/imported").then(data => {
    data.forEach(item => {
      if (!sidebarData[item.token]) sidebarData[item.token] = { ...item, selected: true };
      else Object.assign(sidebarData[item.token], item);
    });
    renderSidebar();
  });
}

function sbSubLabel(item) {
  if (item.char_name || item.skin_id) {
    return `${item.char_name || item.skin_id} / ${item.skin_name || ""}`;
  }
  const parts = (item.game_rel || "").split("/").filter(Boolean);
  if (parts.length >= 2) return `…/${parts[parts.length - 2]}/${parts[parts.length - 1]}`;
  return parts.join("/") || item.game_rel || "";
}

function renderSidebar() {
  const list = document.getElementById("sidebar-list");
  list.innerHTML = "";
  const all = Object.values(sidebarData);
  if (!all.length) {
    list.innerHTML = '<div style="padding:20px 14px;font-size:12px;color:var(--muted)">No edited assets yet.</div>';
    updateInstallBtn();
    return;
  }
  const q     = document.getElementById("search-input").value.trim().toLowerCase();
  const items = q ? all.filter(i =>
        (i.name || "").toLowerCase().includes(q) ||
        (i.skin_name || "").toLowerCase().includes(q) ||
        (i.char_name || "").toLowerCase().includes(q)) : all;
  if (!items.length) {
    list.innerHTML = '<div style="padding:20px 14px;font-size:12px;color:var(--muted)">No edited assets match the search.</div>';
    updateInstallBtn();
    return;
  }
  items.forEach(item => {
    const el = document.createElement("div");
    el.className = "sb-item" + (item.selected ? " selected" : "");
    el.dataset.token = item.token;
    const h = handlerFor(item.file_type);
    el.innerHTML = `
      <button class="sb-clear" title="Delete"><i data-lucide="x" size="12"></i></button>
      <div class="sb-thumb">
        ${h.preview
          ? `<img src="/api/preview?token=${item.token}&game_rel=${encodeURIComponent(item.game_rel)}"
               alt="" onerror="this.style.opacity='.3'">`
          : `<i data-lucide="${h.icon || 'file-question'}" size="32" class="card-icon ${assetIconCls(item.file_type)}"></i>`}
      </div>
      <div class="sb-info">
        <div class="sb-name">${item.name}</div>
        <div class="sb-sub">${sbSubLabel(item)}</div>
      </div>
      <div class="sb-check">${item.selected ? '<i data-lucide="check" size="12"></i>' : ""}</div>
    `;
    el.querySelector(".sb-clear").addEventListener("click", e => {
      e.stopPropagation();
      clearImported(item.token);
    });
    el.querySelector(".sb-check").addEventListener("click", e => {
      e.stopPropagation();
      item.selected = !item.selected;
      renderSidebar();
    });
    el.addEventListener("click", () => handleImportedFileAction(item));
    el.addEventListener("contextmenu", e => _ctxShow(e, _ctxItemsSidebar(item)));
    list.appendChild(el);
  });
  lucide.createIcons({ nodes: [list] });
  updateInstallBtn();
}

function toggleSelectAll() {
  const all = Object.values(sidebarData);
  if (!all.length) return;
  const sel = all.filter(i => i.selected).length;
  const selectAll = sel === 0 || sel < all.length;
  all.forEach(i => { i.selected = selectAll; });
  renderSidebar();
}

function _modsTopFolderName() {
  const parts = (_modsFolderPath || "").replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "~mods";
}

function _syncToggleRow(id) {
  const cb = document.getElementById(id);
  cb.closest(".toggle-row").classList.toggle("on", cb.checked);
}

function updateInstallBtn() {
  const sel = Object.values(sidebarData).filter(i => i.selected).length;
  const badge = document.getElementById("sel-count");
  badge.textContent = `${sel}`;
  badge.classList.toggle("active", sel > 0);
  document.getElementById("install-btn").disabled = sel === 0;

  const copyRow = document.getElementById("toggle-copy-row");
  const copyCb  = document.getElementById("toggle-copy");
  copyRow.classList.toggle("disabled", !_modsFolderSet);
  copyCb.disabled = !_modsFolderSet;
  if (!_modsFolderSet) copyCb.checked = false;
  document.getElementById("toggle-copy-label").textContent = `Copy to ${_modsTopFolderName()}/`;
  copyRow.title = _modsFolderSet ? "" : "Set a mods folder first (Menu → Settings)";
  _syncToggleRow("toggle-copy");

  const pwRow = document.getElementById("toggle-password-row");
  const pwCb  = document.getElementById("toggle-password");
  const hasPw = !!_protectionPassword;
  pwRow.classList.toggle("disabled", !hasPw);
  pwCb.disabled = !hasPw;
  if (!hasPw) pwCb.checked = false;
  pwRow.title = hasPw ? "Encrypt the mod with the Protection Password set in Settings"
                      : "Set a Protection Password first (Menu → Settings)";
  _syncToggleRow("toggle-password");
}

document.getElementById("toggle-copy-row").addEventListener("click", e => {
  if (document.getElementById("toggle-copy").disabled) { e.preventDefault(); openPaths(); }
});
document.getElementById("toggle-password-row").addEventListener("click", e => {
  if (document.getElementById("toggle-password").disabled) { e.preventDefault(); openPaths(); }
});
document.getElementById("toggle-copy").addEventListener("change", () => _syncToggleRow("toggle-copy"));
document.getElementById("toggle-password").addEventListener("change", () => _syncToggleRow("toggle-password"));

async function _runInstall(modName, exportable, skipped, copyToMods, password) {
  document.getElementById("install-btn").disabled = true;
  setStatus(`Installing ${exportable.length} asset${exportable.length !== 1 ? "s" : ""}…`);
  const t = toastSpinner(`Installing ${modName}…`);
  try {
    const res = await api("/api/install_mod", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mod_name: modName,
        items: exportable.map(i => i.game_rel),
        password,
        copy_to_mods: copyToMods,
      }),
    });
    t.remove();
    if (res.ok) {
      toast(`Installed: ${modName}_9999999_P` + (skipped ? ` (${skipped} skipped)` : ""), "success", 5000);
      setStatus(res.installed_dir ? `Installed → ${res.installed_dir}` : `Exported → ${res.pak_path || ""}`);
    } else if (res.need_mods_folder) {
      _modsFolderSet = false;
      toast("No mods folder set — opening Settings…", "warning");
      openPaths();
    } else {
      toast(`Install failed: ${res.error || "unknown error"}`, "warning");
      setStatus("");
    }
  } catch (e) {
    t.remove();
    toast(`Error: ${e.message}`, "warning"); setStatus("");
  } finally {
    updateInstallBtn();
  }
}

async function doInstallMod() {
  const selected = Object.values(sidebarData).filter(i => i.selected);
  if (!selected.length) return;
  const modName = document.getElementById("mod-name-input").value.trim() || _activeProjectName || "ModFilename";
  const exportable = selected.filter(i => ["texture", "material", "curve", "vfx", "world", "text", "mesh"].includes(i.file_type || ""));
  const skipped    = selected.length - exportable.length;
  if (!exportable.length) { toast("Nothing exportable selected", "info"); return; }

  const copyToMods = document.getElementById("toggle-copy").checked && _modsFolderSet;
  if (document.getElementById("toggle-copy").checked && !_modsFolderSet) {
    toast("Set a mods folder first — opening Settings…", "info");
    openPaths();
    return;
  }
  const passwordProtect = document.getElementById("toggle-password").checked && !!_protectionPassword;
  const password = passwordProtect ? _protectionPassword : "";

  let conflict = null;
  try {
    const q = `/api/check_mod_conflict?mod_name=${encodeURIComponent(modName)}&copy_to_mods=${copyToMods ? "1" : "0"}`;
    conflict = await (await fetch(q)).json();
  } catch (_) {}

  const proceed = () => _runInstall(modName, exportable, skipped, copyToMods, password);

  if (conflict && (conflict.default || conflict.mods)) {
    const locs = [];
    if (conflict.default) locs.push("the export folder");
    if (conflict.mods)    locs.push("your mods folder");
    document.getElementById("confirm-overwrite-msg").textContent =
      `A mod named "${modName}" already exists in ${locs.join(" and ")}. Installing will replace it.`;
    _pendingOverwriteConfirm = proceed;
    document.getElementById("confirm-overwrite-overlay").classList.add("active");
  } else {
    await proceed();
  }
}

document.getElementById("confirm-overwrite-cancel").addEventListener("click", () => {
  document.getElementById("confirm-overwrite-overlay").classList.remove("active");
  _pendingOverwriteConfirm = null;
});
document.getElementById("confirm-overwrite-ok").addEventListener("click", async () => {
  document.getElementById("confirm-overwrite-overlay").classList.remove("active");
  const fn = _pendingOverwriteConfirm;
  _pendingOverwriteConfirm = null;
  if (fn) await fn();
});

document.getElementById("install-btn").addEventListener("click", doInstallMod);
document.getElementById("sel-count").addEventListener("click", toggleSelectAll);

// ── clear individual / clear all ──────────────────────────────────────────────
function clearImported(token) {
  const item = sidebarData[token];
  if (!item) return;
  pendingClear = item;
  const ft   = item.file_type || "asset";
  const kind = ft.charAt(0).toUpperCase() + ft.slice(1);
  document.getElementById("confirm-clear-title").textContent = `Delete ${kind}?`;
  document.getElementById("confirm-clear-msg").textContent =
    `Delete "${item.name}" from local assets? This will remove the imported file.`;
  document.getElementById("confirm-clear-overlay").classList.add("active");
}

document.getElementById("confirm-clear-cancel").addEventListener("click", () => {
  document.getElementById("confirm-clear-overlay").classList.remove("active");
  pendingClear = null;
});

document.getElementById("confirm-clear-ok").addEventListener("click", async () => {
  document.getElementById("confirm-clear-overlay").classList.remove("active");
  if (!pendingClear) return;
  const item = pendingClear; pendingClear = null;
  try {
    const res = await api("/api/delete_imported", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: item.game_rel }),
    });
    if (res.ok) {
      delete sidebarData[item.token];
      renderSidebar();
      toast(`Deleted: ${item.name}`, "warning", 3000);
      renderGrid().catch(() => {});
    } else {
      toast(`Delete failed: ${res.error}`, "warning");
    }
  } catch (e) {
    toast(`Error: ${e.message}`, "warning");
  }
});

document.getElementById("clear-all-btn").addEventListener("click", () => {
  const count = Object.keys(sidebarData).length;
  if (!count) { toast("No edited assets to clear", "info"); return; }
  document.getElementById("confirm-clear-all-msg").textContent =
    `All ${count} edited asset${count !== 1 ? "s" : ""} will be permanently deleted from local assets.`;
  document.getElementById("confirm-clear-all-overlay").classList.add("active");
});

document.getElementById("confirm-clear-all-cancel").addEventListener("click", () => {
  document.getElementById("confirm-clear-all-overlay").classList.remove("active");
});

document.getElementById("confirm-clear-all-ok").addEventListener("click", async () => {
  document.getElementById("confirm-clear-all-overlay").classList.remove("active");
  try {
    const res = await api("/api/delete_all_imported", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (res.ok) {
      sidebarData = {};
      renderSidebar();
      toast(`Deleted ${res.deleted} edited asset${res.deleted !== 1 ? "s" : ""}`, "warning", 4000);
      renderGrid().catch(() => {});
    } else {
      toast(`Delete failed: ${res.error}`, "warning");
    }
  } catch (e) {
    toast(`Error: ${e.message}`, "warning");
  }
});

// ── prereq check ─────────────────────────────────────────────────────────────
async function checkPrereqs() {
  try {
    const res = await api("/api/prereqs");
    if (!res.issues || !res.issues.length) return;
    res.issues.forEach(issue => {
      const isError = issue.level === "error";
      toast(issue.message, isError ? "warning" : "info", isError ? 10000 : 6000);
    });
  } catch (e) {}
}

// ── first-run setup ───────────────────────────────────────────────────────────
async function _fetchAesKeyValue() {
  try {
    const r = await fetch("https://raw.githubusercontent.com/SpaceDepot/rivals-depot/refs/heads/main/AES.json");
    if (!r.ok) return null;
    const data = await r.json();
    const text = String(data.mainKey || "").trim();
    if (!text) return null;
    return /^0x/i.test(text) ? text : "0x" + text;
  } catch (_) { return null; }
}

async function _fetchUsmapPath() {
  try {
    const res = await api("/api/download_usmap", { method: "POST" });
    return (res.ok && res.path) ? res.path : null;
  } catch (_) { return null; }
}

function _setSetupLoading(on) {
  document.getElementById("setup-loading").classList.toggle("active", on);
}

async function checkSetup() {
  document.getElementById("setup-overlay").classList.add("active");
  _setSetupLoading(true);
  try {
    const [statusRes, aes, usmapPath] = await Promise.all([
      api("/api/setup_status"),
      _fetchAesKeyValue(),
      _fetchUsmapPath(),
    ]);
    _modsFolderSet     = !!(statusRes.mods_prefill);
    _modsFolderPath    = statusRes.mods_prefill || "";
    _protectionPassword = statusRes.password_prefill || "";
    document.getElementById("toggle-copy").checked = _modsFolderSet;
    if (statusRes.configured) {
      document.getElementById("setup-overlay").classList.remove("active");
      return false;
    }
    _pathsMode = false;
    _applySetupMode();
    document.getElementById("setup-path").value  = statusRes.paks_prefill  || "";
    document.getElementById("setup-aes").value   = aes  || statusRes.aes_prefill  || "";
    document.getElementById("setup-usmap").value = usmapPath || statusRes.usmap_prefill || "";
    _setSetupLoading(false);
    await validateSetup();
    return true;
  } catch (e) {
    _setSetupLoading(false);
    return false;
  }
}

function _applySetupMode() {
  const paths = _pathsMode;
  document.getElementById("setup-title").textContent = paths ? "Settings" : "Initial Configuration";
  document.getElementById("setup-mods-row").style.display     = paths ? "" : "none";
  document.getElementById("setup-export-section").style.display = paths ? "" : "none";
  document.getElementById("setup-password-row").style.display = paths ? "" : "none";
  document.getElementById("setup-cancel").style.display   = paths ? "" : "none";
  document.getElementById("setup-save-label").textContent = paths ? "Save" : "Save & Continue";
}

async function openPaths() {
  _pathsMode = true;
  _applySetupMode();
  document.getElementById("setup-overlay").classList.add("active");
  _setSetupLoading(true);
  try {
    const [statusRes, aes, usmapPath] = await Promise.all([
      api("/api/setup_status"), _fetchAesKeyValue(), _fetchUsmapPath(),
    ]);
    _modsFolderSet      = !!(statusRes.mods_prefill);
    _modsFolderPath     = statusRes.mods_prefill || "";
    _protectionPassword = statusRes.password_prefill || "";
    document.getElementById("setup-path").value     = statusRes.paks_prefill  || "";
    document.getElementById("setup-aes").value      = aes  || statusRes.aes_prefill  || "";
    document.getElementById("setup-usmap").value    = usmapPath || statusRes.usmap_prefill || "";
    document.getElementById("setup-mods").value     = statusRes.mods_prefill || "";
    document.getElementById("setup-password").value = statusRes.password_prefill || "";
  } catch (e) {}
  _setSetupLoading(false);
  await validateSetup();
  updateInstallBtn();
}

document.getElementById("setup-cancel").addEventListener("click", () => {
  document.getElementById("setup-overlay").classList.remove("active");
  _pathsMode = false;
});

let _validateGen = 0;
async function validateSetup() {
  const gen     = ++_validateGen;
  const path    = document.getElementById("setup-path").value.trim();
  const usmap   = document.getElementById("setup-usmap").value.trim();
  const key     = document.getElementById("setup-aes").value.trim();
  const el      = document.getElementById("setup-status");
  const saveBtn = document.getElementById("setup-save");

  let pakStatus = "", pakMsg = "";
  if (path) {
    try {
      const r = await fetch(`/api/validate_paks?path=${encodeURIComponent(path)}`);
      const d = await r.json();
      pakStatus = d.status;
      if (d.status === "wrong_folder") pakMsg = "MarvelRivals folder not found";
      else if (d.status === "missing")  pakMsg = "Path doesn't exist";
    } catch (_) {}
  }

  let usmapStatus = "";
  if (usmap) {
    try {
      const r = await fetch(`/api/validate_usmap?path=${encodeURIComponent(usmap)}`);
      const d = await r.json();
      usmapStatus = d.status;
    } catch (_) {}
  }

  let modsStatus = "";
  if (_pathsMode) {
    const mods = document.getElementById("setup-mods").value.trim();
    if (mods) {
      try {
        const r = await fetch(`/api/validate_mods_folder?path=${encodeURIComponent(mods)}`);
        const d = await r.json();
        modsStatus = d.status;
      } catch (_) {}
    }
  }

  if (gen !== _validateGen) return;

  let keyStatus = "";
  if (key) {
    keyStatus = /^0x[0-9A-Fa-f]{60,68}$/.test(key) ? "ok" : "invalid";
  }

  const pakOk    = pakStatus === "ok";
  const usmapOk  = usmapStatus === "ok";
  const keyOk    = keyStatus === "ok";
  const pakBad   = pakStatus === "wrong_folder" || pakStatus === "missing";
  const usmapBad = usmapStatus === "invalid" || usmapStatus === "missing";
  const keyBad   = keyStatus === "invalid";
  const modsOk   = modsStatus === "ok";
  const modsBad  = modsStatus === "invalid";

  if (pakOk && usmapOk && keyOk && !modsBad) {
    el.className = "ok";
    el.innerHTML = '<i data-lucide="check-circle" size="13"></i> All Valid';
    saveBtn.disabled = false;
  } else {
    saveBtn.disabled = true;
    if (pakBad) {
      el.className = "error";
      el.innerHTML = `<i data-lucide="x-circle" size="13"></i> ${pakMsg}`;
    } else if (usmapBad) {
      el.className = "error";
      el.innerHTML = usmapStatus === "missing"
        ? '<i data-lucide="x-circle" size="13"></i> USMAP file not found'
        : '<i data-lucide="x-circle" size="13"></i> Not a valid .usmap file';
    } else if (keyBad) {
      el.className = "error";
      el.innerHTML = '<i data-lucide="x-circle" size="13"></i> Invalid AES key format';
    } else if (modsBad) {
      el.className = "error";
      el.innerHTML = '<i data-lucide="x-circle" size="13"></i> Mods folder path is not a folder';
    } else if (pakOk && usmapOk && !key) {
      el.className = "error";
      el.innerHTML = '<i data-lucide="x-circle" size="13"></i> Key missing';
    } else {
      el.className = ""; el.innerHTML = "";
    }
  }
  lucide.createIcons({ nodes: [el] });

  const pathEl  = document.getElementById("setup-path");
  const usmapEl = document.getElementById("setup-usmap");
  const aesEl   = document.getElementById("setup-aes");
  pathEl.classList.toggle("setup-valid",   pakOk);
  pathEl.classList.toggle("setup-invalid", pakBad);
  usmapEl.classList.toggle("setup-valid",   usmapOk);
  usmapEl.classList.toggle("setup-invalid", usmapBad);
  aesEl.classList.toggle("setup-valid",   keyOk);
  aesEl.classList.toggle("setup-invalid", keyBad || (pakOk && usmapOk && !key));
  if (_pathsMode) {
    const modsEl = document.getElementById("setup-mods");
    modsEl.classList.toggle("setup-valid",   modsOk);
    modsEl.classList.toggle("setup-invalid", modsBad);
  }
}

document.getElementById("setup-path").addEventListener("input", validateSetup);
document.getElementById("setup-usmap").addEventListener("input", validateSetup);
document.getElementById("setup-aes").addEventListener("input", validateSetup);
document.getElementById("setup-mods").addEventListener("input", validateSetup);
document.getElementById("setup-paste-key").addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      document.getElementById("setup-aes").value = text.trim();
      validateSetup();
    }
  } catch {}
});

document.getElementById("setup-browse").addEventListener("click", async () => {
  const initial = document.getElementById("setup-path").value.trim();
  const btn = document.getElementById("setup-browse");
  btn.disabled = true;
  try {
    const res = await api("/api/pick_folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial }),
    });
    if (res.ok && res.path) {
      document.getElementById("setup-path").value = res.path;
      validateSetup();
    }
  } catch (e) {}
  btn.disabled = false;
});

document.getElementById("setup-usmap-browse").addEventListener("click", async () => {
  const initial = document.getElementById("setup-usmap").value.trim();
  const btn = document.getElementById("setup-usmap-browse");
  btn.disabled = true;
  try {
    const res = await api("/api/pick_usmap_file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial }),
    });
    if (res.ok && res.path) {
      document.getElementById("setup-usmap").value = res.path;
      validateSetup();
    }
  } catch (e) {}
  btn.disabled = false;
});

document.getElementById("setup-mods-browse").addEventListener("click", async () => {
  const initial = document.getElementById("setup-mods").value.trim();
  const btn = document.getElementById("setup-mods-browse");
  btn.disabled = true;
  try {
    const res = await api("/api/pick_folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial, raw: true, desc: "Select your mods folder (e.g. …/Paks/~mods):" }),
    });
    if (res.ok && res.path) {
      document.getElementById("setup-mods").value = res.path;
      validateSetup();
    }
  } catch (e) {}
  btn.disabled = false;
});


function _resetSaveBtn() {
  const btn = document.getElementById("setup-save");
  const label = _pathsMode ? "Save" : "Save & Continue";
  btn.disabled = false;
  btn.innerHTML = `<i data-lucide="check" size="14"></i> <span id="setup-save-label">${label}</span>`;
  lucide.createIcons({ nodes: [btn] });
}

document.getElementById("setup-save").addEventListener("click", async () => {
  const path      = document.getElementById("setup-path").value.trim();
  const usmapPath = document.getElementById("setup-usmap").value.trim();
  const rawKey    = document.getElementById("setup-aes").value.trim();
  const aes_key   = rawKey.toLowerCase().startsWith("0x") ? rawKey.slice(2) : rawKey;
  if (!path)      { toast("Please enter a path", "warning"); return; }
  if (!usmapPath) { toast("Please enter or auto-fetch a USMAP file", "warning"); return; }
  if (!aes_key)   { toast("Please enter an AES key", "warning"); return; }
  const payload = { path, aes_key, usmap_path: usmapPath };
  if (_pathsMode) {
    payload.mods_folder     = document.getElementById("setup-mods").value.trim();
    payload.export_password = document.getElementById("setup-password").value;
  }
  const btn = document.getElementById("setup-save");
  btn.disabled = true;
  btn.innerHTML = "Saving…";
  try {
    const res = await api("/api/save_paks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const wasPaths   = _pathsMode;
      const wasModsSet = _modsFolderSet;
      _pathsMode = false;
      document.getElementById("setup-overlay").classList.remove("active");
      _resetSaveBtn();
      _modsFolderPath      = res.mods_folder || "";
      _modsFolderSet       = !!res.mods_folder;
      _protectionPassword  = res.export_password || "";
      if (!wasModsSet && _modsFolderSet) document.getElementById("toggle-copy").checked = true;
      if (wasPaths) {
        toast("Settings saved", "success");
        await renderGrid();
        await loadSidebar();
        updateInstallBtn();
      } else {
        await checkProject();
        await checkPrereqs();
        await renderGrid();
        await loadSidebar();
        updateInstallBtn();
      }
    } else {
      toast(`Error: ${res.error}`, "warning");
      _resetSaveBtn();
    }
  } catch (e) {
    toast(`Error: ${e.message}`, "warning");
    _resetSaveBtn();
  }
});

// ── sidebar resize ────────────────────────────────────────────────────────────
{
  const handle  = document.getElementById("sidebar-resize");
  const sidebar = document.getElementById("sidebar");
  let dragging = false, startX = 0, startW = 0;

  handle.addEventListener("mousedown", e => {
    dragging = true;
    startX   = e.clientX;
    startW   = sidebar.offsetWidth;
    handle.classList.add("dragging");
    document.body.style.userSelect = "none";
    document.body.style.cursor     = "col-resize";
    e.preventDefault();
  });

  document.addEventListener("mousemove", e => {
    if (!dragging) return;
    const newW = Math.min(520, Math.max(140, startW + (startX - e.clientX)));
    sidebar.style.width = newW + "px";
  });

  document.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove("dragging");
    document.body.style.userSelect = "";
    document.body.style.cursor     = "";
  });
}

// ── context menu ──────────────────────────────────────────────────────────────
let _ctxFileTarget = null;
const _ctxMenu      = document.getElementById("ctx-menu");
const _ctxFileInput = document.getElementById("ctx-file-input");

function _ctxShow(e, items) {
  e.preventDefault();
  e.stopPropagation();
  if (!items.length) return;
  _ctxMenu.innerHTML = "";
  for (const item of items) {
    if (item === "sep") {
      const d = document.createElement("div");
      d.className = "ctx-sep";
      _ctxMenu.appendChild(d);
      continue;
    }
    const el = document.createElement("div");
    el.className = "ctx-item" + (item.danger ? " danger" : "");
    el.innerHTML = `<i data-lucide="${item.icon}" size="13"></i><span>${item.label}</span>`;
    el.addEventListener("click", ev => { ev.stopPropagation(); _ctxHide(); item.action(); });
    _ctxMenu.appendChild(el);
  }
  lucide.createIcons({ nodes: [_ctxMenu] });
  _ctxMenu.style.left = e.clientX + "px";
  _ctxMenu.style.top  = e.clientY + "px";
  _ctxMenu.classList.add("active");
  const r = _ctxMenu.getBoundingClientRect();
  if (r.right  > window.innerWidth)  _ctxMenu.style.left = (e.clientX - r.width)  + "px";
  if (r.bottom > window.innerHeight) _ctxMenu.style.top  = (e.clientY - r.height) + "px";
}

function _ctxHide() { _ctxMenu.classList.remove("active"); }

document.addEventListener("click", _ctxHide);
document.addEventListener("contextmenu", () => _ctxHide());

_ctxFileInput.addEventListener("change", async () => {
  const file = _ctxFileInput.files[0];
  _ctxFileInput.value = "";
  if (!file || !_ctxFileTarget) return;
  const game_rel = _ctxFileTarget;
  _ctxFileTarget = null;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("game_rel", game_rel);
  suppressedImportGameRels.add(game_rel);
  const t = toastSpinner("Replacing…");
  try {
    const res  = await fetch("/api/replace_texture", { method: "POST", body: fd });
    const data = await res.json();
    t.remove();
    if (data.ok) {
      suppressChangeToastUntil = Date.now() + 1500;
      suppressedImportGameRels.delete(game_rel);
      toast("Texture replaced", "success");
      const bust = `&_t=${Date.now()}`;
      document.querySelectorAll(`img[data-game-rel="${CSS.escape(game_rel)}"]`).forEach(img => {
        img.src = `/api/thumb?game_rel=${encodeURIComponent(game_rel)}${bust}`;
      });
      if (data.token) {
        document.querySelectorAll(`img[data-token="${data.token}"]`).forEach(img => {
          img.src = `/api/preview?token=${data.token}&game_rel=${encodeURIComponent(game_rel)}${bust}`;
        });
      }
    } else {
      suppressedImportGameRels.delete(game_rel);
      toast(`Replace failed: ${data.error}`, "warning");
    }
  } catch (err) {
    t.remove();
    suppressedImportGameRels.delete(game_rel);
    toast(`Error: ${err.message}`, "warning");
  }
});

function _ctxItemsCard(card) {
  const items = [];
  if (!card.imported) {
    items.push({ icon: "download", label: card.file_type === "mesh" ? "View in 3D" : "Edit this asset", action: () => handleAssetClick({ imported: card.imported, token: card.token, file_type: card.file_type, name: card.label, rel_path: card.rel_path, game_rel: card.game_rel }) });
    if (card.file_type === "mesh" && card.game_rel)
      items.push({ icon: "box", label: "Edit in Blender", action: () => meshBlendExtract(card.game_rel, card.label) });
    return items;
  }
  if (card.file_type === "mesh" && card.game_rel)
    items.push({ icon: "box", label: "Open in Blender", action: () => openBlend(card.game_rel) });
  if (card.game_rel)
    items.push({ icon: "folder-open", label: "Open in Explorer", action: () => fetch(`/api/open_explorer?game_rel=${encodeURIComponent(card.game_rel)}`) });
  if (card.game_rel)
    items.push({ icon: "compass", label: "Find in Atelier", action: () => { const p = card.game_rel.split("/"); pushNav({ path: p.slice(0, -1).join("/") }); } });
  if (card.imported && card.file_type === "texture" && card.game_rel) {
    if (items.length) items.push("sep");
    items.push({ icon: "image-plus", label: "Replace with Image", action: () => { _ctxFileTarget = card.game_rel; _ctxFileInput.click(); } });
  }
  if (card.imported && card.token) {
    if (items.length && items[items.length - 1] !== "sep") items.push("sep");
    items.push({ icon: "trash-2", label: "Delete edits", danger: true, action: () => clearImported(card.token) });
  }
  return items;
}

function _ctxItemsSidebar(item) {
  const items = [];
  if (item.file_type === "mesh" && item.game_rel)
    items.push({ icon: "box", label: "Open in Blender", action: () => openBlend(item.game_rel) });
  if (item.game_rel)
    items.push({ icon: "folder-open", label: "Open in Explorer", action: () => fetch(`/api/open_explorer?game_rel=${encodeURIComponent(item.game_rel)}`) });
  if (item.game_rel)
    items.push({ icon: "compass", label: "Find in Atelier", action: () => { const p = item.game_rel.split("/"); pushNav({ path: p.slice(0, -1).join("/") }); } });
  if (item.file_type === "texture" && item.game_rel) {
    if (items.length) items.push("sep");
    items.push({ icon: "image-plus", label: "Replace with Image", action: () => { _ctxFileTarget = item.game_rel; _ctxFileInput.click(); } });
  }
  if (items.length) items.push("sep");
  items.push({ icon: "trash-2", label: "Delete edits", danger: true, action: () => clearImported(item.token) });
  return items;
}

// ── USMAP update check ────────────────────────────────────────────────────────
async function checkUsmapUpdate() {
  try { await api("/api/usmap_update_check"); } catch (_) {}
}

// ── update check ──────────────────────────────────────────────────────────────
function _fmtMB(bytes) {
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}
function _showUpdatePanel(id) {
  ["update-checking", "update-confirm", "update-downloading", "update-error"].forEach(p => {
    document.getElementById(p).style.display = p === id ? "flex" : "none";
  });
}

async function checkUpdate() {
  const overlay = document.getElementById("update-overlay");
  overlay.classList.add("active");
  _showUpdatePanel("update-checking");

  let info;
  try { info = await api("/api/update_check"); }
  catch { overlay.classList.remove("active"); return false; }

  if (!info.available) { overlay.classList.remove("active"); return false; }

  document.getElementById("update-tag").textContent = info.tag;
  _showUpdatePanel("update-confirm");
  lucide.createIcons();

  return new Promise(resolve => {
    const dismiss = () => { overlay.classList.remove("active"); resolve(false); };
    document.getElementById("update-later").onclick = dismiss;
    const skipVerBtn = document.getElementById("update-skip-ver");
    if (skipVerBtn) skipVerBtn.onclick = async () => {
      try { await api("/api/update_skip", { method: "POST" }); } catch {}
      dismiss();
    };
    document.getElementById("update-now").onclick = async () => {
      _showUpdatePanel("update-downloading");
      const fill  = document.getElementById("update-dl-fill");
      const label = document.getElementById("update-dl-label");
      try { await api("/api/update_download", { method: "POST" }); }
      catch { _showUpdatePanel("update-error"); return; }
      const poll = setInterval(async () => {
        let s, p;
        try {
          [s, p] = await Promise.all([api("/api/update_status"), api("/api/update_progress")]);
        } catch { clearInterval(poll); return; }
        if (p.total > 0) {
          fill.style.width = p.pct + "%";
          label.textContent = `${_fmtMB(p.bytes)} / ${_fmtMB(p.total)}  (${p.pct}%)`;
        }
        if (s.state === "error") {
          clearInterval(poll);
          _showUpdatePanel("update-error");
          document.getElementById("update-error-ok").onclick = () => { overlay.classList.remove("active"); resolve(false); };
        }
      }, 300);
    };
    document.getElementById("update-error-ok").onclick = () => {
      overlay.classList.remove("active");
      resolve(false);
    };
  });
}

// ── project picker ────────────────────────────────────────────────────────────
let _projPickerResolve  = null;
let _projNameCtx        = null;
let _projDeleteName     = null;
let _activeProjectName  = "";

const _SAFE_NAME_RE = /[/\\:*?"<>|]/g;
function _enforceSafeName(input) {
  input.addEventListener("input", () => {
    const clean = input.value.replace(_SAFE_NAME_RE, "");
    if (clean !== input.value) input.value = clean;
  });
}
_enforceSafeName(document.getElementById("proj-name-input"));
_enforceSafeName(document.getElementById("mod-name-input"));

async function checkProject() {
  const res = await api("/api/projects");
  if (res.active && res.projects.find(p => p.name === res.active)) {
    toast(`Project: ${res.active}`, "success");
    return;
  }
  return new Promise(resolve => {
    _projPickerResolve = resolve;
    _renderProjectPicker(res.projects || []);
    document.getElementById("project-overlay").classList.add("active");
  });
}

function _relTime(mtime) {
  const diff = Math.floor(Date.now() / 1000 - mtime);
  if (diff < 60)         return "just now";
  if (diff < 3600)       return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400)      return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7)  return `${Math.floor(diff / 86400)}d ago`;
  return new Date(mtime * 1000).toLocaleDateString();
}

function _renderProjectPicker(projects) {
  const grid = document.getElementById("proj-grid");
  grid.innerHTML = "";
  if (!projects.length) {
    grid.innerHTML = '<div class="proj-empty"><i data-lucide="folder-plus" size="40"></i><div>No projects yet. Create one to get started.</div></div>';
    lucide.createIcons({ nodes: [grid] });
    return;
  }
  projects.forEach(proj => {
    const card = document.createElement("div");
    card.className = "proj-card";
    card.dataset.name = proj.name;
    const assetTxt  = proj.asset_count === 1 ? "1 asset" : `${proj.asset_count} assets`;
    const thumbUrl  = `/api/project/thumb?project=${encodeURIComponent(proj.name)}&_t=${proj.mtime}`;
    card.innerHTML = `
      <div class="proj-thumb">
        <img src="${thumbUrl}" alt="" onload="this.nextElementSibling.style.display='none'" onerror="this.style.display='none'">
        <i data-lucide="folder" size="40" class="proj-thumb-icon"></i>
      </div>
      <div class="proj-body">
        <div class="proj-name" title="${proj.name}">${proj.name}</div>
        <div class="proj-meta">${assetTxt} &middot; ${_relTime(proj.mtime)}</div>
      </div>
      <div class="proj-actions">
        <button class="proj-action-btn" title="Rename" data-action="rename"><i data-lucide="pencil" size="13"></i></button>
        <button class="proj-action-btn" title="Duplicate" data-action="duplicate"><i data-lucide="copy" size="13"></i></button>
        <button class="proj-action-btn danger" title="Delete" data-action="delete"><i data-lucide="trash-2" size="13"></i></button>
      </div>`;
    card.addEventListener("click", e => {
      if (e.target.closest(".proj-action-btn")) return;
      _selectProject(proj.name);
    });
    card.querySelector("[data-action=rename]").addEventListener("click", e => {
      e.stopPropagation();
      _showProjNameModal({
        title: "Rename Project", value: proj.name, okLabel: "Rename",
        action: async newName => {
          const r = await api("/api/project/rename", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ old_name: proj.name, new_name: newName }),
          });
          if (r.ok) { const res = await api("/api/projects"); _renderProjectPicker(res.projects || []); }
          else toast(`Rename failed: ${r.error}`, "warning");
        },
      });
    });
    card.querySelector("[data-action=duplicate]").addEventListener("click", e => {
      e.stopPropagation();
      _showProjNameModal({
        title: "Duplicate Project", value: `Copy of ${proj.name}`, okLabel: "Duplicate",
        action: async newName => {
          const r = await api("/api/project/duplicate", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: proj.name, new_name: newName }),
          });
          if (r.ok) { const res = await api("/api/projects"); _renderProjectPicker(res.projects || []); }
          else toast(`Duplicate failed: ${r.error}`, "warning");
        },
      });
    });
    card.querySelector("[data-action=delete]").addEventListener("click", e => {
      e.stopPropagation();
      _projDeleteName = proj.name;
      document.getElementById("proj-delete-msg").textContent =
        `Delete project "${proj.name}"? All ${proj.asset_count} edited asset${proj.asset_count !== 1 ? "s" : ""} will be permanently deleted.`;
      document.getElementById("proj-delete-overlay").classList.add("active");
    });
    grid.appendChild(card);
  });
  lucide.createIcons({ nodes: [grid] });
}

function _applyActiveProject(name) {
  _activeProjectName = name;
  const modInput = document.getElementById("mod-name-input");
  modInput.value       = name;
  modInput.placeholder = name || "ModFilename";
}

async function _selectProject(name) {
  const r = await api("/api/project/select", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) { toast(`Failed to open project: ${r.error}`, "warning"); return; }
  toast(`Project: ${name}`, "success");
  _applyActiveProject(name);
  document.getElementById("project-overlay").classList.remove("active");
  if (_projPickerResolve) {
    const resolve = _projPickerResolve;
    _projPickerResolve = null;
    resolve();
  } else {
    sidebarData = {};
    nav = { ...NAV_ROOT };
    history = [{ ...NAV_ROOT }];
    histIdx = 0;
    updateNavBtns();
    document.getElementById("search-input").value = "";
    renderBreadcrumbs();
    await renderGrid();
    await loadSidebar();
  }
}

function _showProjNameModal(ctx) {
  _projNameCtx = ctx;
  document.getElementById("proj-name-title").textContent = ctx.title;
  document.getElementById("proj-name-input").value = ctx.value;
  const okBtn = document.getElementById("proj-name-ok");
  okBtn.innerHTML = `<i data-lucide="check" size="14"></i> ${ctx.okLabel}`;
  lucide.createIcons({ nodes: [okBtn] });
  document.getElementById("proj-name-overlay").classList.add("active");
  setTimeout(() => {
    const inp = document.getElementById("proj-name-input");
    inp.focus(); inp.select();
  }, 40);
}

document.getElementById("proj-new-btn").addEventListener("click", () => {
  _showProjNameModal({
    title: "New Project", value: "", okLabel: "Create",
    action: async name => {
      const r = await api("/api/project/create", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (r.ok) await _selectProject(name);
      else toast(`Create failed: ${r.error}`, "warning");
    },
  });
});

document.getElementById("proj-name-cancel").addEventListener("click", () => {
  document.getElementById("proj-name-overlay").classList.remove("active");
  _projNameCtx = null;
});

document.getElementById("proj-name-ok").addEventListener("click", async () => {
  const name = document.getElementById("proj-name-input").value.trim();
  if (!name) return;
  document.getElementById("proj-name-overlay").classList.remove("active");
  if (_projNameCtx) { const ctx = _projNameCtx; _projNameCtx = null; await ctx.action(name); }
});

document.getElementById("proj-name-input").addEventListener("keydown", e => {
  if (e.key === "Enter")  document.getElementById("proj-name-ok").click();
  if (e.key === "Escape") document.getElementById("proj-name-cancel").click();
});

document.getElementById("proj-delete-cancel").addEventListener("click", () => {
  document.getElementById("proj-delete-overlay").classList.remove("active");
  _projDeleteName = null;
});

document.getElementById("proj-delete-ok").addEventListener("click", async () => {
  document.getElementById("proj-delete-overlay").classList.remove("active");
  const name = _projDeleteName; _projDeleteName = null;
  if (!name) return;
  const r = await api("/api/project/delete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (r.ok) {
    toast(`Deleted project "${name}"`, "warning");
    const res = await api("/api/projects");
    _renderProjectPicker(res.projects || []);
    if (!res.active || !res.projects.find(p => p.name === res.active)) {
      document.getElementById("project-overlay").classList.add("active");
    }
  } else {
    toast(`Delete failed: ${r.error}`, "warning");
  }
});

document.getElementById("menu-btn").addEventListener("click", e => {
  const rect = e.currentTarget.getBoundingClientRect();
  _ctxShow(
    { preventDefault: () => {}, stopPropagation: () => e.stopPropagation(), clientX: rect.left, clientY: rect.bottom + 4 },
    [
      { icon: "folder-open", label: "Back to Projects", action: async () => {
        const res = await api("/api/projects");
        _renderProjectPicker(res.projects || []);
        document.getElementById("project-overlay").classList.add("active");
      }},
      { icon: "refresh-cw", label: "Refresh View", action: () => renderGrid().then(() => toast("Refreshed view", "success")) },
      { icon: "folder-search", label: "Show in Explorer", action: () => { fetch("/api/open_projects_folder"); toast("Explorer opened", "success"); } },
      { icon: "package-open", label: "Open Export Folder", action: () => { fetch("/api/open_export_folder"); toast("Export folder opened", "success"); } },
      "sep",
      { icon: "wrench", label: "Repatch a mod…", action: () => openRepatcher() },
      { icon: "binary", label: "Shader Studio…", action: () => openShaderStudio() },
      { icon: "sliders-horizontal", label: "Settings…", action: () => openPaths() },
      { icon: "circle-help", label: "Help / Info", action: () => { window.open("https://github.com/clownfetus/Atelier#usage", "_blank"); toast("Browser tab opened", "info"); } },
      "sep",
      { icon: "trash-2", label: "Reset Data…", danger: true, action: () => document.getElementById("reset-overlay").classList.add("active") },
    ]
  );
});

document.getElementById("reset-cancel").addEventListener("click", () => {
  document.getElementById("reset-overlay").classList.remove("active");
});

// ── Repatcher ──────────────────────────────────────────────────────────────
let _repatchPath = "";
function openRepatcher() {
  _repatchPath = "";
  document.getElementById("repatch-file").textContent = "";
  document.getElementById("repatch-lockrow").style.display = "none";
  document.getElementById("repatch-unlock").value = "";
  document.getElementById("repatch-stage").checked = false;
  document.getElementById("repatch-pw").value = "";
  document.getElementById("repatch-run").disabled = true;
  const res = document.getElementById("repatch-result"); res.style.display = "none"; res.innerHTML = "";
  document.getElementById("repatch-overlay").classList.add("active");
  if (window.lucide) lucide.createIcons();
}
document.getElementById("repatch-close").addEventListener("click", () =>
  document.getElementById("repatch-overlay").classList.remove("active"));
document.getElementById("repatch-pick").addEventListener("click", async () => {
  const r = await api("/api/pick_mod_file", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  if (!r || !r.ok || !r.path) return;
  _repatchPath = r.path;
  document.getElementById("repatch-file").textContent = r.path;
  document.getElementById("repatch-lockrow").style.display = r.locked ? "block" : "none";
  document.getElementById("repatch-run").disabled = false;
});
document.getElementById("repatch-run").addEventListener("click", async () => {
  if (!_repatchPath) return;
  const btn = document.getElementById("repatch-run"); btn.disabled = true;
  const res = document.getElementById("repatch-result");
  res.style.display = "block"; res.innerHTML = '<span class="muted">Repatching…</span>';
  const stage = document.getElementById("repatch-stage").checked;
  const pw = document.getElementById("repatch-pw").value.trim();
  try {
    const r = await api("/api/repatch", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: _repatchPath, unlock: document.getElementById("repatch-unlock").value, stage_as_project: stage, password: pw }) });
    if (r.locked) { res.innerHTML = '<span class="warning">Wrong or missing password.</span>'; btn.disabled = false; return; }
    if (!r.ok) { res.innerHTML = '<span class="warning">Failed: ' + (r.error || "unknown") + '</span>'; btn.disabled = false; return; }
    const m = r.manifest || {};
    res.innerHTML = '<b>✓ Repatched</b> — ' + r.mod + '<br><span class="muted">' +
      (m.materials || 0) + ' materials · ' + (m.textures || 0) + ' textures · ' + (m.skipped || 0) + ' skipped' +
      (stage ? ' · ' + (m.staged_project || 0) + ' staged to project' : '') + (pw ? ' · 🔒 locked' : '') +
      '</span><br><a href="#" id="repatch-open">Open export folder</a>';
    const oa = document.getElementById("repatch-open");
    if (oa) oa.addEventListener("click", (e) => { e.preventDefault(); fetch("/api/open_export_folder?select=" + encodeURIComponent(r.pak || "")); });
    toast("Repatched: " + r.mod, "success", 5000);
    if (stage) renderGrid();
    btn.disabled = false;
  } catch (e) { res.innerHTML = '<span class="warning">Error: ' + e + '</span>'; btn.disabled = false; }
});

document.getElementById("reset-ok").addEventListener("click", async () => {
  document.getElementById("reset-overlay").classList.remove("active");
  const t = toastSpinner("Resetting…");
  try {
    await api("/api/reset_data", { method: "POST" });
    t.remove();
    window.location.reload();
  } catch (e) {
    t.remove();
    toast(`Reset failed: ${e.message}`, "warning");
  }
});

// ── initial load ──────────────────────────────────────────────────────────────
async function init() {
  console.log("[init] starting");
  renderBreadcrumbs();
  if (await checkUpdate()) { console.log("[init] update in progress"); return; }
  if (await checkSetup()) { console.log("[init] halted for setup"); return; }
  await checkProject();
  await checkPrereqs();
  await renderGrid();
  await loadSidebar();
  checkUsmapUpdate();
}

init();

// ── Shader Studio ─────────────────────────────────────────────────────────────
const _sh = { page: 0, total: 0, sel: null, busy: false, poll: null };

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

_shEl("shader-build-btn").addEventListener("click", startShaderBuild);
_shEl("shader-close").addEventListener("click", closeShaderStudio);

async function startShaderBuild() {
  _shEl("shader-build-btn").style.display = "none";
  _shEl("shader-build-err").style.display = "none";
  _shEl("shader-build-prog").style.display = "block";
  _shEl("shader-bar-fill").style.width = "5%";
  _shEl("shader-build-msg").textContent = "Starting…";
  try { await api("/api/shaders/build", { method: "POST" }); }
  catch (e) { _shBuildError(e.message); return; }
  _sh.poll = setInterval(async () => {
    let st; try { st = await api("/api/shaders/status"); } catch { return; }
    const b = st.build || {};
    if (b.error) { clearInterval(_sh.poll); _sh.poll = null; _shBuildError(b.error); return; }
    _shEl("shader-bar-fill").style.width = Math.max(5, b.pct || 0) + "%";
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

let _shQTimer = null;
["shader-lib", "shader-freq"].forEach(id =>
  _shEl(id).addEventListener("change", () => { _sh.page = 0; loadShaderList(); }));
_shEl("shader-q").addEventListener("input", () => {
  clearTimeout(_shQTimer);
  _shQTimer = setTimeout(() => { _sh.page = 0; loadShaderList(); }, 250);
});
_shEl("shader-prev").addEventListener("click", () => { if (_sh.page > 0) { _sh.page--; loadShaderList(); } });
_shEl("shader-next").addEventListener("click", () => {
  if ((_sh.page + 1) * 200 < _sh.total) { _sh.page++; loadShaderList(); }
});

const _FREQ_CLASS = { 0: "vtx", 3: "pix", 5: "cmp" };

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
  } catch (e) { list.innerHTML = `<div class="muted" style="padding:14px">Error: ${e.message}</div>`; return; }
  if (!res.ok) { list.innerHTML = `<div class="muted" style="padding:14px">${res.error}</div>`; return; }
  _sh.total = res.total;
  if (!res.rows.length) { list.innerHTML = `<div class="muted" style="padding:14px">No shaders match.</div>`; }
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

function _esc(s) { return String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

function _shSelectTab(tab) {
  document.querySelectorAll(".sh-tab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  _shEl("shader-props").style.display = tab === "props" ? "block" : "none";
  _shEl("shader-disasm").style.display = tab === "raw" ? "block" : "none";
}

async function loadShaderEdit() {
  const wrap = _shEl("shader-edit");
  if (!_sh.cur) { wrap.innerHTML = `<div class="sh-note">Select a shader first.</div>`; return; }
  if (wrap.dataset.loadedFor === `${_sh.cur.lib}#${_sh.cur.idx}`) return;   // cache per shader
  wrap.dataset.loadedFor = `${_sh.cur.lib}#${_sh.cur.idx}`;
  wrap.innerHTML = `<div class="shader-loading"><div class="spinner"></div><span>Disassembling to editable IR…</span></div>`;
  let res;
  try { res = await api(`/api/shaders/ir?lib=${encodeURIComponent(_sh.cur.lib)}&idx=${_sh.cur.idx}`); }
  catch (e) { wrap.innerHTML = `<div class="warning">${e.message}</div>`; wrap.dataset.loadedFor = ""; return; }
  if (!res.ok) { wrap.innerHTML = `<div class="warning">${res.error}</div>`; wrap.dataset.loadedFor = ""; return; }
  wrap.innerHTML = `
    <div class="sh-note"><i data-lucide="pencil" size="13"></i>
      This is the shader's real code as editable LLVM IR (${(res.lines || 0).toLocaleString()} lines).
      Edit it — e.g. change a <code>fmul</code> factor or a <code>float</code> constant — then
      <b>Reassemble &amp; Build Mod</b>. DXC reassembles it into a real shader.
      <b>Note:</b> if this dxil.dll can't sign, the mod is emitted unsigned — test it in-game.</div>
    <textarea id="sh-ir" class="sh-ir" spellcheck="false"></textarea>
    <div class="sh-buildrow">
      <input id="sh-mod-name" class="sh-pval" placeholder="mod name (optional)" spellcheck="false" style="flex:1">
      <button class="btn" id="sh-ir-reset"><i data-lucide="rotate-ccw" size="13"></i> Reset</button>
      <button class="btn primary" id="sh-build-btn"><i data-lucide="package" size="14"></i> Reassemble &amp; Build Mod</button>
    </div>`;
  lucide.createIcons({ nodes: [wrap] });
  const ta = _shEl("sh-ir");
  ta.value = res.ir || "";
  ta.dataset.orig = res.ir || "";
  _shEl("sh-ir-reset").addEventListener("click", () => { ta.value = ta.dataset.orig; });
  _shEl("sh-build-btn").addEventListener("click", buildShaderMod);
}

async function buildShaderMod() {
  const ta = _shEl("sh-ir");
  if (!ta || !ta.value.trim()) { toast("No IR to build", "warning"); return; }
  if (ta.value === ta.dataset.orig) { toast("Edit the IR first — it's unchanged", "warning"); return; }
  const btn = _shEl("sh-build-btn");
  btn.disabled = true;
  const t = toastSpinner("Reassembling & building shader mod…");
  let res;
  try {
    res = await api("/api/shaders/build_mod_ir", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lib: _sh.cur.lib, idx: _sh.cur.idx,
                             name: (_shEl("sh-mod-name").value || "").trim(), ir: ta.value }),
    });
  } catch (e) { t.remove(); btn.disabled = false; toast("Build failed: " + e.message, "warning"); return; }
  t.remove(); btn.disabled = false;
  if (!res.ok) { toast("Build failed: " + res.error, "warning", 7000); return; }
  toast(`${res.signed ? "Signed" : "UNSIGNED"} shader mod built → ${res.files.join(", ")}`,
        res.signed ? "success" : "warning", 8000);
  if (res.note) toast(res.note, "info", 9000);
}
document.querySelectorAll(".sh-tab").forEach(b =>
  b.addEventListener("click", () => _shSelectTab(b.dataset.tab)));

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
      These are the shader's live properties. Constant buffers are its parameter banks; per-value
      editing arrives with Phase&nbsp;4's in-game round-trip (proven on one shader first).</div>`;

  // Constant buffers = the shader's parameter banks.
  html += `<div class="sh-sec">
      <div class="sh-sec-h"><i data-lucide="box" size="13"></i> Constant buffers (params)
        <span class="pm">${cbufs.length}</span></div>
      <table class="sh-tbl">
        ${cbufs.length ? cbufs.map(r => `<tr>
          <td class="pk">${_esc(r.bind)}</td><td>${_esc(r.name)}</td>
          <td><input class="sh-pval" placeholder="edit in Phase 4" disabled
               title="Per-value editing arrives with the Phase 4 round-trip"></td></tr>`).join("")
        : `<tr><td class="pm">none</td></tr>`}
      </table></div>`;

  // Textures / samplers / UAVs.
  html += `<div class="sh-sec">
      <div class="sh-sec-h"><i data-lucide="plug" size="13"></i> Textures &amp; samplers
        <span class="pm">${other.length}</span></div>
      <table class="sh-tbl">
        ${other.length ? other.map(r => `<tr>
          <td class="pk">${_esc(r.bind)}</td><td class="pm">${_esc(r.type)}</td>
          <td class="pm">${_esc(r.fmt || "")}</td><td>${_esc(r.name)}</td></tr>`).join("")
        : `<tr><td class="pm">none</td></tr>`}
      </table></div>`;

  // Signatures.
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

// ── World / level editor (lights · fog · grade · component visibility) ─────────
let worldEditor = null;

function _wHx(n) { return ("0" + Math.round(Math.min(255, Math.max(0, n))).toString(16)).slice(-2); }
function _rgb255Hex(c) { c = c || [255, 255, 255]; return "#" + _wHx(c[0]) + _wHx(c[1]) + _wHx(c[2]); }
function _hex255(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
function _rgb01Hex(c) { c = c || [1, 1, 1]; return "#" + _wHx(c[0] * 255) + _wHx(c[1] * 255) + _wHx(c[2] * 255); }
function _hex01(h) { return [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255]; }

async function openWorldEditor(item) {
  const ov = document.getElementById("world-overlay");
  document.getElementById("world-title").textContent = item.name;
  document.getElementById("world-sub").textContent = item.game_rel || "";
  document.getElementById("world-status").textContent = "";
  document.getElementById("world-body").innerHTML = '<div class="spinner" style="margin:44px auto"></div>';
  ov.classList.add("active");
  lucide.createIcons({ nodes: [ov] });
  let res;
  try { res = await api("/api/world_params?game_rel=" + encodeURIComponent(item.game_rel)); }
  catch (e) { document.getElementById("world-body").innerHTML = '<div class="mat-empty">Error: ' + e.message + '</div>'; return; }
  if (!res.ok) { document.getElementById("world-body").innerHTML = '<div class="mat-empty">' + (res.error || "failed to read level") + '</div>'; return; }
  const e = res.edits || {};
  worldEditor = { game_rel: item.game_rel, name: item.name, model: res,
                  edits: { lights: e.lights || {}, fog: e.fog || {}, grade: e.grade || {}, visibility: e.visibility || {} } };
  renderWorldEditor();
}

function renderWorldEditor() {
  const m = worldEditor.model, ed = worldEditor.edits, out = [];
  const sec = (icon, title, inner) => '<div style="margin-bottom:18px"><div style="font-weight:600;font-size:13px;display:flex;align-items:center;gap:7px;margin-bottom:8px"><i data-lucide="' + icon + '" size="14" style="color:var(--acc)"></i> ' + title + '</div>' + inner + '</div>';
  const row = inner => '<div style="display:flex;align-items:center;gap:12px;padding:6px 0;flex-wrap:wrap">' + inner + '</div>';

  if (m.lights && m.lights.length) {
    const rows = m.lights.map(L => {
      const cur = ed.lights[L.idx] || {};
      const inten = (cur.intensity != null) ? cur.intensity : L.intensity;
      const col = cur.color || L.color;
      const ni = (L.intensity != null) ? '<label style="font-size:12px">Intensity <input type="number" step="0.1" style="width:80px" data-lidx="' + L.idx + '" data-lk="intensity" value="' + inten + '"></label>' : "";
      const nc = (L.color) ? '<label style="font-size:12px">Color <input type="color" data-lidx="' + L.idx + '" data-lk="color" value="' + _rgb255Hex(col) + '"></label>' : "";
      return row('<span style="flex:1;min-width:180px;font-size:12px">' + L.name + ' <span class="muted">' + L.cls.replace(/Component$/, "") + '</span></span>' + ni + nc);
    }).join("");
    out.push(sec("sun", 'Lights <span class="muted">(' + m.lights.length + ')</span>', rows));
  }
  if (m.fog) {
    const fc = ed.fog.color || m.fog.color;
    const fd = (ed.fog.density != null) ? ed.fog.density : m.fog.density;
    const nc = (m.fog.color) ? '<label style="font-size:12px">Inscatter color <input type="color" data-fog="color" value="' + _rgb01Hex(fc) + '"></label>' : "";
    const nd = (m.fog.density != null) ? '<label style="font-size:12px">Density <input type="number" step="0.001" style="width:90px" data-fog="density" value="' + fd + '"></label>' : "";
    out.push(sec("cloud-fog", "Height Fog", row(nc + nd)));
  }
  const ppv = (m.components || []).find(c => c.is_ppv);
  if (ppv && ppv.grade && Object.keys(ppv.grade).length) {
    const ORDER = ["ColorSaturation", "ColorContrast", "ColorGamma", "ColorGain", "ColorOffset",
      "ColorSaturationShadows", "ColorContrastShadows", "ColorGainShadows",
      "ColorSaturationMidtones", "ColorSaturationHighlights",
      "BloomIntensity", "VignetteIntensity", "FilmGrainIntensity"];
    const names = ORDER.filter(n => n in ppv.grade).concat(Object.keys(ppv.grade).filter(n => !ORDER.includes(n)));
    let gh = "";
    for (const name of names) {
      const gd = ppv.grade[name];
      const cur = (name in (ed.grade || {})) ? ed.grade[name] : gd.value;
      const pretty = name.replace(/^Color/, "").replace(/([a-z])([A-Z])/g, "$1 $2");
      const tag = gd.override ? "" : ' <span class="muted" style="font-size:10px">(off — edit to enable)</span>';
      const dim = gd.override ? "" : ";opacity:.72";
      const lbl = '<span style="flex:0 0 158px">' + pretty + tag + '</span>';
      if (Array.isArray(gd.value)) {
        const v = Array.isArray(cur) ? cur : gd.value;
        gh += '<div style="display:flex;align-items:center;gap:7px;padding:3px 0;font-size:12px' + dim + '">' + lbl +
          [0, 1, 2].map(ci => '<input type="number" step="0.01" style="width:64px" title="' + "RGB"[ci] +
            '" value="' + (+v[ci]).toFixed(3) + '" data-gname="' + name + '" data-gch="' + ci + '">').join("") + '</div>';
      } else {
        gh += '<div style="display:flex;align-items:center;gap:7px;padding:3px 0;font-size:12px' + dim + '">' + lbl +
          '<input type="number" step="0.05" style="width:82px" value="' + (+cur).toFixed(3) + '" data-gname="' + name + '"></div>';
      }
    }
    out.push(sec("palette", "Post-Process Grade", gh));
  }
  const hide = (m.components || []).filter(c => c.hideable);
  if (hide.length) {
    const rows = hide.map(c => {
      const cur = (c.idx in ed.visibility) ? ed.visibility[c.idx] : (c.enables && "bVisible" in c.enables ? c.enables.bVisible : true);
      return '<label style="display:flex;align-items:center;gap:8px;font-size:12px;padding:3px 0"><input type="checkbox" data-vidx="' + c.idx + '" ' + (cur ? "checked" : "") + '> <span>' + c.name + ' <span class="muted">' + c.cls.replace(/Component$/, "") + '</span></span></label>';
    }).join("");
    out.push(sec("eye", 'Visibility <span class="muted">(' + hide.length + ')</span>',
      '<div style="max-height:220px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:8px 10px">' + rows + '</div>'));
  }
  const body = document.getElementById("world-body");
  body.innerHTML = out.join("") || '<div class="mat-empty">No editable lights, fog, grade, or components in this sublevel.</div>';
  lucide.createIcons({ nodes: [body] });
  _wireWorldInputs();
}

function _wireWorldInputs() {
  const ed = worldEditor.edits, body = document.getElementById("world-body");
  body.querySelectorAll("[data-lidx]").forEach(el => el.addEventListener("input", () => {
    const i = el.dataset.lidx, k = el.dataset.lk;
    (ed.lights[i] = ed.lights[i] || {});
    ed.lights[i][k] = (k === "color") ? _hex255(el.value) : parseFloat(el.value);
  }));
  body.querySelectorAll("[data-fog]").forEach(el => el.addEventListener("input", () => {
    if (el.dataset.fog === "color") ed.fog.color = _hex01(el.value);
    else ed.fog.density = parseFloat(el.value);
  }));
  body.querySelectorAll("[data-gname]").forEach(el => el.addEventListener("input", () => {
    const name = el.dataset.gname, v = parseFloat(el.value); if (isNaN(v)) return;
    if (el.dataset.gch !== undefined) {                         // vec4 channel edit (keep the other channels)
      const ppv = (worldEditor.model.components || []).find(c => c.is_ppv);
      const base = Array.isArray(ed.grade[name]) ? ed.grade[name].slice()
                 : ((ppv && ppv.grade[name] && Array.isArray(ppv.grade[name].value)) ? ppv.grade[name].value.slice() : [1, 1, 1, 1]);
      base[+el.dataset.gch] = v; ed.grade[name] = base;
    } else {                                                    // scalar (bloom/vignette/grain)
      ed.grade[name] = v;
    }
  }));
  body.querySelectorAll("[data-vidx]").forEach(el => el.addEventListener("change", () => {
    ed.visibility[el.dataset.vidx] = el.checked;
  }));
}

document.getElementById("world-close").addEventListener("click", () =>
  document.getElementById("world-overlay").classList.remove("active"));

document.getElementById("world-save").addEventListener("click", async () => {
  if (!worldEditor) return;
  const st = document.getElementById("world-status"); st.textContent = "Saving…";
  try {
    const res = await api("/api/world_save", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: worldEditor.game_rel, edits: worldEditor.edits }) });
    if (!res.ok) { st.textContent = res.error || "save failed"; return; }
    st.textContent = "Saved — included at export.";
    toast("Saved " + worldEditor.name, "success");
    refreshSidebarEntry(worldEditor.game_rel, worldEditor.name, "");
    await renderGrid();
  } catch (e) { st.textContent = "Error: " + e.message; }
});

document.getElementById("world-reset").addEventListener("click", async () => {
  if (!worldEditor) return;
  const st = document.getElementById("world-status"); st.textContent = "Resetting…";
  try {
    const res = await api("/api/world_reset", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: worldEditor.game_rel }) });
    if (!res.ok) { st.textContent = res.error || "reset failed"; return; }
    worldEditor.edits = { lights: {}, fog: {}, grade: {}, visibility: {} };
    worldEditor.model = res;
    renderWorldEditor();
    st.textContent = "Reset to vanilla.";
    toast("Reset " + worldEditor.name, "success");
    await renderGrid();
  } catch (e) { st.textContent = "Error: " + e.message; }
});

// ── Text / StringTable editor ─────────────────────────────────────────────────
let textEditor = null;

function _esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

async function openTextEditor(item) {
  const ov = document.getElementById("text-overlay");
  document.getElementById("text-title").textContent = item.name;
  document.getElementById("text-sub").textContent = item.game_rel || "";
  document.getElementById("text-status").textContent = "";
  document.getElementById("text-search").value = "";
  document.getElementById("text-body").innerHTML = '<div class="spinner" style="margin:44px auto"></div>';
  ov.classList.add("active");
  lucide.createIcons({ nodes: [ov] });
  let res;
  try { res = await api("/api/text_params?game_rel=" + encodeURIComponent(item.game_rel)); }
  catch (e) { document.getElementById("text-body").innerHTML = '<div class="mat-empty">Error: ' + e.message + '</div>'; return; }
  if (!res.ok) { document.getElementById("text-body").innerHTML = '<div class="mat-empty">' + (res.error || "failed to read StringTable") + '</div>'; return; }
  textEditor = { game_rel: item.game_rel, name: item.name, entries: res.entries || [], edits: Object.assign({}, res.edits || {}) };
  renderTextEditor("");
}

function renderTextEditor(filter) {
  const ed = textEditor.edits, f = (filter || "").toLowerCase();
  const rows = [];
  for (const e of textEditor.entries) {
    const cur = (e.key in ed) ? ed[e.key] : e.value;
    if (f && !(String(e.key).toLowerCase().includes(f) || String(cur == null ? "" : cur).toLowerCase().includes(f))) continue;
    const changed = (e.key in ed) && ed[e.key] !== e.value;
    rows.push('<div style="display:flex;gap:10px;align-items:center;padding:4px 0;border-bottom:1px solid var(--line)">' +
      '<div style="flex:0 0 40%;font-size:12px;font-family:ui-monospace,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"' +
      ' title="' + _esc(e.key) + '">' + (changed ? '<span style="color:var(--acc)">●</span> ' : '') + _esc(e.key) + '</div>' +
      '<input data-tkey="' + _esc(e.key) + '" value="' + _esc(cur) + '" spellcheck="false"' +
      ' style="flex:1;background:#0000;color:inherit;border:1px solid var(--line);border-radius:6px;padding:5px 8px;font:inherit;font-size:12px"></div>');
  }
  const body = document.getElementById("text-body");
  body.innerHTML = '<div style="font-size:11px;color:var(--muted);margin-bottom:6px">' + textEditor.entries.length +
    ' strings' + (f ? ' (' + rows.length + ' shown)' : '') + '</div>' +
    (rows.join("") || '<div class="mat-empty">No matching strings.</div>');
  body.querySelectorAll("[data-tkey]").forEach(el => el.addEventListener("input", () => {
    const k = el.dataset.tkey, orig = (textEditor.entries.find(x => String(x.key) === k) || {}).value;
    if (el.value === (orig == null ? "" : String(orig))) delete ed[k];
    else ed[k] = el.value;
  }));
}

document.getElementById("text-search").addEventListener("input", (e) => { if (textEditor) renderTextEditor(e.target.value); });

document.getElementById("text-close").addEventListener("click", () =>
  document.getElementById("text-overlay").classList.remove("active"));

document.getElementById("text-save").addEventListener("click", async () => {
  if (!textEditor) return;
  const st = document.getElementById("text-status"); st.textContent = "Saving…";
  try {
    const res = await api("/api/text_save", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: textEditor.game_rel, edits: textEditor.edits }) });
    if (!res.ok) { st.textContent = res.error || "save failed"; return; }
    const n = Object.keys(textEditor.edits).length;
    st.textContent = n ? (n + " string(s) edited — included at export.") : "No changes.";
    toast("Saved " + textEditor.name, "success");
    refreshSidebarEntry(textEditor.game_rel, textEditor.name, "");
    await renderGrid();
  } catch (e) { st.textContent = "Error: " + e.message; }
});

document.getElementById("text-reset").addEventListener("click", async () => {
  if (!textEditor) return;
  const st = document.getElementById("text-status"); st.textContent = "Resetting…";
  try {
    const res = await api("/api/text_reset", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_rel: textEditor.game_rel }) });
    if (!res.ok) { st.textContent = res.error || "reset failed"; return; }
    textEditor.entries = res.entries || []; textEditor.edits = {};
    renderTextEditor(document.getElementById("text-search").value);
    st.textContent = "Reset to vanilla.";
    toast("Reset " + textEditor.name, "success");
    await renderGrid();
  } catch (e) { st.textContent = "Error: " + e.message; }
});
