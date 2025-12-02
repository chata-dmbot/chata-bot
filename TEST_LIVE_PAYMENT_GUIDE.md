# Test Live Payment System - Setup Guide

This guide will help you test your live Stripe payment system with a minimal €0.10 payment.

## Step 1: Create Test Product in Stripe

1. Go to **Stripe Dashboard** → **Products** → **Add Product**

2. Fill in:
   - **Name:** `Test Payment`
   - **Description:** `€0.10 test payment for live system verification`
   - **Pricing model:** One-time payment
   - **Price:** `€0.10` (or `€0.10 EUR`)
   - Click **Save product**

3. **Copy the Price ID** (starts with `price_...`)
   - You'll see it in the product details
   - It looks like: `price_1ABC123def456GHI789`

## Step 2: Set Environment Variable

1. Go to **Render Dashboard** → Your service → **Environment**

2. Add new variable:
   - **Key:** `STRIPE_TEST_PAYMENT_PRICE_ID`
   - **Value:** `price_...` (paste the Price ID you copied)
   - Click **Save Changes**

3. **Render will automatically redeploy** (wait 2-3 minutes)

## Step 3: Test the Payment

1. Go to your **Dashboard** → **Quick Actions**
2. You'll see a yellow "Test Live Payment System" box
3. Click **Test Payment (€0.10)**
4. Complete the payment with a real card
5. After payment, you'll be redirected back to the dashboard

## Step 4: Verify Everything Works

Check these things:

1. **Render Logs:**
   - Go to Render → Logs
   - Look for webhook events like:
     - `checkout.session.completed`
     - `payment_intent.succeeded`
   - Should see: `✅ Received webhook: checkout.session.completed`

2. **Stripe Dashboard:**
   - Go to **Payments** → You should see the €0.10 payment
   - Go to **Webhooks** → Click your endpoint → See successful deliveries

3. **Database (optional check):**
   - You can check if the payment was recorded (though test payments don't create subscriptions)

## Step 5: Refund the Test Payment

1. Go to **Stripe Dashboard** → **Payments**
2. Find your €0.10 test payment
3. Click on it → **Refund** → **Refund payment**
4. The full amount will be refunded to your card

## Step 6: Remove Test Button (After Testing)

Once you've verified everything works:

1. I'll remove the test button from the dashboard
2. You can optionally delete the test product in Stripe (or keep it for future testing)

## Troubleshooting

- **"Test payment price ID not configured"**: Make sure you set `STRIPE_TEST_PAYMENT_PRICE_ID` in Render and waited for redeploy
- **No webhook events**: Check that your webhook endpoint URL is correct in Stripe
- **Payment succeeded but nothing in logs**: Check Render logs are enabled and refresh

---

**Note:** This is a real payment in live mode. You'll be charged €0.10, but you can immediately refund it after testing.

