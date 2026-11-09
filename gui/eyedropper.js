// A pipette beside every colour swatch. The picker's own eyedropper leaves the picker open, and
// Escape there cancels and restores the old colour, so a pick could be lost. This button picks
// from anywhere on screen and applies the colour straight away, through the swatch's own input
// and change handlers. Only where the engine offers EyeDropper (Windows desktop and Edge, not
// Linux WebKitGTK); elsewhere nothing is added.
(() => {
  if (!('EyeDropper' in window)) return;
  const LABEL = 'Pick a colour from the screen';
  let picking = false;

  function enhance(input) {
    if (input.dataset.eyedropper || input.hidden || input.disabled) return;
    input.dataset.eyedropper = 'ready';
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'eyedropper-btn';
    button.title = LABEL; button.setAttribute('aria-label', LABEL);
    button.setAttribute('aria-pressed', 'false');
    const icon = document.createElement('i'); icon.dataset.lucide = 'pipette'; icon.setAttribute('size', '16');
    button.append(icon);
    // The material editor wraps its swatch in a checkerboard well; the button sits beside the well.
    // Theme rows show the hex in an <output> that theme.js finds as the swatch's next sibling.
    let anchor = input.parentElement?.classList.contains('mat-color-well') ? input.parentElement : input;
    if (anchor.nextElementSibling?.tagName === 'OUTPUT') anchor = anchor.nextElementSibling;
    anchor.after(button);
    window.AtelierIcons?.createIcons({nodes: [button]});
    button.addEventListener('click', () => pick(input, button));
  }

  async function pick(input, button) {
    if (picking || !input.isConnected) return;
    picking = true; button.setAttribute('aria-pressed', 'true');
    try {
      const {sRGBHex} = await new EyeDropper().open();
      if (!/^#[0-9a-f]{6}$/i.test(sRGBHex) || !input.isConnected) return;
      input.value = sRGBHex.toLowerCase();
      input.dispatchEvent(new Event('input', {bubbles: true}));
      input.dispatchEvent(new Event('change', {bubbles: true}));
    } catch (_) {
      // Escape or a second picker cancels; the swatch keeps its colour.
    } finally {
      picking = false; button.setAttribute('aria-pressed', 'false');
    }
  }

  function scan(root) {
    if (root.matches?.('input[type=color]')) enhance(root);
    root.querySelectorAll?.('input[type=color]').forEach(enhance);
  }

  function start() {
    scan(document.body);
    new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) if (node.nodeType === 1) scan(node);
    }).observe(document.body, {childList: true, subtree: true});
  }
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start, {once: true});
  window.AtelierEyedropper = Object.freeze({enhance});
})();
