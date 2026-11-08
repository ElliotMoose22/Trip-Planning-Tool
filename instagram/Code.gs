/**
 * Trip reels inbox: receives the reels you and Cat DM to the trip Instagram account
 * and adds one row per reel to the Reels tab of the SUMMER TRIP sheet.
 *
 * Paste this into Extensions → Apps Script in the sheet, then follow instagram/SETUP.md.
 *
 * How messages are read:
 *   - a shared reel            → new row (Received, From, Reel link, Caption), Status "New"
 *   - a number 1–10            → rating for that person's most recent unrated reel
 *   - "8 Kamakura, Enoshima"   → rating plus the places in that reel (one map pin each);
 *                                use brackets for a region: "9 Ubud (Bali), Tegallalang"
 *   - "elliot" or "cat"        → tells the script whose Instagram account this is (once each)
 * Everything else (place, map colour, photo) is filled in by the trip tool's daily run.
 *
 * Script properties (Project Settings → Script properties):
 *   VERIFY_TOKEN   any phrase; you type the same phrase into the Meta webhook settings
 *   SENDERS        filled in automatically, e.g. {"1784...":"Elliot","1790...":"Cat"}
 */

const TAB = 'Reels';
const HEADER_ROW = 3;            // row with "Received | From | Reel link | ..."

const VERIFY_TOKEN = 'asia-2027-reels';   // must match the Verify token typed into Meta

function doGet(e) {
  // Meta checks the webhook once: echo hub.challenge back if the token matches.
  const p = e.parameter || {};
  const token = String(PropertiesService.getScriptProperties().getProperty('VERIFY_TOKEN') || VERIFY_TOKEN).trim();
  if (p['hub.mode'] === 'subscribe') {
    if (String(p['hub.verify_token'] || '').trim() === token) return ContentService.createTextOutput(p['hub.challenge']);
    return ContentService.createTextOutput('Verify token does not match the one in the script.');
  }
  return ContentService.createTextOutput('Trip reels inbox is running.');
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    (body.entry || []).forEach((entry) => (entry.messaging || []).forEach(handle_));
  } catch (err) {
    console.error(err);
  }
  return ContentService.createTextOutput('ok');
}

function handle_(ev) {
  const msg = ev.message;
  if (!msg || msg.is_echo) return;
  const cache = CacheService.getScriptCache();
  if (msg.mid) {                                  // Meta can deliver the same message twice
    if (cache.get(msg.mid)) return;
    cache.put(msg.mid, '1', 21600);
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const who = senderName_(ev.sender && ev.sender.id, msg.text);
    if (who === null) return;                     // that message was just "elliot" / "cat"

    const reels = (msg.attachments || []).filter((a) => ['ig_reel', 'reel', 'share'].includes(a.type));
    reels.forEach((a) => addReel_(who, a.payload || {}));

    const text = (msg.text || '').trim();
    const m = text.match(/^(\d{1,2})(?:\s*\/\s*10)?(?:[\s,:\-–]+(.+))?$/s);
    if (!reels.length && m && +m[1] >= 1 && +m[1] <= 10) rate_(who, +m[1], (m[2] || '').trim());
  } finally {
    lock.releaseLock();
  }
}

function senderName_(id, text) {
  const props = PropertiesService.getScriptProperties();
  const senders = JSON.parse(props.getProperty('SENDERS') || '{}');
  const t = (text || '').trim().toLowerCase();
  if (id && (t === 'elliot' || t === 'cat')) {
    senders[id] = t === 'cat' ? 'Cat' : 'Elliot';
    props.setProperty('SENDERS', JSON.stringify(senders));
    relabel_(`Unknown (${id})`, senders[id]);       // fix reels sent before saying who you are
    return null;
  }
  return senders[id] || `Unknown (${id})`;
}

function sheet_() {
  const sh = SpreadsheetApp.getActive().getSheetByName(TAB);
  if (!sh) throw new Error(`No "${TAB}" tab in this sheet`);
  const head = sh.getRange(HEADER_ROW, 1, 1, sh.getLastColumn()).getValues()[0].map((h) => String(h).trim().toLowerCase());
  const col = (name) => head.findIndex((h) => h.startsWith(name)) + 1;   // 1-based, 0 = missing
  return { sh, col };
}

function addReel_(who, p) {
  const { sh, col } = sheet_();
  const link = p.url || (p.reel_video_id ? `https://www.instagram.com/reel/${p.reel_video_id}` : '');
  const caption = String(p.title || '').slice(0, 1500);
  // first empty row under the header (ignores the sample rows' status note)
  const last = Math.max(sh.getLastRow(), HEADER_ROW);
  const links = last > HEADER_ROW ? sh.getRange(HEADER_ROW + 1, col('reel link'), last - HEADER_ROW, 1).getValues() : [];
  if (link && links.some((r) => String(r[0]) === link)) return;          // already in the sheet
  let row = HEADER_ROW + 1 + links.findIndex((r) => !String(r[0]).trim());
  if (row <= HEADER_ROW) row = last + 1;
  const put = (name, v) => { const c = col(name); if (c) sh.getRange(row, c).setValue(v); };
  put('received', Utilities.formatDate(new Date(), 'America/Toronto', 'yyyy-MM-dd'));
  put('from', who);
  put('reel link', link);
  put('caption', caption);
  put('status', 'New');
}

function rate_(who, rating, places) {
  const { sh, col } = sheet_();
  const last = sh.getLastRow();
  if (last <= HEADER_ROW) return;
  const n = last - HEADER_ROW;
  const from = sh.getRange(HEADER_ROW + 1, col('from'), n, 1).getValues();
  const rate = sh.getRange(HEADER_ROW + 1, col('rating'), n, 1).getValues();
  const link = sh.getRange(HEADER_ROW + 1, col('reel link'), n, 1).getValues();
  const place = sh.getRange(HEADER_ROW + 1, col('place'), n, 1).getValues();
  for (let i = n - 1; i >= 0; i--) {
    if (String(from[i][0]) === who && String(link[i][0]).trim() && String(rate[i][0]).trim() === '') {
      for (let j = 0; j < n; j++) {               // a reel already split into several places: rate them all
        if (String(link[j][0]) === String(link[i][0]) && String(rate[j][0]).trim() === '') {
          sh.getRange(HEADER_ROW + 1 + j, col('rating')).setValue(rating);
        }
      }
      if (places && !String(place[i][0]).trim()) sh.getRange(HEADER_ROW + 1 + i, col('place')).setValue(places);
      return;
    }
  }
}

function relabel_(oldName, name) {
  const { sh, col } = sheet_();
  const last = sh.getLastRow();
  if (last <= HEADER_ROW) return;
  const r = sh.getRange(HEADER_ROW + 1, col('from'), last - HEADER_ROW, 1);
  r.setValues(r.getValues().map((x) => [String(x[0]) === oldName ? name : x[0]]));
}

/** Run this once from the editor to check the script can write to the tab. */
function testAddReel() {
  handle_({ sender: { id: 'test' }, message: { mid: 'test-' + Date.now(),
    attachments: [{ type: 'ig_reel', payload: { url: 'https://www.instagram.com/reel/test', title: 'Test reel: Kamakura day trip' } }] } });
  handle_({ sender: { id: 'test' }, message: { mid: 'test2-' + Date.now(), text: '8' } });
}
