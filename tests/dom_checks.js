// Assertions for the Phase 3 UI, evaluated inside dom_smoke.js's context — every identifier below
// (matEditor, renderMatEditor, sidebarData, …) is gui/app.js's own. Throws on the first failure.
(async () => {
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

// ── the intensity split: stored, not re-derived ──────────────────────────────
// The reported bug: a colour typed into a row showing intensity 1.2 was stored as the product, and
// the next open derived max(rgb, 1) = 1 and handed the multiplier back as colour — 10,61,0 read
// back as 12,73,0. Seeding from the stored split is what stops that.
const _typed = [10 / 255 * 1.2, 61 / 255 * 1.2, 0, 1];
setColorMode("255");
const seededOld = _seedColors([{ name: "DynamicLineColor", rgba: _typed }], null);
if (seededOld[0].inten !== 1) throw new Error("no stored split must still derive: " + seededOld[0].inten);
if (fmtColor01(_typed[0], _typed[1], _typed[2]) !== "12, 73, 0")
  throw new Error("the regression itself changed shape: " + fmtColor01(_typed[0], _typed[1], _typed[2]));

const seeded = _seedColors([{ name: "DynamicLineColor", rgba: _typed }], { DynamicLineColor: 1.2 });
if (Math.abs(seeded[0].inten - 1.2) > 1e-9) throw new Error("stored split ignored: " + seeded[0].inten);
const n12 = seeded[0].inten;
if (fmtColor01(_typed[0] / n12, _typed[1] / n12, _typed[2] / n12) !== "10, 61, 0")
  throw new Error("row did not read back what was typed");

// a junk or missing entry falls back to derivation rather than poisoning the row
for (const bad of [{ DynamicLineColor: 0 }, { DynamicLineColor: -2 }, { DynamicLineColor: "1.2" },
                   { Other: 1.2 }, {}])
  if (_seedColors([{ name: "DynamicLineColor", rgba: _typed }], bad)[0].inten !== 1)
    throw new Error("bad stored split not rejected: " + JSON.stringify(bad));

// only a split derivation cannot reproduce is worth storing
if (JSON.stringify(_intenMap(seeded, c => c.name, c => _derivedInten(c.rgba))) !== '{"DynamicLineColor":1.2}')
  throw new Error("the split that would be lost was not sent");
if (Object.keys(_intenMap(seededOld, c => c.name, c => _derivedInten(c.rgba))).length !== 0)
  throw new Error("a derivable split must not be written to the project");
// an HDR value whose peak IS its intensity stays derivable, so nothing is stored for it
const hdr = _seedColors([{ name: "Glow", rgba: [9, 9, 9, 1] }], null);
if (hdr[0].inten !== 9) throw new Error("HDR derivation regressed: " + hdr[0].inten);
if (Object.keys(_intenMap(hdr, c => c.name, c => _derivedInten(c.rgba))).length !== 0)
  throw new Error("an HDR peak must not need storing");
setColorMode("hex");

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

// ── projects: view modes, multi-select, context menu ─────────────────────────
// Cards are appended as nodes, so the markup is read off the children, not the container.
const projGrid  = document.getElementById("proj-grid");
const projCards = () => [...projGrid.children];
const projHtml  = () => projCards().map(c => c.innerHTML).join("");
_renderProjectPicker([{ name: "Rocket Recolor", asset_count: 2, mtime: 1 },
                      { name: "Hela UI", asset_count: 1, mtime: 2 }]);

// grid view: the tick is in the markup (CSS reveals it on hover), one per card
setProjView("grid");
if (projCards().some(c => c.className !== "proj-card")) throw new Error("grid view did not render cards");
if ((projHtml().match(/class="proj-check"/g) || []).length !== 2)
  throw new Error("grid cards are missing the hover checkbox");

// list view: rows, with the tick first — the leftmost column, before the thumbnail
setProjView("list");
if (projGrid.className !== "proj-list-mode") throw new Error("list view class not applied");
if (projCards().some(c => c.className !== "proj-row")) throw new Error("list view did not render rows");
for (const c of projCards()) {
  const check = c.innerHTML.indexOf("proj-check"), thumb = c.innerHTML.indexOf("proj-thumb");
  if (check < 0 || thumb < 0 || check > thumb)
    throw new Error("the list checkbox must come first, in the leftmost column");
}
if (_store.get("atelier.projView") !== "list") throw new Error("view mode not persisted");

// ticking: a click on the box selects without opening; shift extends over what is visible
_projSelClick("Hela UI", {});
if (_projSel.size !== 1 || !_projSel.has("Hela UI")) throw new Error("checkbox did not select");
if (!projCards().some(c => c.className.includes("sel"))) throw new Error("selected row not marked");
if (!document.getElementById("proj-selbar").innerHTML.includes("1 selected"))
  throw new Error("the selection bar does not report the count");
_projSelClick("Rocket Recolor", { shiftKey: true });
if (_projSel.size !== 2) throw new Error("shift-range did not extend: " + [..._projSel]);

// the context menu acts on the whole selection when the target is part of it
const ctxMany = _ctxItemsProject({ name: "Hela UI", asset_count: 1 }).filter(i => i !== "sep");
if (!ctxMany.some(i => i.label === "Export 2 projects…") ||
    !ctxMany.some(i => i.label === "Delete 2 projects…"))
  throw new Error("bulk context menu missing Export/Delete: " + ctxMany.map(i => i.label));

// …and on one project alone when it is not
projSelClear();
if (_projSel.size !== 0) throw new Error("clear failed");
const ctxOne = _ctxItemsProject({ name: "Hela UI", asset_count: 1 }).filter(i => i !== "sep");
for (const l of ["Open", "Rename…", "Duplicate…", "Export…", "Delete…"])
  if (!ctxOne.some(i => i.label === l)) throw new Error("single context menu missing " + l);

// both destructive-looking actions stop at a confirmation that names what it will act on
_projDeleteConfirm(["Hela UI", "Rocket Recolor"]);
const delMsg = document.getElementById("proj-delete-msg").textContent;
if (!/Delete these 2 projects/.test(delMsg) || !delMsg.includes("3 edited assets"))
  throw new Error("bulk delete confirmation does not add up: " + delMsg);
if (!delMsg.includes("Hela UI") || !delMsg.includes("Rocket Recolor"))
  throw new Error("the delete confirmation must name the projects");
if (_projDeleteNames.length !== 2) throw new Error("delete confirmation did not hold the names");

_projExportConfirm(["Hela UI"]);
const expMsg = document.getElementById("proj-export-msg").textContent;
if (!expMsg.includes('"Hela UI"') || !expMsg.includes("1 edited asset"))
  throw new Error("export confirmation does not name the project: " + expMsg);
if (!/Nothing is changed or removed/.test(expMsg))
  throw new Error("export must say it leaves the project alone");
if (_projExportNames.length !== 1) throw new Error("export confirmation did not hold the names");

// a project filtered out of view drops out of the selection — a bulk action can only ever
// reach what the user can see
_projSelClick("Hela UI", {});
_projSelClick("Rocket Recolor", {});
document.getElementById("proj-search").value = "hela";
projSearch();
if (_projSel.size !== 1 || !_projSel.has("Hela UI"))
  throw new Error("search must narrow the selection to the visible rows: " + [..._projSel]);
document.getElementById("proj-search").value = "";
projSelClear();
setProjView("grid");

// ── Phase 4: per-asset export options (#20 mips/group, #21 Marvel_LQ, #22 remove) ───────────
// The controls are only worth having if they say what they will actually do to THIS asset, so
// that is what is asserted: the two cases where the honest answer is "not what you might expect".
texOpts = { game_rel: "UI/T_A", name: "T_A", opts: {},
            info: { groups: ["TEXTUREGROUP_UI", "TEXTUREGROUP_Character"],
                    current_group: "TEXTUREGROUP_Character", has_lq: false,
                    format: "DXT1", blank_alpha: false } };
renderTexOpts();
// the help text is a wrapped template literal, so compare against flattened whitespace
const flat = () => document.getElementById("texopt-body").innerHTML.replace(/\s+/g, " ");
let oh = flat();
if (!oh.includes("opaque black") || !oh.includes("DXT1"))
  throw new Error("a format with no alpha must not be offered as 'transparent'");
if (!oh.includes("Your paks have no Marvel_LQ mount"))
  throw new Error("the LQ control must explain why it is off");
if (!oh.includes("disabled")) throw new Error("the LQ control must be disabled without the mount");
if (!oh.includes("Unchanged (Character)")) throw new Error("the group dropdown must start unchanged");

texOpts.info.blank_alpha = true; texOpts.info.format = "DXT5"; texOpts.info.has_lq = true;
texOptSet("blank", true);
oh = flat();
if (oh.includes("opaque black")) throw new Error("a format WITH alpha was described as black");
if (!oh.includes("fully transparent")) throw new Error("the honest blank case lost its wording");
if (texOpts.opts.blank !== true) throw new Error("the toggle did not record");
texOptSet("blank", false);
if ("blank" in texOpts.opts) throw new Error("switching off must remove, not store false");

// the badge: an altered export has to be visible on the asset in the sidebar
if (_sbOptBadge({ opts: {} }) !== "") throw new Error("a plain asset must carry no badge");
const badge = _sbOptBadge({ opts: { blank: true, lod_group: "TEXTUREGROUP_UI" } });
if (!badge.includes("blank") || !badge.includes("UI"))
  throw new Error("the badge does not name the options: " + badge);

// ── Phase 4: the dye-off toggle (#12) and the whole-set download (#23) ──────────────────────
// colors/scalars left empty on purpose: a dyeing material whose Region params are not exposed
// still has a preview and a toggle, and the "no editable parameters" note must not replace them.
matEditor = { game_rel: "C/MI_X", name: "MI_X", colors: [], scalars: [],
              dyeable: true, dyeView: "preview", dyeUsed: ["1"], dyeOff: false,
              dyeMask: "Textures/T_X_ColorID",
              dyeInfo: { used: { "0": 5, "1": 5 }, coverage: { "0": 50, "1": 50 },
                         overlay: { "0": "#888", "1": "#f00" }, regions: {} } };
renderMatEditor();
let mh = document.getElementById("mat-body").innerHTML.replace(/\s+/g, " ");
if (!mh.includes("turn this skin's dyeing off"))
  throw new Error("the dye-off toggle is missing from a dyeing material: ");
if (!mh.includes("T_X_ColorID"))
  throw new Error("the toggle must name the asset it adds to the mod");
if (!mh.includes("Download all textures"))
  throw new Error("#23's button is missing");
matEditor.dyeOff = true;
renderMatEditor();
mh = document.getElementById("mat-body").innerHTML.replace(/\s+/g, " ");
if (!/toggle-row on/.test(mh)) throw new Error("the toggle does not reflect its own state");
if (!mh.includes("no editable color or scalar parameters"))
  throw new Error("the empty-parameter note went missing");

// ── curve / VFX / level / text editors: unsaved drafts and destructive resets ─────────────────
// Closing with unsaved edits must ask before discarding them, and Reset (which deletes the
// project's saved sidecar) and Revert must ask before doing anything — as the material editor does.
{
  const prompts = []; let answer = false; let apiCalls = 0;
  globalThis.AtelierDialog = {confirm: async ({body}) => { prompts.push(body); return answer; }};
  const realApi = api;
  api = async path => { if (/reset|revert_imported/.test(path)) apiCalls++; return { ok: false, error: "stub" }; };

  curveEditor = { game_rel: "Fx/Curve", name: "Curve", channels: {}, stops: [], dirty: {} };
  if (await closeCurveEditor() !== true || prompts.length) throw new Error("a clean curve editor must close without asking");
  curveEditor = { game_rel: "Fx/Curve", name: "Curve", channels: {}, stops: [], dirty: { R: true } };
  if (await closeCurveEditor() !== false || !curveEditor) throw new Error("declining must keep an edited curve open");
  answer = true;
  if (await closeCurveEditor() !== true || curveEditor) throw new Error("accepting must close the edited curve");
  answer = false;

  vfxEditor = { game_rel: "Fx/NS", name: "NS", groups: [{ stops: [0] }], scalars: [], vectors: [] };
  vfxEditor.baseline = _vfxSnapshot(vfxEditor);
  if (_vfxDirty()) throw new Error("a freshly loaded VFX editor must not be dirty");
  vfxEditor.groups[0].stops.push(1);
  if (!_vfxDirty() || await closeVfxEditor() !== false || !vfxEditor) throw new Error("an edited VFX draft closed silently");
  if (await closeVfxEditor(true) !== true || vfxEditor) throw new Error("a forced VFX close (after save) must not ask");

  worldEditor = { game_rel: "Maps/L", name: "L", edits: { lights: {}, fog: {}, grade: {}, visibility: {} } };
  worldEditor.baseline = _editSnapshot(worldEditor.edits);
  worldEditor.edits.fog.density = 0.2;
  if (await closeWorldEditor() !== false) throw new Error("edited level lighting closed silently");
  worldEditor.baseline = _editSnapshot(worldEditor.edits);
  const before = prompts.length;
  if (await closeWorldEditor() !== true || prompts.length !== before) throw new Error("a saved level editor must close without asking");

  textEditor = { game_rel: "Text/ST", name: "ST", entries: [], edits: {} };
  textEditor.baseline = _editSnapshot(textEditor.edits);
  textEditor.edits.KEY = "changed";
  if (await closeTextEditor() !== false) throw new Error("edited strings closed silently");

  curveEditor = { game_rel: "Fx/Curve", name: "Curve", channels: {}, stops: [], dirty: {} };
  vfxEditor = { game_rel: "Fx/NS", name: "NS", groups: [], scalars: [], vectors: [] };
  await resetCurve(); await resetVfx();
  await revertImported({ name: "T_Painted", game_rel: "Fixture/T_Painted", token: "kept" });
  if (apiCalls) throw new Error("a declined Reset/Revert still reached the server");
  if (!prompts.some(p => p.includes("T_Painted"))) throw new Error("the revert prompt must name the asset");

  api = realApi; curveEditor = vfxEditor = worldEditor = textEditor = null;
  delete globalThis.AtelierDialog;
}

// ── material texture slots: a slot can take the user's own image as a new texture ─────────────
await (async () => {
  const realApi = api, realFetch = projectFetch;
  matEditor = { game_rel: "Characters/1015/MI_Body", name: "MI_Body", colors: [], scalars: [],
                textures: { Normal: "Characters/1015/T_Body_N", BaseColor: "Characters/1015/T_Body_D",
                            Env: "Env/T_<Cube>" },
                textureClasses: { Normal: "Texture2D", BaseColor: "Texture2D", Env: "TextureCube" },
                custom: { BaseColor: { name: "T_Hood", file: "0123456789abcdef0123.png", source: "Hood <1>.png",
                                       size: [1024, 512], game_rel: "Atelier/Custom/k/T_Hood" } } };
  renderMatEditor();
  let th = document.getElementById("mat-body").innerHTML.replace(/\s+/g, " ");
  if (!th.includes("Texture slots") || !th.includes("1 of 3 using your images"))
    throw new Error("the texture slot group is missing or miscounted");
  if (th.indexOf(">BaseColor<") > th.indexOf(">Env<") || th.indexOf(">Env<") > th.indexOf(">Normal<"))
    throw new Error("slots must be listed in a stable, sorted order");
  if (!th.includes("T_Hood") || !th.includes("1024×512") || !th.includes("Use game texture") || !th.includes("Change image…"))
    throw new Error("a slot using the user's image must name it and offer to change or remove it");
  if (!th.includes("material_custom_texture/preview") || !th.includes("v=0123456789abcdef0123.png"))
    throw new Error("a custom slot must preview the stored image, cache-busted by its content hash");
  if (!th.includes("Use my own image…") || !th.includes("T_Body_N"))
    throw new Error("a game-texture slot must name its texture and offer an image");
  if (!th.includes("Use my HDR cubemap…") || !th.includes("all six faces and HDR values"))
    throw new Error("a cubemap slot must offer HDR input and explain the preserved faces and range");
  if (th.includes("Hood <1>") || th.includes("T_<Cube>"))
    throw new Error("asset and file names must be escaped");

  // Choosing a file uploads it for that slot and re-renders from the server's answer.
  const sent = [];
  globalThis.FormData = class { constructor() { this.parts = {}; } append(k, v) { this.parts[k] = v; } };
  projectFetch = async (path, opts = {}) => {
    if (path !== "/api/material_custom_texture") return { json: async () => [] };   // the sidebar refresh's empty list
    sent.push([path, opts.body.parts]);
    return { json: async () => ({ ok: true, custom_textures: { ...matEditor.custom,
      Normal: { name: "T_Scales", file: "abcdef0123456789abcd.png", size: [512, 512], game_rel: "Atelier/Custom/n/T_Scales" } } }) }; };
  _matTexInput.click = () => {};                 // the stub element has no file dialog
  matCustomTexturePick(1);                       // Env is a cubemap
  if (_matTexInput.accept !== '.hdr,.dds') throw new Error('cubemap selection must request HDR or DDS');
  matCustomTexturePick(2);                       // sorted: BaseColor, Env, Normal
  if (_matTexInput.accept.includes('.hdr')) throw new Error('2D selection must retain its image formats');
  await matCustomTextureUpload(_matTexTarget, { name: "scales.png" });
  if (sent.length !== 1 || sent[0][0] !== "/api/material_custom_texture" || sent[0][1].slot !== "Normal"
      || sent[0][1].game_rel !== "Characters/1015/MI_Body")
    throw new Error("the upload must name the material and the chosen slot");
  if (!matEditor.custom.Normal || !document.getElementById("mat-body").innerHTML.includes("T_Scales"))
    throw new Error("the editor must show the newly assigned image");

  // Removing asks first; declining sends nothing.
  const prompts = []; let answer = false, cleared = [];
  globalThis.AtelierDialog = {confirm: async ({body}) => { prompts.push(body); return answer; }};
  api = async (path, opts = {}) => {
    if (path !== "/api/material_custom_texture/clear") return [];
    cleared.push([path, JSON.parse(opts.body)]);
    return { ok: true, custom_textures: { BaseColor: matEditor.custom.BaseColor } };
  };
  await matCustomTextureClear(2);
  if (cleared.length || !prompts[0].includes("Normal") || !prompts[0].includes("T_Scales"))
    throw new Error("removing an image must ask first, naming the slot and image");
  answer = true;
  await matCustomTextureClear(2);
  if (cleared.length !== 1 || cleared[0][0] !== "/api/material_custom_texture/clear" || cleared[0][1].slot !== "Normal"
      || matEditor.custom.Normal)
    throw new Error("an accepted removal must clear that slot only");
  await matCustomTextureClear(1);                // Env has no image: nothing to remove
  if (cleared.length !== 1) throw new Error("a slot without an image must not send a removal");

  // Restoring game defaults warns that the user's images go too.
  answer = false; prompts.length = 0;
  await resetMaterial();
  if (!prompts[0] || !prompts[0].includes("image is also removed from its texture slots"))
    throw new Error("the reset prompt must mention the images it removes");

  api = realApi; projectFetch = realFetch; delete globalThis.AtelierDialog; delete globalThis.FormData;
  matEditor = null;
  console.log("DOM smoke: all render paths OK");
})();   // a rejection here is unhandled, so node exits non-zero with the error
})();
