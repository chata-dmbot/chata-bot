# Webhook signature verification – debugging step by step

## Where we are

Your logs show:

- `body_len=392` → we're receiving the request body
- `has_sig=True` → Facebook is sending the signature header
- `sig_prefix=sha256=` → header format is correct
- `secret_len=32, expected 32` → the secret has the right length (no trailing newline/space)

So the only two realistic possibilities are:

1. **Secret value** – One character in the 32‑char secret is wrong (typo, wrong copy).
2. **Body bytes** – The 392 bytes we're hashing are not exactly what Facebook signed (something in the path changes the body).

---

## What we added to narrow it down

On the next verification failure, the logs will also show:

- `expected_sig_preview=...` – first 12 characters of the signature **we** compute (secret + body we received).
- `received_sig_preview=...` – first 12 characters of the signature **Facebook** sent.

How to read it:

- **Completely different** (e.g. `expected_sig_preview='aB3xY...'` vs `received_sig_preview='k9mZ...'`)  
  → Either the secret is wrong, or the body we receive is not what Facebook signed.

- **Same or very similar**  
  → Less likely; would suggest something odd (e.g. encoding/trim) rather than a totally wrong secret or body.

---

## Next steps (in order)

### Step 1: Redeploy and send one more message

After deploy, send one message to the bot and check the logs. You should see the new line:

`expected_sig_preview=... received_sig_preview=...`

That tells us whether our computed signature and Facebook’s are in the same ballpark or totally different.

---

### Step 2a: If the two previews are totally different – try a fresh secret

Then either the secret or the body is wrong. Easiest way to rule out “wrong character in secret”:

1. In **Meta for Developers** → your app → **Settings** → **Basic** → **App Secret** → click **Regenerate** (or **Reset**).
2. Copy the **new** App Secret (no spaces, no newline).
3. In **Render** → your service → **Environment** → set `FACEBOOK_APP_SECRET` to that **exact** new value. Save.
4. Redeploy, send one message again, check logs.

If it still fails with the new secret, then the problem is almost certainly **body modification** (Step 2b).

---

### Step 2b: If it still fails (or previews are different) – body might be modified

If the secret is definitely correct (e.g. you just regenerated and pasted it) and verification still fails, then something between Facebook and our app is changing the request body (proxy, load balancer, WSGI server, etc.). In that case we’d need to:

- Capture the raw body as early as possible (e.g. WSGI middleware that reads `wsgi.input` once and stores it), or
- Check Render / Gunicorn docs to see if anything parses or modifies the body before our app.

---

### Optional: Temporary bypass (only for debugging)

If you need the bot to work while we debug, we can add an env var (e.g. `SKIP_INSTAGRAM_WEBHOOK_SIGNATURE_VERIFICATION=true`) that skips the check when set. That is **insecure** (anyone could POST to your webhook), so use it only temporarily and only if you accept that risk.

---

## Summary

1. Redeploy and send one message → check logs for `expected_sig_preview` and `received_sig_preview`.
2. If previews are totally different → try regenerating the App Secret in Meta and updating Render, then test again.
3. If it still fails → treat as body modification and look at capturing raw body or at Render/Gunicorn behavior.

No rush; we’re just narrowing down between “wrong secret” and “body changed in transit.”
