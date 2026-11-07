// Moves a colour's lightness until it reads on a surface, holding its hue and saturation.
// Transfer conventions: https://www.w3.org/TR/css-color-4/#color-conversion-code
(() => {
  'use strict';
  const clamp = (n, a = 0, b = 1) => Math.max(a, Math.min(b, n));
  function rgb(value) {
    let match = /^#([\da-f]{3}|[\da-f]{6})$/i.exec(String(value).trim());
    if (match) {
      const digits = match[1].length === 3 ? [...match[1]].map(c => c + c).join('') : match[1];
      return digits.match(/../g).map(n => parseInt(n, 16));
    }
    match = /^rgba?\(\s*([\d.]+)[, ]+\s*([\d.]+)[, ]+\s*([\d.]+)/.exec(String(value));
    if (match) return match.slice(1).map(n => clamp(+n, 0, 255));
    throw Error('Expected an sRGB colour.');
  }
  const hex = color => '#' + rgb(color).map(n => Math.round(n).toString(16).padStart(2, '0')).join('');
  const linear = n => { n /= 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4; };
  const luminance = color => rgb(color).map(linear).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
  const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);
  function hsl(color) {
    const [r, g, b] = rgb(color).map(n => n / 255), max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min, l = (max + min) / 2;
    const h = !d ? 0 : max === r ? ((g - b) / d + 6) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h * 60, d ? d / (1 - Math.abs(2 * l - 1)) : 0, l];
  }
  function fromHsl(h, s, l) {
    const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs(h / 60 % 2 - 1)), m = l - c / 2;
    const values = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
    return '#' + values.map(n => Math.round((n + m) * 255).toString(16).padStart(2, '0')).join('');
  }
  // The smallest lightness move that reaches the target. A colour already there comes back unchanged.
  function fit(color, surface, target = 3) {
    color = hex(color);
    if (contrast(color, surface) >= target) return color;
    const [h, s, l] = hsl(color), dark = luminance(surface) < .179;
    let low = 0, high = 1, result = dark ? '#ffffff' : '#000000';
    for (let i = 0; i < 18; i++) {
      const t = (low + high) / 2, candidate = fromHsl(h, s, clamp(l + (dark ? 1 - l : -l) * t));
      if (contrast(candidate, surface) >= target) { result = candidate; high = t; } else low = t;
    }
    return result;
  }
  window.AtelierColourFit = Object.freeze({ fit, contrast });
})();
