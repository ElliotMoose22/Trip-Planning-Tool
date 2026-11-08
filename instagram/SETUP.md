# Reels inbox setup

You and Cat each DM reels to the trip Instagram account (1:1, not a group chat: Instagram's API
doesn't deliver group-chat messages). After each reel, send a number 1–10 as its rating.

```
Instagram DM ──▶ Meta webhook ──▶ Apps Script (Code.gs) ──▶ Reels tab
                                                                │  every evening (daily-reels.yml)
                                                                ▼
                      Claude reads the caption → place → map pin (green/yellow/red), photo, Ideas tab, recommendations
```

## 1. The trip Instagram account
1. Create the account, then **Settings and activity → Account type and tools → Switch to professional account**
   (Business is the safest choice for messaging; skip linking a Facebook Page).
2. In the **phone app** (not the website): **Settings and activity → Messages and story replies → Message requests
   → Connected tools → Allow access to messages** (on). Some app versions say *Message controls* instead of *Message requests*.

## 2. The Apps Script inbox
1. Open the SUMMER TRIP Google Sheet (the one with the Places, Legs and Reels tabs) → **Extensions → Apps Script**. Replace the code with `Code.gs` from this folder.
2. **Project Settings → Script properties → Add**: `VERIFY_TOKEN` = any phrase (e.g. `asia-2027-reels`).
3. Run `testAddReel` once from the editor and approve the permissions. A test row appears in Reels; delete it.
4. **Deploy → New deployment → Web app**. Execute as: *Me*. Who has access: *Anyone*. Copy the `/exec` URL.

## 3. The Meta app (stays in development mode, no review needed)
1. At developers.facebook.com → **My Apps → Create app** → type *Business* (or "Other → Business").
2. Add the **Instagram** product → **API setup with Instagram login**.
3. **Add account**: log in with the trip account. Then **Generate token** (keeps the connection active).
4. **Configure webhooks**: Callback URL = the `/exec` URL, Verify token = your phrase → *Verify and save*.
   Then subscribe to the **messages** field.
   - If Meta says the URL couldn't be verified, deploy `worker.js` as a free Cloudflare Worker
     (variable `APPS_SCRIPT_URL` = the `/exec` URL) and use the worker's URL instead.
5. **App roles → Roles → Add people → Instagram Tester**: add your and Cat's personal Instagram usernames.
   Each of you accepts in the Instagram app: **Settings → Website permissions → Apps and websites → Tester invites**.
   (In development mode only testers' messages reach the webhook, which is exactly what we want.)

## 4. Say who you are (once each)
From your own Instagram, DM the trip account the word `elliot`; Cat sends `cat`.
After that every reel either of you sends is tagged with your name.

## 5. Let Claude read the captions (uses your Pro plan, no API key)
1. On your computer: `npm install -g @anthropic-ai/claude-code`, then `claude setup-token` and log in.
2. Copy the token into GitHub → repo **Settings → Secrets and variables → Actions → New secret**:
   `CLAUDE_CODE_OAUTH_TOKEN`.

Without the token everything still works except the caption reading: type the place into the
**Place** column yourself (or ask Claude in chat to process the new reels) and the next run maps it.

## Sending a reel
1. Share the reel to the trip account.
2. Send the rating as its own message: `8` (or `8/10`).
   - Several places in one reel? Add them after the rating: `8 Kamakura, Enoshima`. Each gets its own pin.
     Put a region in brackets so it stays with its place: `9 Ubud (Bali), Tegallalang`.
   - Just `8` works too: Claude lists every place the caption names (it can't see the video or photos,
     so name the places yourself when the caption doesn't).
3. By the next evening it's on the map at the dashboard, in the Ideas tab, and if it needs a night
   somewhere new, in Recommendations. Run **Actions → Daily reels → Run workflow** to do it now.
