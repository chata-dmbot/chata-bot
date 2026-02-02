# Webhook signature verification – what to verify (step by step)

We're using the earliest body we can (`body_source=middleware`), but the signature still doesn't match. So the issue is either **the secret** or **the body we receive is not what Facebook signed**.

---

## 1. Verify the secret (do this first)

**What to check:**

- **Which secret:** You must use the **Facebook App Secret** from the **Chata** app (the app that receives the webhook), **not** the Instagram app secret.
  - Meta for Developers → **Chata** app (App ID 1452514309497145) → **Settings** → **Basic** → **App secret** → copy it.
- **Where it goes:** In Render → your service → **Environment** → variable **`FACEBOOK_APP_SECRET`** must be **exactly** that value.
- **Exact match:**
  - Length: 32 characters (no space, no newline at the end).
  - After pasting in Render, re-copy from Meta and paste again to rule out a typo.
  - If you ever **regenerated** the App Secret in Meta, you **must** update Render with the **new** value (old one will no longer match).

**Why it matters:** If one character is wrong, the HMAC we compute will be completely different from Facebook's, even with the correct body.

---

## 2. Check Content-Encoding (after next deploy)

**What we added:** The next webhook log line will show **`Content-Encoding=...`**.

**What to look for:**

- If you see **`Content-Encoding='gzip'`** (or similar): Facebook may be sending the body **compressed**. If Render's proxy **decompresses** it before passing the request to our app, we receive **different bytes** than what Facebook signed (they sign the raw body as sent). In that case verification will fail until we either get the raw (compressed) body or the proxy stops decompressing for `/webhook`.
- If you see **`Content-Encoding='(none)'`**: The body is not compressed (or the proxy already decompressed and removed the header). Then the mismatch is more likely a **secret** issue (step 1).

---

## 3. Order of checks

1. **Secret:** Confirm `FACEBOOK_APP_SECRET` in Render is exactly the Facebook App Secret (32 chars, same app, no extra characters). Re-paste from Meta if needed, save, redeploy.
2. **Redeploy and send one message** so the new log line appears.
3. **Logs:** Check for `Content-Encoding=...` in the webhook line.
   - If **gzip**: Body is likely being decompressed by the proxy; we’d need a different approach (e.g. get raw body or disable decompression for webhook).
   - If **(none)** and secret is 100% correct: Something else is changing the body before our app; we can dig into that next.

---

## Summary

| Check | What to do |
|-------|------------|
| **Secret** | Meta → Chata app → App secret → copy. Render → `FACEBOOK_APP_SECRET` = that exact value (32 chars). Re-paste, save, redeploy. |
| **Content-Encoding** | After deploy, send one message and look at the webhook log line for `Content-Encoding=...`. |
| **If gzip** | Proxy may be decompressing; body we hash ≠ body Facebook signed. |
| **If (none) and secret correct** | Next step is to see what else might be modifying the body. |

Start with the secret; then use the new log to interpret Content-Encoding.
