# Meta Instagram webhook signature verification – implementation notes

Based on research (see PDF: *Fixing Meta Instagram Webhook Signature Verification on Render with Flask*) and current code.

## What Meta does

- Meta signs webhook **Event Notification** payloads and puts the signature in **X-Hub-Signature-256** (format: `sha256=<hex>`).
- Verification: compute **HMAC-SHA256** over the **exact raw request body bytes** using the **App Secret**, then compare to the header (constant-time).
- Meta’s signature is over the **raw payload bytes as sent** (including any escaping their serializer uses). Even equivalent JSON (different whitespace, escaping, key order) yields a different HMAC.

## Findings from research

- **Compression**: Real Instagram/Messenger webhook captures show **no Content-Encoding: gzip** on the request; body is plain JSON. So **transparent gzip decompression** by the proxy is unlikely; Meta typically sends uncompressed.
- **Render**: Render often has Cloudflare in front; there is no strong evidence that Render transparently decompresses **request** bodies. Request-body decompression is usually an explicit feature, not default.
- **Likely cause when verification fails**: The bytes we hash are **not** the exact bytes Meta signed—e.g. body read after something else consumed/decoded it, or parsing/rewriting (Unicode escapes, re-serialization) before verification.
- **Do not**: Parse or re-serialize the body before verification; add your own “escape Unicode” step; rely on reading the body from a stream that might already have been consumed.

## What we do in code

1. **Single canonical raw body**  
   We use **`request.get_data(cache=True)`** at the start of the POST handler and use that for verification. That gives one read, cached for the request. Our WSGI middleware also reads the body early and replaces `wsgi.input` with `BytesIO(body)`; in that case `get_data()` returns the same bytes.

2. **Verification**  
   - Strip `sha256=` from the header; compute `hmac.new(secret, raw_body, hashlib.sha256).hexdigest()`; compare with `hmac.compare_digest(expected, received)`.
   - Secret is stripped of leading/trailing whitespace (env vars often have newlines when pasted).

3. **Order of operations**  
   We never call `request.get_json()` or any body parsing before signature verification. Verification runs first, then we parse JSON for processing.

4. **Fallback**  
   If raw-body verification fails, we try once with **compact JSON** (no spaces, same key order) in case something re-serialized the body; research suggests this is not Meta’s normal behavior, so this is a best-effort fallback.

5. **Skip flag**  
   `SKIP_INSTAGRAM_WEBHOOK_SIGNATURE_VERIFICATION` (default `true`) skips verification so the bot works in production when verification still fails. Set to `false` to enable verification once the byte source is correct.

## If verification still fails

- Ensure **no** middleware or `before_request` touches or parses the body before the webhook handler runs.
- Log a **fingerprint** of the body we hash: `len(body)`, `hashlib.sha256(body).hexdigest()`, and short hex prefix/suffix of `body` (e.g. `body[:32].hex()`, `body[-32:].hex()`) to confirm we’re hashing the same buffer end-to-end.
- Reduce **proxy layers** in front of `/webhook` (e.g. avoid extra CDN/proxy that might rewrite the body).
- If you can prove the body bytes at the app differ from what Meta signed, verification must happen at a layer that sees the exact bytes (e.g. edge that preserves raw body) or the pipeline must be changed so the app receives the unmodified body.
