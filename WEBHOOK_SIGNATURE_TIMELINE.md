# Webhook signature: why it was working before and what changed

## Short answer

**It was working before because we were not verifying the signature.**  
We then added signature verification for security (H2). Once that was in place, every POST to `/webhook` is checked: if the signature doesn’t match, we return 403. So “it stopped working” when we started enforcing verification, not because we changed how or when we read the body.

---

## Timeline

### 1. Before signature verification (original behavior)

- POST to `/webhook`:
  - We read the body and parsed the JSON.
  - We did **not** check `X-Hub-Signature-256`.
- Result: **every** webhook POST was accepted (no 403 from signature).

So “it was working before” = no signature check, so nothing could fail it.

---

### 2. What we added: signature verification (H2)

- We added:
  - `_verify_instagram_webhook_signature(raw_body, sig_header)`
  - At the start of the POST branch: read `raw_body`, get `X-Hub-Signature-256`, then:
    - If `FACEBOOK_APP_SECRET` is set **and** the signature doesn’t match → **403**.
    - If `FACEBOOK_APP_SECRET` is not set → we **skip** verification (and log a warning).
- So after this change:
  - If you **don’t** set `FACEBOOK_APP_SECRET` in Render → we still don’t verify, webhook keeps “working” as before (but unsecured).
  - If you **do** set `FACEBOOK_APP_SECRET` → we verify; if the signature doesn’t match (secret wrong, or body changed), we return 403.

So “it stopped working” = we started **enforcing** verification once the secret was set; the failure is from the new check, not from changing body handling.

---

### 3. What we did *not* change (optimization commit)

- We only changed **after** verification and parsing:
  - We build `incoming_by_sender` **before** opening the DB.
  - If there are no processable messages, we return 200 **without** opening the DB.
- Order in the code is still:

  1. `raw_body = request.get_data()`
  2. Read `X-Hub-Signature-256`
  3. **Verify signature** (if `FACEBOOK_APP_SECRET` is set) → 403 if fail
  4. Parse JSON, build `incoming_by_sender`, etc.

We did **not** move body read or verification later; we did **not** add anything that reads the body before `get_data()`. So the optimization commit did **not** cause the signature to start failing.

---

## Why verification fails now

Only a few things can make the check fail:

1. **Secret mismatch**  
   The value of `FACEBOOK_APP_SECRET` in Render must be **exactly** the Meta App Secret (same characters, no extra newline or space). We now strip the secret before use and log `secret_len` on failure so you can see if there’s an extra character (e.g. 33 instead of 32).

2. **Body not the same as what Facebook signed**  
   We verify using the **exact** bytes we get from `request.get_data()`. If a proxy or platform changes the body (e.g. encoding, trimming), the bytes change and the signature will not match. In that case the fix is either to ensure the raw body is preserved up to our app or to investigate the platform (e.g. Render).

3. **Wrong header or encoding**  
   We expect `X-Hub-Signature-256` with format `sha256=<base64>`. Your logs show `has_sig=True` and `sig_prefix=sha256=`, so this part is fine.

---

## Summary

| When              | What happened |
|-------------------|----------------|
| **Before H2**     | No signature verification → all webhook POSTs accepted. |
| **After H2**      | Signature verification added; if `FACEBOOK_APP_SECRET` is set and the signature doesn’t match → 403. |
| **Optimization**  | Only changed logic *after* verification (when we open DB, when we return 200). Did **not** change body read or verification order. |

So: **it was working before because we weren’t verifying. It “stopped working” when we started verifying and the signature didn’t match (secret or body).** The recent optimization did not introduce the failure.

Next steps: redeploy with the strip + `secret_len` log, send a message, and check the log. If `secret_len=32` and it still fails, the next place to look is whether the request body is being modified before it reaches the app.
