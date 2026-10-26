/* LUT math shared by Motionboard's timeline and its deliberately limited proxy. */
(function (root) {
  'use strict';
  const roles = ['color', 'opacity', 'scale', 'emission', 'rate'];
  const clamp = (x, low = 0, high = 1) => Math.max(low, Math.min(high, x));
  const key = group => (group.export_indices || []).slice().sort((a, b) => a - b).join(',') || 'group:' + group.group_id;
  function sample(stops, time) {
    if (!stops?.length) return [];
    const position = clamp(time) * (stops.length - 1), index = Math.floor(position), next = Math.min(index + 1, stops.length - 1);
    return stops[index].map((value, channel) => Number(value) + (Number(stops[next][channel]) - Number(value)) * (position - index));
  }
  function equal(a, b) {
    return !!a && !!b && a.length === b.length && a.every((s, i) => s.length === b[i].length && s.every((v, c) => v === b[i][c]));
  }
  const modified = g => !g.restore_original && (g.has_saved_edit || !equal(g.stops, g.original_stops));
  const original = g => g.original_samples || g.original_stops || null;
  const edited = g => !modified(g) && original(g) ? original(g) : g.stops;
  const allowed = (role, g) => ({color: g.channels >= 3, opacity: [1, 4].includes(g.channels),
    scale: g.channels <= 3, emission: g.channels === 1 || g.channels >= 3, rate: g.channels === 1})[role];
  function namedRole(name, channels) {
    // Only inspect the module/input portion of an actual ResolvedDataInterfaces
    // binding. An emitter's name or an owner fallback cannot establish meaning.
    const text = name.split('.').slice(-2).join(' ').replace(/[0-9_\s]/g, '').toLowerCase();
    if (/spawnrate|spawncount|spawnburst|emissionrate/.test(text) && channels === 1) return 'rate';
    if (/opacity|alphascale|alphacurve|scalealpha/.test(text) && [1, 4].includes(channels)) return 'opacity';
    if (/spritesize|spritescale|meshscale|meshsize|uniformscale/.test(text) && channels <= 3) return 'scale';
    if (/emissive|emissioncolor|emissionintensity/.test(text) && (channels === 1 || channels >= 3)) return 'emission';
    if (/color|colour|tint/.test(text) && channels >= 3) return 'color';
    return null;
  }
  function binding(group) {
    const names = [...new Set((group.bindings || []).filter(info => info.source === 'binding').flatMap(info => info.names || []))];
    if (!names.length) return {role: null, source: 'unbound', note: 'No precise property binding. Sample-based categories do not establish particle behaviour.'};
    const found = names.map(name => namedRole(name, group.channels)), unique = new Set(found);
    if (unique.size !== 1 || !found[0]) return {role: null, source: 'ambiguous', note: 'Bindings are mixed or do not identify a supported preview property.'};
    return {role: found[0], source: 'binding', note: 'Named property binding: ' + names.join(' · ')};
  }
  function assignments(groups) {
    const result = {}, candidates = {};
    for (const role of roles) {
      candidates[role] = groups.filter(group => binding(group).role === role).map(key);
      result[role] = candidates[role].length === 1 ? candidates[role][0] : '';
    }
    return {values: result, candidates};
  }
  function extent(stops) {
    let min = Infinity, max = -Infinity;
    for (const stop of stops || []) for (const value of stop) if (Number.isFinite(value)) { min = Math.min(min, value); max = Math.max(max, value); }
    if (!Number.isFinite(min)) return {min: 0, max: 1};
    min = Math.min(0, min); max = Math.max(0, max);
    const padding = (max - min || Math.max(1, Math.abs(max))) * .12;
    return {min: min - padding, max: max + padding};
  }
  const api = Object.freeze({roles, clamp, key, sample, equal, modified, original, edited, allowed, binding, assignments, extent});
  root.AtelierMotionboardData = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window === 'undefined' ? globalThis : window);
