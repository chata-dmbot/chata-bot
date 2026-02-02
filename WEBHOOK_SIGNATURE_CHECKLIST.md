# Webhook signature verification – what to verify (step by step)

We're using the earliest body we can (`body_source=middleware`), and `Content-Encoding='(none)'` so gzip is ruled out. The signature still doesn't match, so the issue is either **the secret** or **the body we receive is not what Facebook signed** (e.g. modified by proxy before our process).

---

## 1. Verify the secret using logs (do this first)

**What we log on failure (safe, no full secret):**

- **secret_len** – must be 32.
- **secret_prefix** – first 2 characters of the secret we use (e.g. `'be'`).
- **secret_suffix** – last 4 characters (e.g. `'ef44'`).

**What you do:**

1. In **Meta for Developers** → **Chata** app (App ID 1452514309497145) → **Settings** → **Basic** → **App secret** → look at the value (don’t copy yet).
2. Check: first 2 chars = **secret_prefix** from the log? Last 4 chars = **secret_suffix** from the log?
3. If **they don’t match** → the value in Render (`FACEBOOK_APP_SECRET`) is wrong. Re-copy from Meta (no spaces/newline), paste into Render, save, redeploy.
4. If **they match** → the secret we use is the same as Meta’s; the mismatch is likely **body modification before our app** (e.g. proxy).

**Which secret:** You must use the **Facebook App Secret** from the **Chata** app (the app that receives the webhook), **not** the Instagram app secret. If you ever **regenerated** the App Secret in Meta, you **must** update Render with the **new** value.

---

## 2. What the other log lines mean

- **body_sha256_preview** – First 16 chars of SHA256(raw body). That’s a fingerprint of the **exact bytes** we’re hashing. If the body changed (e.g. by a proxy), this would change. We can’t compare with Facebook’s body, but it confirms what we hashed.
- **expected_sig_preview / received_sig_preview** – First 12 chars of our computed HMAC vs Facebook’s. If they differ, either the secret or the body is wrong.
- **Formula:** We verify: `HMAC-SHA256(raw_body, FACEBOOK_APP_SECRET) == X-Hub-Signature-256`. The raw body is the bytes as received (from middleware). The secret is `FACEBOOK_APP_SECRET` from the environment.

---

## 3. Check Content-Encoding (already done)

**What we added:** The next webhook log line will show **`Content-Encoding=...`**.

**What to look for:**

- If you see **`Content-Encoding='gzip'`** (or similar): Facebook may be sending the body **compressed**. If Render's proxy **decompresses** it before passing the request to our app, we receive **different bytes** than what Facebook signed (they sign the raw body as sent). In that case verification will fail until we either get the raw (compressed) body or the proxy stops decompressing for `/webhook`.
- If you see **`Content-Encoding='(none)'`**: The body is not compressed (or the proxy already decompressed and removed the header). Then the mismatch is more likely a **secret** issue (step 1).

---

## 4. Order of checks

1. **Secret:** Confirm `FACEBOOK_APP_SECRET` in Render is exactly the Facebook App Secret (32 chars, same app, no extra characters). Re-paste from Meta if needed, save, redeploy.
2. **Redeploy and send one message** so the new log line appears.
3. **Logs:** Check for `Content-Encoding=...` in the webhook line.
   - If **gzip**: Body is likely being decompressed by the proxy; we’d need a different approach (e.g. get raw body or disable decompression for webhook).
   - If **(none)** and secret is 100% correct: Something else is changing the body before our app; we can dig into that next.

---

## Summary

| Check | What to do |
|-------|------------|
| **Secret (logs)** | Compare log `secret_prefix` and `secret_suffix` with Meta Chata app secret (first 2 + last 4 chars). If different → fix `FACEBOOK_APP_SECRET` in Render. |
| **Secret (source)** | Must be **Facebook** App Secret of **Chata** app (App ID 1452514309497145), not Instagram app secret. 32 chars, no space/newline. |
| **Content-Encoding** | You already see `(none)` – gzip ruled out. |
| **If prefix/suffix match** | Secret in use matches Meta; likely **body modified before our app** (proxy). Options: keep skip, or investigate Render/proxy. |
| **If prefix/suffix differ** | Update Render with exact secret from Meta, redeploy, test again. |

**What we’re verifying:** Facebook signs the raw POST body with HMAC-SHA256 using the App Secret and sends it in `X-Hub-Signature-256`. We do the same with the body we receive and the secret from env. If they match, the request is from Facebook. If they don’t, either the secret or the body we see is wrong.
