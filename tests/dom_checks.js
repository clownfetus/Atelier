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

console.log("DOM smoke: all render paths OK");
