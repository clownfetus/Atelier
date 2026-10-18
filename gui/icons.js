// All artwork is Google's locally bundled Material Symbols Sharp, FILL=0.
// Retain the old marker/API as a small compatibility bridge for existing editors.
// No network requests or icon font are needed to render controls.
(() => {
  function createIcons({ nodes = [document] } = {}) {
    for (const root of nodes) {
      const candidates = [...root.querySelectorAll('i[data-lucide]')];
      if (root.matches?.('i[data-lucide]')) candidates.unshift(root);
      for (const node of candidates) {
        const name = node.dataset.lucide;
        const symbol = window.AtelierSymbolPaths[name] || window.AtelierSymbolPaths['file-question'];
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
        // D4 candidates: generated emblem markup is inlined (not an <image>) so the theme's Krackle inks reach it.
        const emblems=window.AtelierCategoryEmblems,category=Object.keys(emblems?.names||{}).find(cls=>node.classList.contains(cls));
        if(category&&emblems.enabled())svg.innerHTML=emblems.markup(category,size>=32?102:24),svg.setAttribute('viewBox','0 0 24 24');
        node.replaceWith(svg);
      }
    }
  }
  window.AtelierIcons = Object.freeze({ createIcons });
  window.lucide = window.AtelierIcons;
})();
