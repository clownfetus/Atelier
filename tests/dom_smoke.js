// Phase 3 front-end checks. Run via tests/test_phase3.py, or directly:
//     node tests/dom_smoke.js
//
// gui/app.js is a classic script that expects a real DOM, so its render paths cannot be imported.
// This stubs just enough document/localStorage to load the file, then runs tests/dom_checks.js in
// THE SAME context so it can call the app's own functions — asserting what the editors actually
// produce rather than that a string appears in the source. The four Phase 3 UI features are
// covered: #11 region overlay + legend, #16 projects search, #17 colour notation, #18 multi-select.
// Throws on the first failure; prints one line and exits 0 when everything renders.
const fs = require("fs"), path = require("path"), vm = require("vm");
const ROOT = path.join(__dirname, "..");

const sandbox = {};
// Minimal DOM stub: enough to load app.js and drive the render functions.
const els = {};
function mkEl(id) {
  if (els[id]) return els[id];
  const el = {
    id, value: "", textContent: "", _html: "", dataset: {}, style: {}, children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){return false;} },
    addEventListener(){}, removeEventListener(){}, appendChild(c){ this.children.push(c); },
    querySelector(){ return mkEl(id + "-q"); }, querySelectorAll(){ return []; },
    closest(){ return mkEl(id + "-c"); }, scrollIntoView(){}, focus(){}, select(){}, remove(){},
    insertAdjacentHTML(){}, getBoundingClientRect(){ return {top:0,left:0,width:0,height:0}; },
  };
  // innerHTML = "" must also drop appended children, like a real node does
  Object.defineProperty(el, "innerHTML",
    { get(){ return this._html; }, set(v){ this._html = v; this.children.length = 0; } });
  return (els[id] = el);
}
sandbox.document = {
  getElementById: mkEl,
  createElement: () => mkEl("created" + Math.random()),
  addEventListener(){}, querySelectorAll(){ return []; }, querySelector(){ return mkEl("q"); },
  body: mkEl("body"), documentElement: mkEl("html"),
};
sandbox.window = { addEventListener(){}, location: { href: "" }, matchMedia: () => ({matches:false, addEventListener(){}}) };
sandbox.localStorage = { _d:{}, getItem(k){return this._d[k] ?? null;}, setItem(k,v){this._d[k]=String(v);} };
sandbox.lucide = { createIcons(){} };
sandbox.EventSource = class { constructor(){} addEventListener(){} close(){} };
sandbox.fetch = async () => ({ ok:false, json: async()=>({}), blob: async()=>({}) });
sandbox.URL = { createObjectURL: () => "blob:x", revokeObjectURL(){} };
sandbox.CSS = { escape: s => s };
sandbox.setInterval = () => 0;
sandbox.console = console;
sandbox.globalThis = sandbox;
sandbox.clearTimeout = clearTimeout; sandbox.setTimeout = setTimeout;

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(ROOT, "gui", "app.js"), "utf8"), sandbox, { filename: "gui/app.js" });
vm.runInContext(fs.readFileSync(path.join(__dirname, "dom_checks.js"), "utf8"), sandbox, { filename: "tests/dom_checks.js" });
