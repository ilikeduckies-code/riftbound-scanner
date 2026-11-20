/**
 * Riftbound Scanner sync backend. Paste into the sheet's Extensions > Apps Script,
 * then Deploy > New deployment > Web app (Execute as: Me, Who has access: Anyone).
 *
 * The Log tab is the source of truth: one row per scan or correction (Qty +1 / -1).
 * Inventory, Locations, Batches and Find Card are formulas over the Log.
 */
const LOG = 'Log', SETTINGS = 'Settings';
const COLS = 13; // Timestamp, Device, Op ID, Card ID, Name, Set, Set Code, Number, Foil, Batch, Qty, Rarity, Type

function doGet(e) { return respond(e && e.parameter || {}); }
function doPost(e) {
  let body = {};
  try { body = JSON.parse(e.postData.contents); } catch (err) {}
  return respond(body);
}

function respond(p) {
  let out;
  try { out = Object.assign({ ok: true }, route(p)); }
  catch (err) { out = { ok: false, error: String(err && err.message || err) }; }
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

function route(p) {
  switch (p.action) {
    case 'pull': return pull(+p.since || 0);
    case 'push': return withLock(() => push(p.ops || []));
    case 'nextBatch': return withLock(nextBatch);
    case 'saveSettings': return withLock(() => saveSettings(p.settings || {}));
    default: return { settings: readSettings(), total: logCount() };
  }
}

function withLock(fn) {
  const lock = LockService.getScriptLock();
  lock.waitLock(25000);
  try { return fn(); } finally { lock.releaseLock(); }
}

function sheet(name) { return SpreadsheetApp.getActive().getSheetByName(name); }
function logCount() { return Math.max(0, sheet(LOG).getLastRow() - 1); }

function pull(since) {
  const sh = sheet(LOG), total = logCount();
  if (since > total) since = 0; // rows were deleted by hand: client should reload everything
  // Op ID of the last row the client already has; the client reloads everything if it differs.
  const anchor = since > 0 ? String(sh.getRange(since + 1, 3).getValue()) : '';
  let rows = [];
  if (total > since) {
    rows = sh.getRange(since + 2, 1, total - since, COLS).getValues()
      .map(r => { r[0] = r[0] instanceof Date ? r[0].toISOString() : String(r[0]); return r; });
  }
  return { since, anchor, total, rows, settings: readSettings() };
}

function push(ops) {
  const sh = sheet(LOG);
  const total = logCount();
  // Skip ops already written (a retry after a lost response).
  const recent = new Set();
  if (total) {
    const n = Math.min(total, 2000);
    sh.getRange(total - n + 2, 3, n, 1).getValues().forEach(r => recent.add(String(r[0])));
  }
  const now = new Date();
  const rows = ops.filter(o => o && o.opId && !recent.has(String(o.opId))).map(o => [
    now, text(o.device), text(o.opId), text(o.rid), text(o.name), text(o.setName),
    text(o.code), text(o.num), o.foil ? 'Foil' : '', text(o.batch), Number(o.qty) || 0,
    text(o.rarity), text(o.type)
  ]);
  if (rows.length) {
    const start = total + 2, need = start + rows.length - 1;
    if (need > sh.getMaxRows()) sh.insertRowsAfter(sh.getMaxRows(), need - sh.getMaxRows() + 500);
    sh.getRange(start, 1, rows.length, COLS).setValues(rows);
  }
  return { written: rows.length, total: logCount() };
}

// Plain text only: a value starting with = + - @ would otherwise become a formula in the sheet.
function text(v) {
  const s = String(v == null ? '' : v);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function readSettings() {
  const v = sheet(SETTINGS).getRange('B2:B5').getValues().map(r => r[0]);
  return { batchSize: Number(v[0]) || 50, prefix: String(v[1] ?? ''), digits: Number(v[2]) || 4, next: Number(v[3]) || 1 };
}

function saveSettings(s) {
  const cur = readSettings();
  const merged = {
    batchSize: Math.max(1, Number(s.batchSize) || cur.batchSize),
    prefix: s.prefix !== undefined ? String(s.prefix) : cur.prefix,
    digits: Math.max(1, Number(s.digits) || cur.digits),
    next: s.next !== undefined ? Math.max(1, Number(s.next) || 1) : cur.next
  };
  sheet(SETTINGS).getRange('B2:B5').setValues([[merged.batchSize], [merged.prefix], [merged.digits], [merged.next]]);
  return { settings: merged };
}

function nextBatch() {
  const s = readSettings(), total = logCount();
  // Skip codes already used in the Log (e.g. made offline, or the counter was lowered by hand).
  const used = new Set(total ? sheet(LOG).getRange(2, 10, total, 1).getValues().map(r => String(r[0])) : []);
  let n = s.next, code;
  do { code = s.prefix + String(n).padStart(s.digits, '0'); n++; } while (used.has(code));
  sheet(SETTINGS).getRange('B5').setValue(n);
  return { code, batchSize: s.batchSize, settings: Object.assign(s, { next: n }) };
}
