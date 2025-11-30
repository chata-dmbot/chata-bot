# 🚀 Stripe Live Mode Migration Checklist

## Environment Variables to Update in Render

To switch from Stripe **test mode** to **live/production mode**, you need to update **6 environment variables** in your Render dashboard:

### 1. **STRIPE_SECRET_KEY**
   - **Test Mode:** Starts with `sk_test_...`
   - **Live Mode:** Starts with `sk_live_...`
   - **Where to find:** Stripe Dashboard → Developers → API keys → Secret key (Live mode)
   - ⚠️ **CRITICAL:** This is your live secret key - keep it secure!

### 2. **STRIPE_PUBLISHABLE_KEY**
   - **Test Mode:** Starts with `pk_test_...`
   - **Live Mode:** Starts with `pk_live_...`
   - **Where to find:** Stripe Dashboard → Developers → API keys → Publishable key (Live mode)
   - 📝 **Note:** This is safe to expose in frontend code

### 3. **STRIPE_WEBHOOK_SECRET**
   - **Test Mode:** Starts with `whsec_test_...` or `whsec_...`
   - **Live Mode:** Different secret for live webhook endpoint
   - **Where to find:** 
     1. Stripe Dashboard → Developers → Webhooks
     2. Create a new webhook endpoint (or use existing) pointing to: `https://chata-bot.onrender.com/webhook/stripe`
     3. Click on the webhook endpoint → "Signing secret" → Reveal
   - ⚠️ **IMPORTANT:** You must create a NEW webhook endpoint in LIVE mode (separate from test mode)

### 4. **STRIPE_STARTER_PLAN_PRICE_ID**
   - **Test Mode:** Starts with `price_...` (from test mode products)
   - **Live Mode:** Different price ID from live mode products
   - **Where to find:**
     1. Stripe Dashboard → Products → Create or select your Starter plan
     2. Make sure you're in **LIVE mode** (toggle at top of Stripe dashboard)
     3. Create the product with €9/month price
     4. Copy the Price ID (starts with `price_...`)

### 5. **STRIPE_STANDARD_PLAN_PRICE_ID**
   - **Test Mode:** Starts with `price_...` (from test mode products)
   - **Live Mode:** Different price ID from live mode products
   - **Where to find:**
     1. Stripe Dashboard → Products → Create or select your Standard plan
     2. Make sure you're in **LIVE mode**
     3. Create the product with €39/month price
     4. Copy the Price ID (starts with `price_...`)

### 6. **STRIPE_ADDON_PRICE_ID**
   - **Test Mode:** Starts with `price_...` (from test mode products)
   - **Live Mode:** Different price ID from live mode products
   - **Where to find:**
     1. Stripe Dashboard → Products → Create or select your Add-on product
     2. Make sure you're in **LIVE mode**
     3. Create a one-time payment product for €5 / 150 replies
     4. Copy the Price ID (starts with `price_...`)

---

## Step-by-Step Migration Process

### Step 1: Prepare Stripe Live Mode Products
1. Go to Stripe Dashboard
2. **Toggle to LIVE mode** (top right of dashboard)
3. Create the following products if they don't exist:
   - **Starter Plan:** Recurring subscription, €9/month
   - **Standard Plan:** Recurring subscription, €39/month
   - **Add-on:** One-time payment, €5 (for 150 replies)

### Step 2: Create Live Webhook Endpoint
1. In Stripe Dashboard (LIVE mode) → Developers → Webhooks
2. Click "Add endpoint"
3. Endpoint URL: `https://chata-bot.onrender.com/webhook/stripe`
4. Select events to listen for:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
5. Copy the "Signing secret" (this is your `STRIPE_WEBHOOK_SECRET`)

### Step 3: Get Live API Keys
1. Stripe Dashboard → Developers → API keys
2. Make sure you're in **LIVE mode**
3. Copy:
   - **Secret key** (starts with `sk_live_...`)
   - **Publishable key** (starts with `pk_live_...`)

### Step 4: Update Render Environment Variables
1. Go to Render Dashboard → Your Service → Environment
2. Update each of the 6 variables above with your LIVE mode values
3. Save changes (this will trigger a redeploy)

### Step 5: Verify After Deployment
1. Wait for deployment to complete
2. Visit: `https://chata-bot.onrender.com/payment-system-verification`
3. Check that all Stripe configuration shows ✅
4. Verify all price IDs show live mode prices

---

## ⚠️ Important Notes

1. **Test Mode vs Live Mode are COMPLETELY SEPARATE**
   - Test mode products/prices don't exist in live mode
   - You must create everything again in live mode

2. **Real Money Transactions**
   - Once you switch to live mode, ALL payments will be REAL
   - Test your checkout flow thoroughly before going live
   - Consider setting up Stripe test cards first

3. **Webhook Must Be Recreated**
   - Test mode webhooks don't work with live mode
   - You must create a new webhook endpoint in live mode
   - The webhook URL stays the same, but the secret is different

4. **No Code Changes Needed**
   - You only need to update environment variables
   - No code changes required (code is already compatible)

5. **Rollback Plan**
   - Keep your test mode values saved somewhere safe
   - If something goes wrong, you can switch back to test mode

---

## Quick Reference: All Variables

```
STRIPE_SECRET_KEY=sk_live_...           ← Secret key (live mode)
STRIPE_PUBLISHABLE_KEY=pk_live_...      ← Publishable key (live mode)
STRIPE_WEBHOOK_SECRET=whsec_...         ← Webhook secret (live mode)
STRIPE_STARTER_PLAN_PRICE_ID=price_...  ← Starter plan price (live mode)
STRIPE_STANDARD_PLAN_PRICE_ID=price_... ← Standard plan price (live mode)
STRIPE_ADDON_PRICE_ID=price_...         ← Add-on price (live mode)
```

---

## Testing After Switch

Since you mentioned you want to avoid real payments, here are some options:

1. **Use Stripe's Test Cards** (but you're in live mode, so this won't work)
2. **Test with Small Amount:** Make a test payment of €0.01 or €0.10
3. **Use Stripe's Test Mode:** Keep testing in test mode until everything is perfect
4. **Refund Immediately:** Make a real payment, verify it works, then refund it

**Recommendation:** Test everything thoroughly in TEST mode first, then switch to LIVE mode when you're 100% confident everything works.

