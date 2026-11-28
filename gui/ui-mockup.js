/**
 * Lazy-loaded HUD frame mockup overlays for Texture Preview.
 * Only imported when the user activates "HUD frame" on a UI texture.
 */

const UI_PATH_RE = /(?:^|\/)(?:ui|nameplates?|sprays?|crosshairs?|reticles?)(?:\/|$)|(?:nameplateframe|playerheadframe|herohead|herogallery|killicon|item_kill|item_herohead|lordicon|abilityicon|skillicon|crosshair|reticle)/i;

export const HUD_PRESETS = Object.freeze([
  {
    id: 'portrait',
    label: 'Hero portrait (circle)',
    hint: 'Circular avatar & scoreboard crop · outer shaded ring is clipped in game',
    aspect: 1,
    svg: `
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <mask id="hud-mask-portrait">
            <rect width="100" height="100" fill="white"/>
            <circle cx="50" cy="50" r="44" fill="black"/>
          </mask>
        </defs>
        <rect width="100" height="100" fill="rgba(8,12,18,0.68)" mask="url(#hud-mask-portrait)"/>
        <circle cx="50" cy="50" r="44" fill="none" stroke="rgba(255,255,255,0.9)" stroke-width="0.9"/>
        <circle cx="50" cy="50" r="39" fill="none" stroke="rgba(255,255,255,0.45)" stroke-width="0.5" stroke-dasharray="2.5 2"/>
        <line x1="47" y1="50" x2="53" y2="50" stroke="rgba(255,255,255,0.55)" stroke-width="0.5"/>
        <line x1="50" y1="47" x2="50" y2="53" stroke="rgba(255,255,255,0.55)" stroke-width="0.5"/>
      </svg>`,
  },
  {
    id: 'hero-tile',
    label: 'Hero select tile',
    hint: 'Slanted hero-select card with bottom name bar safe zone',
    aspect: 0.72,
    svg: `
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <mask id="hud-mask-tile">
            <rect width="100" height="100" fill="white"/>
            <polygon points="10,4 94,4 90,96 6,96" fill="black"/>
          </mask>
        </defs>
        <rect width="100" height="100" fill="rgba(8,12,18,0.68)" mask="url(#hud-mask-tile)"/>
        <polygon points="10,4 94,4 90,96 6,96" fill="none" stroke="rgba(255,255,255,0.9)" stroke-width="0.9"/>
        <polygon points="7,78 91,78 90,96 6,96" fill="rgba(8,12,18,0.52)" stroke="rgba(255,255,255,0.45)" stroke-width="0.5" stroke-dasharray="2 2"/>
        <text x="50" y="90" text-anchor="middle" fill="rgba(255,255,255,0.82)" font-size="5.5" font-weight="600" font-family="Inter, sans-serif">NAMEPLATE SAFE ZONE</text>
      </svg>`,
  },
  {
    id: 'nameplate',
    label: 'Nameplate banner',
    hint: 'Left avatar cutout & right player title band',
    aspect: 3.6,
    svg: `
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <rect x="2" y="8" width="96" height="84" fill="none" stroke="rgba(255,255,255,0.9)" stroke-width="0.9"/>
        <rect x="4" y="14" width="20" height="72" rx="2" fill="rgba(8,12,18,0.45)" stroke="rgba(255,255,255,0.55)" stroke-width="0.6" stroke-dasharray="2 2"/>
        <rect x="27" y="54" width="66" height="28" rx="1.5" fill="rgba(8,12,18,0.42)" stroke="rgba(255,255,255,0.45)" stroke-width="0.5" stroke-dasharray="2 2"/>
        <text x="14" y="53" text-anchor="middle" fill="rgba(255,255,255,0.8)" font-size="5" font-family="Inter, sans-serif">AVATAR</text>
        <text x="60" y="71" text-anchor="middle" fill="rgba(255,255,255,0.8)" font-size="5" font-family="Inter, sans-serif">PLAYER NAME / TITLE</text>
      </svg>`,
  },
  {
    id: 'ability',
    label: 'Ability / HUD icon',
    hint: 'Bottom-right ability slot with keybind badge area',
    aspect: 1,
    svg: `
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <mask id="hud-mask-ability">
            <rect width="100" height="100" fill="white"/>
            <polygon points="14,6 86,6 94,14 94,86 86,94 14,94 6,86 6,14" fill="black"/>
          </mask>
        </defs>
        <rect width="100" height="100" fill="rgba(8,12,18,0.62)" mask="url(#hud-mask-ability)"/>
        <polygon points="14,6 86,6 94,14 94,86 86,94 14,94 6,86 6,14" fill="none" stroke="rgba(255,255,255,0.9)" stroke-width="0.9"/>
        <rect x="16" y="16" width="68" height="68" fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="0.5" stroke-dasharray="2 2"/>
        <rect x="34" y="81" width="32" height="13" rx="2" fill="rgba(8,12,18,0.75)" stroke="rgba(255,255,255,0.75)" stroke-width="0.6"/>
        <text x="50" y="90" text-anchor="middle" fill="rgba(255,255,255,0.9)" font-size="6" font-weight="600" font-family="Inter, sans-serif">KEY</text>
      </svg>`,
  },
  {
    id: 'killfeed',
    label: 'KO feed icon',
    hint: 'Compact horizontal kill-feed framing',
    aspect: 1.6,
    svg: `
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <mask id="hud-mask-ko">
            <rect width="100" height="100" fill="white"/>
            <polygon points="8,18 96,18 92,82 4,82" fill="black"/>
          </mask>
        </defs>
        <rect width="100" height="100" fill="rgba(8,12,18,0.68)" mask="url(#hud-mask-ko)"/>
        <polygon points="8,18 96,18 92,82 4,82" fill="none" stroke="rgba(255,255,255,0.9)" stroke-width="0.9"/>
      </svg>`,
  },
  {
    id: 'crosshair',
    label: 'Crosshair / reticle',
    hint: 'Exact centre pixel axes and concentric sight rings',
    aspect: 1,
    svg: `
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <line x1="50" y1="0" x2="50" y2="100" stroke="rgba(255,255,255,0.45)" stroke-width="0.45" stroke-dasharray="2 2"/>
        <line x1="0" y1="50" x2="100" y2="50" stroke="rgba(255,255,255,0.45)" stroke-width="0.45" stroke-dasharray="2 2"/>
        <circle cx="50" cy="50" r="10" fill="none" stroke="rgba(255,255,255,0.7)" stroke-width="0.6"/>
        <circle cx="50" cy="50" r="24" fill="none" stroke="rgba(255,255,255,0.5)" stroke-width="0.5" stroke-dasharray="2 2"/>
        <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="0.5" stroke-dasharray="3 3"/>
      </svg>`,
  },
  {
    id: 'spray',
    label: 'Spray safe zone',
    hint: 'Circular wall-spray safe boundary',
    aspect: 1,
    svg: `
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <circle cx="50" cy="50" r="46" fill="none" stroke="rgba(255,255,255,0.85)" stroke-width="0.8" stroke-dasharray="3 2"/>
        <rect x="8" y="8" width="84" height="84" fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="0.5"/>
      </svg>`,
  },
]);

export function isUiTexturePath(path) {
  return UI_PATH_RE.test(String(path || '').replace(/\\/g, '/'));
}

export function defaultPresetForPath(path) {
  const norm = String(path || '').replace(/\\/g, '/').toLowerCase();
  if (/nameplateframe|banner/.test(norm)) return 'nameplate';
  if (/playerheadframe|herohead|avatar|lord/.test(norm)) return 'portrait';
  if (/crosshair|reticle/.test(norm)) return 'crosshair';
  if (/killicon|item_kill|killfeed/.test(norm)) return 'killfeed';
  if (/spray/.test(norm)) return 'spray';
  if (/ability|skill|marvelgas|hud_?icon/.test(norm)) return 'ability';
  if (/herogallery|portrait|prestige|story|select/.test(norm)) return 'hero-tile';
  return 'portrait';
}

export function getHudPreset(id) {
  return HUD_PRESETS.find(preset => preset.id === id) || HUD_PRESETS[0];
}

export function aspectHint(preset, width, height) {
  if (!preset || !width || !height) return preset?.hint || '';
  const actual = width / height;
  const ratioDiff = Math.abs(actual - preset.aspect) / Math.max(actual, preset.aspect);
  if (ratioDiff > 0.35) {
    return `${preset.hint} · Texture is ${width}×${height} (check crop/aspect)`;
  }
  return preset.hint;
}

export function renderHudOverlay(host, presetId, width = 0, height = 0) {
  if (!host) return null;
  const preset = getHudPreset(presetId);
  host.innerHTML = preset.svg;
  host.dataset.preset = preset.id;
  return { preset, caption: aspectHint(preset, width, height) };
}
