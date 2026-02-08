# ChatGPT Deep Research prompt: Meta/Instagram webhook signature verification on Render

Copy the block below and paste it into ChatGPT (Deep Research mode) to gather everything needed to fix X-Hub-Signature-256 verification when the app is hosted on Render.

---

## Research request

I need to fix **Meta (Facebook) Instagram webhook payload signature verification** in production. The app is a **Python Flask** backend hosted on **Render.com**. Meta sends webhooks to our HTTPS endpoint and signs the request body with **HMAC-SHA256** using our **App Secret**; the signature is in the **X-Hub-Signature-256** header (format: `sha256=<hex_string>`).

**Current situation:**
- Verification **fails** in production: the signature we compute never matches the one Meta sends, so we have to skip verification (insecure).
- We already fixed: (1) encoding — Meta sends **hex**, we now use `.hexdigest()` not base64; (2) the **App Secret** is correct and matches Meta for Developers; (3) we capture the **raw request body** as early as possible via WSGI middleware (before Flask parses it) and use that for HMAC.
- The **body we receive** is valid JSON, looks like a normal Instagram webhook payload, and we log `Content-Encoding: (none)`. The **body length** is ~400 bytes (decompressed size). Our computed signature and Meta’s are always **completely different** (different hex prefixes), so it’s not a small encoding/trim issue — we are hashing **different bytes** than Meta signed.

**Working hypothesis:**
- Something between Meta and our app is changing the request body. The most likely cause is **transparent decompression**: Meta sends the webhook with **Content-Encoding: gzip** and signs the **compressed** body; a reverse proxy or load balancer (e.g. Render’s) **decompresses** the body before it reaches our app and may remove the Content-Encoding header, so we only ever see decompressed bytes and our HMAC is computed over different data than Meta’s.

**What I need you to research in depth:**

1. **Meta’s webhook request format**
   - Do Meta / Instagram / Facebook Graph API webhooks send the **request body** as **gzip-compressed** or uncompressed?
   - Is there official documentation that states whether the body is compressed and what exact bytes are used for the X-Hub-Signature-256 calculation (raw body as sent, including compression or not)?
   - Any official sample code or docs that show how to verify the signature when the request goes through a reverse proxy or CDN?

2. **Render.com behavior**
   - Does Render (or its edge/proxy layer) **decompress** incoming request bodies (e.g. when the client sends `Content-Encoding: gzip`)?
   - Is there a way to **disable** request-body decompression or to get the **raw** (possibly compressed) body for a specific path (e.g. `/webhook`) on Render?
   - Any Render docs, community posts, or support answers about receiving webhooks from Meta, Stripe, or other providers that sign the body, and how to preserve the exact body bytes?

3. **Best practices when proxy changes the body**
   - If the hosting platform always decompresses or otherwise modifies the body before the app sees it, what are the **recommended solutions**? (e.g. use a different host, run behind our own proxy that doesn’t touch the body, ask the provider for an alternative verification method, etc.)
   - Any known workarounds (e.g. re-compressing the body with gzip and verifying against that) and whether they are valid for Meta’s webhooks?

4. **Similar reports and solutions**
   - Search for reports of **Meta webhook signature verification failing** specifically when the app is behind a proxy (AWS, Render, Heroku, Cloudflare, nginx, etc.) and what fixed it (config change, middleware, platform setting, or moving to a host that doesn’t modify the body).

Please summarize:
- Whether Meta sends webhook bodies compressed or not, and what bytes they sign.
- Whether Render (or similar PaaS) is known to decompress or modify request bodies and how to get raw body for signature verification.
- Concrete steps or config (for Render or our code) to get X-Hub-Signature-256 verification working, or a clear statement that it’s not possible on this platform and what the alternatives are.

---

*After you have the research results, you can share the summary with your codebase/AI to implement the fix. Set the env var `SKIP_INSTAGRAM_WEBHOOK_SIGNATURE_VERIFICATION=true` on Render so the bot keeps working until the fix is in place.*
