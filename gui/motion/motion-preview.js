// Settings samples use the very same finite formations as the workspace.
(() => {
  'use strict';
  const control = document.getElementById('settings-motion');
  if (!control || !window.AtelierMotion?.workflow) return;

  const panel = document.createElement('div');
  panel.className = 'k-motion-preview';
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-label', 'Krackle motion preview');
  const heading = document.createElement('div');
  heading.className = 'k-motion-preview-heading';
  const title = document.createElement('strong'); title.textContent = 'Try Krackle';
  const badge = document.createElement('span'); badge.className = 'k-motion-preview-mode';
  heading.append(title, badge);
  const note = document.createElement('p');
  note.className = 'k-motion-preview-description'; note.textContent = 'Little gestures drawn into the edges, in your hero or costume colours. Tap one to replay.';
  const samples = document.createElement('div'); samples.className = 'k-motion-samples';
  const buttons = [];
  const handoff = document.createElement('button');
  handoff.type = 'button'; handoff.className = 'k-motion-handoff';
  handoff.setAttribute('aria-label', 'Replay ink handoff');
  const handoffTitle = document.createElement('span'); handoffTitle.className = 'k-motion-handoff-title';
  handoffTitle.textContent = 'Replay ink handoff';
  const handoffSurfaces = [];
  for (const [label, icon] of [['Edit', 'file-box'], ['Mod tray', 'package']]) {
    const item = document.createElement('span'); item.className = 'k-motion-handoff-item';
    const surface = document.createElement('span'); surface.className = 'k-motion-sample-art';
    surface.setAttribute('aria-hidden', 'true');
    const glyph = document.createElement('i'); glyph.dataset.lucide = icon; surface.append(glyph);
    const caption = document.createElement('span'); caption.textContent = label;
    item.append(surface, caption); handoff.append(item); handoffSurfaces.push(surface);
  }
  const handoffNote = document.createElement('span'); handoffNote.className = 'k-motion-handoff-note';
  handoffNote.textContent = 'Ink gathers at your edit, flows into the tray, then catches its edge.';
  handoff.prepend(handoffTitle); handoff.append(handoffNote); buttons.push(handoff);
  handoff.addEventListener('click', () => {
    window.AtelierMotion.workflow.stop();
    window.AtelierMotion.workflow.transfer(handoffSurfaces[0], handoffSurfaces[1], 'arrival');
  });
  for (const [kind, label, icon, description] of [
    ['arrive', 'Arrive', 'user', 'Rails rise to greet a hero, editor or panel.'],
    ['trace', 'Trace', 'folder', 'A seam follows the way you moved.'],
    ['seal', 'Seal', 'check', 'Two jaws close on a pin, choice or action.'],
    ['release', 'Release', 'pin-off', 'The same seal unwinds when you undo.'],
  ]) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'k-motion-sample'; button.dataset.motionSample = kind;
    button.setAttribute('aria-label', 'Preview ' + label.toLowerCase());
    const art = document.createElement('span'); art.className = 'k-motion-sample-art';
    art.setAttribute('aria-hidden', 'true');
    if (kind === 'arrive') {
      const image = document.createElement('img'); image.src = '/static/brand/atelier-mark.png';
      image.alt = ''; image.width = image.height = 28; art.append(image);
    } else {
      const glyph = document.createElement('i'); glyph.dataset.lucide = icon; art.append(glyph);
    }
    const caption = document.createElement('span'); caption.className = 'k-motion-sample-caption'; caption.textContent = label;
    const detail = document.createElement('span'); detail.className = 'k-motion-sample-description'; detail.textContent = description;
    button.append(art, caption, detail); samples.append(button); buttons.push(button);
    button.addEventListener('click', () => {
      // Previews never start a job, touch a project, or queue an automatic replay.
      window.AtelierMotion.workflow.stop();
      window.AtelierMotion.workflow[kind](art);
    });
  }
  panel.append(heading, note, handoff, samples); control.closest('.setup-field').append(panel);
  const sync = () => {
    const mode = window.AtelierMotionPolicy?.mode() || 'off';
    badge.textContent = mode === 'full' ? 'Full' : mode === 'calm' ? 'Calm' : 'Still';
    for (const button of buttons) button.disabled = mode === 'off';
  };
  window.AtelierMotionPolicy?.query().addEventListener('change', sync);
  sync();
  window.addEventListener('pagehide', () => window.AtelierMotionPolicy?.query().removeEventListener('change', sync), {once: true});
})();
