// All artwork is Google's locally bundled Material Symbols Sharp, FILL=0.
// Retain the old marker/API as a small compatibility bridge for existing editors.
// No network requests or icon font are needed to render controls.
(() => {
  // Material Symbols Sharp visibility_off, same pinned Google source as the local eye.
  // https://raw.githubusercontent.com/google/material-design-icons/49d4db35df873165d6bd6ba09b063c7dafbac2f4/symbols/web/visibility_off/materialsymbolssharp/visibility_off_24px.svg
  const visibilityOff={"viewBox": "0 -960 960 960", "body": "<path d=\"m644-428-58-58q9-47-27-88t-93-32l-58-58q17-8 34.5-12t37.5-4q75 0 127.5 52.5T660-500q0 20-4 37.5T644-428Zm128 126-58-56q38-29 67.5-63.5T832-500q-50-101-143.5-160.5T480-720q-29 0-57 4t-55 12l-62-62q41-17 84-25.5t90-8.5q151 0 269 83.5T920-500q-23 59-60.5 109.5T772-302Zm20 246L624-222q-35 11-70.5 16.5T480-200q-151 0-269-83.5T40-500q21-53 53-98.5t73-81.5L56-792l56-56 736 736-56 56ZM222-624q-29 26-53 57t-41 67q50 101 143.5 160.5T480-280q20 0 39-2.5t39-5.5l-36-38q-11 3-21 4.5t-21 1.5q-75 0-127.5-52.5T300-500q0-11 1.5-21t4.5-21l-84-82Zm319 93Zm-151 75Z\"/>"};
  function createIcons({ nodes = [document] } = {}) {
    for (const root of nodes) {
      const candidates = [...root.querySelectorAll('i[data-lucide]')];
      if (root.matches?.('i[data-lucide]')) candidates.unshift(root);
      for (const node of candidates) {
        const name = node.dataset.lucide;
        const symbol = ['eye-off','visibility_off'].includes(name) ? visibilityOff : window.AtelierSymbolPaths[name==='visibility'?'eye':name] || window.AtelierSymbolPaths['file-question'];
        const size = Number(node.getAttribute('size') || 20);
        // Large asset artwork uses finer official contours; controls keep a readable weight.
        const artwork = size >= 32 && symbol.large ? symbol.large : symbol;
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        for (const attr of node.attributes) {
          if (!['size', 'class'].includes(attr.name)) svg.setAttribute(attr.name, attr.value);
        }
        svg.setAttribute('viewBox', artwork.viewBox);
        svg.setAttribute('width', node.getAttribute('size') || '20');
        svg.setAttribute('height', node.getAttribute('size') || '20');
        svg.setAttribute('class', `studio-icon lucide ${node.className}`);
        svg.setAttribute('fill', 'currentColor');
        svg.setAttribute('aria-hidden', 'true');
        svg.setAttribute('focusable', 'false');
        // Trusted, vendored SVG path data only; never insert asset names or API data here.
        svg.innerHTML = artwork.body;
        // Category emblems: generated markup is inlined (not an <image>) so the theme's Krackle inks reach it.
        const emblems=window.AtelierCategoryEmblems,category=Object.keys(emblems?.names||{}).find(cls=>node.classList.contains(cls));
        if(category)svg.innerHTML=emblems.markup(category,size>=32?102:24),svg.setAttribute('viewBox','0 0 24 24');
        node.replaceWith(svg);
      }
    }
  }
  window.AtelierIcons = Object.freeze({ createIcons });
  window.lucide = window.AtelierIcons;
})();
