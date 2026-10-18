// Shared motion timing. Load after tokens.css and before the motion controllers.
(() => {
  'use strict';
  const motion = window.AtelierMotion ||= {};
  const tokens = getComputedStyle(document.documentElement);
  function milliseconds(name, fallback) {
    const value = tokens.getPropertyValue(name).trim();
    const amount = parseFloat(value) * (value.endsWith('ms') ? 1 : 1000);
    return Number.isFinite(amount) && amount > 0 ? amount : fallback;
  }
  motion.beatMs = milliseconds('--krackle-beat', 1040);
  motion.exitMs = milliseconds('--studio-motion-exit', 120);
  motion.ease = Object.freeze({
    standard: tokens.getPropertyValue('--studio-easing').trim() || 'cubic-bezier(0.2, 0, 0, 1)',
    exit: tokens.getPropertyValue('--studio-easing-exit').trim() || 'cubic-bezier(0.3, 0, 1, 1)',
    fall: 'cubic-bezier(0.55, 0, 1, 0.45)',
    rise: 'cubic-bezier(0, 0.55, 0.45, 1)',
    sway: 'cubic-bezier(0.45, 0, 0.55, 1)',
    turn: 'cubic-bezier(0.42, 0, 0.58, 1)',
  });
})();
