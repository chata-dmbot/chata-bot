# Stripe Webhook Setup Guide

## Recommendation: Test Locally First ⚡

**I recommend testing locally first** because:
1. ✅ **Faster iteration** - No need to deploy for each test
2. ✅ **Easy debugging** - See logs immediately
3. ✅ **No production impact** - Test without affecting real users
4. ✅ **Stripe CLI** - Makes local testing super easy

---

## Option 1: Local Testing (Recommended First) 🏠

### Step 1: Install Stripe CLI

**Windows:**
```bash
# Using Chocolatey
choco install stripe

# Or download from: https://github.com/stripe/stripe-cli/releases
```

**Mac:**
```bash
brew install stripe/stripe-cli/stripe
```

**Linux:**
```bash
# Download from: https://github.com/stripe/stripe-cli/releases
```

### Step 2: Login to Stripe

```bash
stripe login
```

This will open a browser window to authenticate.

### Step 3: Forward Webhooks to Local Server

Start your Flask app locally (usually on port 5000):

```bash
# In one terminal
python app.py
# or
flask run
```

Then in another terminal, forward webhooks:

```bash
stripe listen --forward-to http://localhost:5000/webhook/stripe
```

**This will give you a webhook signing secret like:**
```
> Ready! Your webhook signing secret is whsec_xxxxx (^C to quit)
```

**⚠️ IMPORTANT:** Copy this secret! It's different from production.

### Step 4: Add to Environment Variables

Add to your `.env` file for local testing:

```
STRIPE_WEBHOOK_SECRET=whsec_xxxxx
```

### Step 5: Test the Webhook

1. Make a test payment/subscription in your app
2. Check your terminal - you should see webhook events coming through
3. Check your database - subscription/purchase should be created

---

## Option 2: Production Setup (After Local Testing) 🌐

### Step 1: Deploy Your Code

Make sure your app is deployed and accessible at:
```
https://chata-bot.onrender.com/webhook/stripe
```

### Step 2: Set Up Webhook in Stripe Dashboard

1. Go to **Stripe Dashboard** → **Developers** → **Webhooks**
2. Click **"+ Add endpoint"**
3. **Endpoint URL:**
   ```
   https://chata-bot.onrender.com/webhook/stripe
   ```
   (Replace with your actual domain)
4. **Description:** "Chata Bot Webhook"
5. **Events to send:** Select these:
   - ✅ `checkout.session.completed` (for successful payments)
   - ✅ `customer.subscription.created` (when subscription starts)
   - ✅ `customer.subscription.updated` (when subscription changes)
   - ✅ `customer.subscription.deleted` (when subscription ends)
   - ✅ `invoice.payment_succeeded` (when monthly payment succeeds)
   - ✅ `invoice.payment_failed` (when payment fails)

6. Click **"Add endpoint"**

### Step 3: Get Production Webhook Secret

1. After creating, click on your endpoint
2. Click **"Reveal"** next to **"Signing secret"**
3. Copy the secret (starts with `whsec_...`)

### Step 4: Add to Production Environment

Add to your **Render environment variables**:

```
STRIPE_WEBHOOK_SECRET=whsec_xxxxx
```

### Step 5: Test Production Webhook

1. Make a test payment/subscription
2. Go to **Stripe Dashboard** → **Developers** → **Webhooks** → Your endpoint
3. Check **"Events"** tab - you should see events
4. Check your database/logs to verify everything worked

---

## Quick Test Commands

### Test Webhook Locally (Using Stripe CLI)

```bash
# Trigger a test event
stripe trigger checkout.session.completed

# Or trigger subscription created
stripe trigger customer.subscription.created
```

### Check Webhook Events in Dashboard

1. Go to **Stripe Dashboard** → **Developers** → **Webhooks**
2. Click on your endpoint
3. View **"Events"** tab to see all webhook calls
4. Click on any event to see details and response

---

## Troubleshooting

### Webhook not receiving events?

1. ✅ Check your endpoint URL is correct and accessible
2. ✅ Verify webhook secret is set correctly
3. ✅ Check Stripe Dashboard → Webhooks → Events for errors
4. ✅ Check your app logs for webhook errors
5. ✅ Verify events are selected in webhook settings

### Webhook signature verification failed?

1. ✅ Check `STRIPE_WEBHOOK_SECRET` environment variable
2. ✅ Make sure you're using the correct secret (test vs live)
3. ✅ Verify the endpoint URL matches exactly

### Events not processing?

1. ✅ Check your app logs for error messages
2. ✅ Verify database connection
3. ✅ Check that event handlers are correct

---

## Summary

**For Testing:**
1. Install Stripe CLI
2. Run `stripe listen --forward-to http://localhost:5000/webhook/stripe`
3. Copy the webhook secret it gives you
4. Add to `.env` file
5. Test locally!

**For Production:**
1. Deploy your app
2. Set up webhook endpoint in Stripe Dashboard
3. Copy production webhook secret
4. Add to Render environment variables
5. Test with a real payment

---

## Need Help?

Check your app logs and Stripe Dashboard webhook events to see what's happening!

