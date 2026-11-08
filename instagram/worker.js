// Optional relay, only needed if Meta won't accept the Apps Script URL directly
// (Apps Script answers through a redirect, which some Meta checks reject).
// Deploy as a free Cloudflare Worker, set APPS_SCRIPT_URL as a variable, and give Meta the worker's URL.
export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (req.method === 'GET') {
      const r = await fetch(env.APPS_SCRIPT_URL + url.search, { redirect: 'follow' });
      return new Response(await r.text(), { status: 200 });
    }
    const body = await req.text();
    ctx.waitUntil(fetch(env.APPS_SCRIPT_URL, { method: 'POST', body, headers: { 'content-type': 'application/json' }, redirect: 'follow' }));
    return new Response('ok', { status: 200 });   // answer Meta straight away
  },
};
