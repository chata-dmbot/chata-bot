# Stripe Setup Guide

## ✅ Step 1: Get Your Price IDs (NOT Product IDs)

You provided **Product IDs** (`prod_...`), but we need **Price IDs** (`price_...`) for Checkout.

### How to Find Your Price IDs:

1. Go to your Stripe Dashboard → **Product catalog** (left sidebar)
2. Click on **"Starter"** product (the one you created)
3. You'll see the product details - look for the **"Pricing"** section
4. Under pricing, you'll see your monthly price listed
5. Click on that price - you'll see the **Price ID** which starts with `price_...` (e.g., `price_1234567890abcdef`)
6. Copy that Price ID - that's what we need for the Starter Plan

7. Now go to your **"Reply Add-on"** product
8. Repeat the same process to find its Price ID

**Alternatively:**
- Go to **Developers** → **API keys** → Scroll down to see your products/prices
- Or use the Stripe CLI or API to list prices

### What We Need:
- ✅ Starter Plan **Price ID**: `price_...` (for €9/month subscription)
- ✅ Add-on **Price ID**: `price_...` (for €5 one-time payment)

---

## ✅ Step 2: Set Up Webhook Endpoint

### Option A: Using Stripe CLI (For Local Testing - Recommended First)

1. **Install Stripe CLI:**
   - Download from: https://stripe.com/docs/stripe-cli
   - Or: `brew install stripe/stripe-cli/stripe` (Mac)
   - Or: `choco install stripe` (Windows)

2. **Login to Stripe:**
   ```bash
   stripe login
   ```

3. **Forward webhooks to your local server:**
   ```bash
   stripe listen --forward-to http://localhost:5000/webhook/stripe
   ```
   This will give you a **webhook signing secret** like `whsec_...`
   - **Copy this secret** - you'll need it for local testing

### Option B: Using Stripe Dashboard (For Production)

1. Go to **Developers** → **Webhooks** → **Add endpoint**

2. **Endpoint URL:**
   ```
   https://chata-bot.onrender.com/webhook/stripe
   ```
   (Replace with your actual domain)

3. **Events to send:**
   Select these events:
   - `payment_intent.succeeded` (for one-time payments)
   - `customer.subscription.created` (when subscription starts)
   - `customer.subscription.updated` (when subscription changes)
   - `customer.subscription.deleted` (when subscription ends)
   - `invoice.payment_succeeded` (when monthly payment succeeds)
   - `invoice.payment_failed` (when payment fails)

4. Click **Add endpoint**

5. **Copy the Signing secret:**
   - After creating, click on the endpoint
   - Click **Reveal** next to "Signing secret"
   - Copy the secret (starts with `whsec_...`)

---

## ✅ Step 3: Environment Variables

Add these to your Render environment variables (or `.env` for local):

```
STRIPE_PUBLISHABLE_KEY=pk_test_51SUwAW2YobxhcxuMG8tJ1HO5CeI2XNDDOGtUiMEXW41kcZ6MagpvHyO2y1hSXsA2Au72xiAzKs1E5yolSJ8WfmJa00GQXEL9KW
STRIPE_SECRET_KEY=sk_test_51SUwAW2YobxhcxuMt2HuJLrqlH3MwlHqaeL4iSC0bs8WExeSzOpViut0YPkxAPxI1Mx2s2bm8yBEUKduIYpk16yu008gvnM4SS
STRIPE_STARTER_PLAN_PRICE_ID=price_XXXXX (you need to get this)
STRIPE_ADDON_PRICE_ID=price_XXXXX (you need to get this)
STRIPE_WEBHOOK_SECRET=whsec_XXXXX (get this after setting up webhook)
```

---

## 📋 Summary: What You Need to Provide

1. ✅ **Stripe Publishable Key**: `pk_test_...` (You already provided)
2. ✅ **Stripe Secret Key**: `sk_test_...` (You already provided)
3. ⏳ **Starter Plan Price ID**: `price_...` (Need to find this)
4. ⏳ **Add-on Price ID**: `price_...` (Need to find this)
5. ⏳ **Webhook Signing Secret**: `whsec_...` (Get this after setting up webhook)

Once you provide the Price IDs and Webhook Secret, I can complete the integration!

