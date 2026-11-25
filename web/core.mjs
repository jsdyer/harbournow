export function endpoint(value, origin = globalThis.location?.origin || 'https://coolcode.ca') {
  const text = String(value || '').trim();
  if (!text) return '';
  const url = new URL(text, origin);
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('Use an HTTPS server origin, for example https://harbour.example.com.');
  return url.origin;
}
export function typeName(code) {
  if (code >= 70 && code <= 79) return 'Cargo';
  if (code >= 80 && code <= 89) return 'Tanker';
  if (code >= 60 && code <= 69) return 'Passenger';
  return ({30:'Fishing',31:'Towing',32:'Towing',33:'Dredging',34:'Diving',35:'Military',36:'Sailing',37:'Pleasure',50:'Pilot',51:'Search & rescue',52:'Tug',53:'Port tender',55:'Law enforcement',58:'Medical',59:'Other service'})[code] || (code ? 'Other' : 'Unknown');
}
export function duration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return 'Unknown';
  if (seconds < 60) return 'less than a minute';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ${Math.floor(seconds % 3600 / 60)} min`;
  return `${Math.floor(seconds / 86400)} d ${Math.floor(seconds % 86400 / 3600)} h`;
}
export function project(lat, lon, zoom) {
  const size = 256 * 2 ** zoom;
  const bounded = Math.max(-85.0511, Math.min(85.0511, lat));
  const sin = Math.sin(bounded * Math.PI / 180);
  return [(lon + 180) / 360 * size, (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size];
}
export function filterShips(ships, query, type, showStale) {
  const needle = query.trim().toLocaleLowerCase();
  return ships.filter(s => (showStale || !s.stale) && (!type || typeName(s.ship_type) === type) && (!needle || [s.name, s.mmsi, s.callsign, s.destination].some(v => String(v || '').toLocaleLowerCase().includes(needle))));
}
export function segmentTrack(points, gap = 600) {
  const segments = [];
  for (const point of points) {
    const last = segments.at(-1);
    if (!last || point.time - last.at(-1).time > gap) segments.push([point]);
    else last.push(point);
  }
  return segments;
}
export function csv(rows) {
  return rows.map(row => row.map(value => {
    let s = String(value ?? '');
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return '"' + s.replaceAll('"', '""') + '"';
  }).join(',')).join('\r\n');
}
