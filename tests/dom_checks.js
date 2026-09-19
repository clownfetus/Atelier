// Assertions for the Phase 3 UI, evaluated inside dom_smoke.js's context — every identifier below
// (matEditor, renderMatEditor, sidebarData, …) is gui/app.js's own. Throws on the first failure.
// ── material editor with a dyeable material ──────────────────────────────────
matEditor = {
  game_rel: "Characters/1060/1060300/MI_Body", name: "MI_Body",
  colors: [{ name: "Region 1 - ColorA", rgba: [1, 0.2, 0.2, 1], inten: 1 },
           { name: "Region 1 - ColorB", rgba: [0.2, 0.2, 1, 1], inten: 1 },
           { name: "Region 3 - ColorA", rgba: [2.5, 2.0, 0.1, 1], inten: 2.5 }],
  scalars: [{ name: "Metallic", value: 0.5, orig: 0.5, max: 1.5 }],
  dyeable: true, dyeUsed: ["1", "3"], dyeView: "regions",
  dyeInfo: { dyeable: true, used: { "0": 100, "1": 300, "3": 600 },
             overlay: { "0": "#8e8e93", "1": "#ff3b30", "3": "#ffd60a" },
             coverage: { "0": 10.0, "1": 30.0, "3": 60.0 },
             regions: { "1": { ColorA: [1, 0.2, 0.2, 1] }, "3": { ColorA: [2.5, 2, 0.1, 1] } } },
};
renderMatEditor();
const matHtml = document.getElementById("mat-body").innerHTML;
const need = ['id="dye-prev"', 'dyeView(\'regions\')', 'class="dye-legend"', 'matFocusRegion(1)',
              'matFocusRegion(3)', 'class="mat-hex"', 'setColorMode(', 'id="matrow0"', '60%'];
for (const n of need) if (!matHtml.includes(n)) throw new Error("material editor missing: " + n);
if (matHtml.includes("matFocusRegion(0)")) throw new Error("undyed region must not be clickable");

// notation switching must re-render in the new notation
setColorMode("255");
if (!document.getElementById("mat-body").innerHTML.includes('value="255, 51, 51"'))
  throw new Error("0-255 notation not applied: " + document.getElementById("mat-body").innerHTML.slice(0, 400));
setColorMode("float");
if (!document.getElementById("mat-body").innerHTML.includes('value="1.000, 0.200, 0.200"'))
  throw new Error("float notation not applied");
if (localStorage.getItem("atelier.colorMode") !== "float") throw new Error("notation not persisted");
setColorMode("hex");
if (!document.getElementById("mat-body").innerHTML.includes('value="#ff3333"')) throw new Error("hex notation not applied");

// HDR colour: the notation shows the colour normalised by intensity, like the swatch does
if (!document.getElementById("mat-body").innerHTML.includes('value="#ffcc0a"'))
  throw new Error("intensity-normalised hex missing");

// typing a colour writes back through the intensity
matColorText(2, { value: "#00ff00", classList: { add(){}, remove(){} } });
const c = matEditor.colors[2];
if (Math.abs(c.rgba[1] - 2.5) > 1e-6 || c.rgba[0] > 1e-6) throw new Error("text edit ignored intensity: " + c.rgba);

// preview mode renders the other copy
matEditor.dyeView = "preview";
renderMatEditor();
if (!document.getElementById("mat-body").innerHTML.includes("ColorID")) throw new Error("dye preview blurb missing");

// ── MPC editor ───────────────────────────────────────────────────────────────
vfxEditor = { game_rel: "VFX/Params/MPC_Ice", name: "MPC_Ice", kind: "mpc", groups: [],
              scalars: [{ name: "GlowStrength", value: 2.5 }],
              vectors: [{ name: "IceGlow", rgba: [1, 0.8, 0.1, 1], inten: 1 }] };
renderVfxEditor();
const vfxHtml = document.getElementById("vfx-body").innerHTML;
for (const n of ["Vector parameters", "Scalar parameters", "mpcColor(0", "mpcScalar(0", "global",
                 'class="mat-hex"'])
  if (!vfxHtml.includes(n)) throw new Error("MPC editor missing: " + n);
mpcColorText(0, { value: "255 0 0", classList: { add(){}, remove(){} } });
if (vfxEditor.vectors[0].rgba[0] !== 1 || vfxEditor.vectors[0].rgba[1] !== 0)
  throw new Error("MPC colour text edit failed: " + vfxEditor.vectors[0].rgba);

// an empty collection says so instead of rendering an empty panel
vfxEditor.vectors = []; vfxEditor.scalars = [];
if (!renderMpcEditor().includes("no parameters")) throw new Error("empty MPC not handled");

// ── sidebar multi-select ─────────────────────────────────────────────────────
sidebarData = {
  a: { token: "a", game_rel: "UI/T_A", name: "T_A", file_type: "texture", selected: true },
  b: { token: "b", game_rel: "UI/T_B", name: "T_B", file_type: "texture", selected: true },
  c: { token: "c", game_rel: "UI/T_C", name: "T_C", file_type: "texture", selected: false },
};
_sbMarkClick(sidebarData.a, {});
_sbMarkClick(sidebarData.c, { shiftKey: true });
if (_sbMarked.size !== 3) throw new Error("shift-range did not mark a..c: " + [..._sbMarked]);
if (!Object.values(sidebarData).every(i => i.selected === (i.token !== "c")))
  throw new Error("marking changed the export checkboxes");
sbMarkClear();
if (_sbMarked.size !== 0) throw new Error("clear failed");

// ── projects search ──────────────────────────────────────────────────────────
_renderProjectPicker([{ name: "Rocket Recolor", asset_count: 2, mtime: 1 },
                      { name: "Hela UI", asset_count: 1, mtime: 2 }]);
document.getElementById("proj-search").value = "hela";
projSearch();
const cards = document.getElementById("proj-grid").children;
if (cards.length !== 1) throw new Error("projects search matched " + cards.length + " cards");
document.getElementById("proj-search").value = "zzz";
projSearch();
if (!document.getElementById("proj-grid").innerHTML.includes("No project matches"))
  throw new Error("empty search result not reported");

console.log("DOM smoke: all render paths OK");
