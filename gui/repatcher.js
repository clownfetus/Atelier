// Repatcher modal controller (extracted from gui/app.js).
(() => {
  'use strict';

  let _repatchPath = "";

  function openRepatcher() {
    _repatchPath = "";
    window.AtelierModRepair?.select();
    document.getElementById("repatch-file").textContent = "";
    document.getElementById("repatch-lockrow").style.display = "none";
    document.getElementById("repatch-unlock").value = "";
    document.getElementById("repatch-stage").checked = false;
    document.getElementById("repatch-run").disabled = true;
    const res = document.getElementById("repatch-result"); res.style.display = "none"; res.innerHTML = ""; delete res.dataset.state;
    document.getElementById("repatch-overlay").classList.add("active");
    if (window.lucide) lucide.createIcons();
  }

  function showRepatchSkips(container, skipped = []) {
    if (!skipped.length) return;
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Review skipped changes";
    const list = document.createElement("ul");
    for (const problem of skipped) {
      const item = document.createElement("li");
      item.textContent = problem;
      list.append(item);
    }
    details.append(summary, list);
    container.append(details);
  }

  document.getElementById("repatch-close")?.addEventListener("click", () =>
    document.getElementById("repatch-overlay").classList.remove("active"));

  document.getElementById("repatch-pick")?.addEventListener("click", async () => {
    const r = await api("/api/pick_mod_file", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (!r || !r.ok || !r.path) return;
    _repatchPath = r.path;
    window.AtelierModRepair?.select(r.path);
    document.getElementById("repatch-file").textContent = r.path;
    document.getElementById("repatch-lockrow").style.display = r.locked ? "block" : "none";
    document.getElementById("repatch-run").disabled = false;
  });

  document.getElementById("repatch-run")?.addEventListener("click", async () => {
    if (!_repatchPath) return;
    const btn = document.getElementById("repatch-run");
    btn.disabled = true;
    const result = document.getElementById("repatch-result");
    result.style.display = "block";
    result.dataset.state = "busy";
    result.textContent = "Repatching…";
    const stage = document.getElementById("repatch-stage").checked;
    try {
      const r = await (window.AtelierJobs?.run || api)("/api/repatch", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: _repatchPath, unlock: document.getElementById("repatch-unlock").value, stage_as_project: stage }),
      });
      if (!r.ok) {
        result.dataset.state = "error";
        result.textContent = r.locked ? "Wrong or missing password." : r.error || "Couldn’t repatch this mod.";
        showRepatchSkips(result, r.skipped);
        return;
      }
      const m = r.manifest || {};
      result.dataset.state = m.skipped ? "warning" : "success";
      const title = document.createElement("strong");
      title.textContent = "Repatched " + r.mod;
      const counts = document.createElement("span");
      counts.className = "muted";
      counts.textContent = [
        (m.materials || 0) + " materials",
        (m.textures || 0) + " textures",
        (m.skipped || 0) + " skipped",
        ...(m.recovered_materials ? [m.recovered_materials + " recovered from older layouts"] : []),
        ...(stage ? [(m.staged_project || 0) + " staged to project"] : []),
      ].join(" · ");
      const open = document.createElement("a");
      open.href = "#";
      open.id = "repatch-open";
      open.textContent = "Open export folder";
      open.addEventListener("click", event => {
        event.preventDefault();
        projectFetch("/api/open_export_folder?select=" + encodeURIComponent(r.pak || ""));
      });
      result.replaceChildren(title, document.createElement("br"), counts, document.createElement("br"), open);
      showRepatchSkips(result, r.skipped);
      toast("Repatched " + r.mod, m.skipped ? "warning" : "success", 5000);
      if (stage) renderGrid();
    } catch (_) {
      result.dataset.state = "error";
      result.textContent = "Couldn’t repatch this mod.";
    } finally {
      btn.disabled = !_repatchPath;
    }
  });

  window.openRepatcher = openRepatcher;
})();
