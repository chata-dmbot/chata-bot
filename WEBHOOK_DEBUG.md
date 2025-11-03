# Webhook Debugging Guide

## Quick Check: Are POST requests arriving?

1. Send a message to your Instagram account
2. Immediately check Render logs
3. Look for: `📥 WEBHOOK RECEIVED POST REQUEST`

**If you see it:** The webhook is working, but message processing might have an issue.
**If you DON'T see it:** Instagram isn't sending webhooks to your app.

## Getting Correct ACCESS_TOKEN and INSTAGRAM_USER_ID

### Step 1: Get Page Access Token
1. Go to: https://developers.facebook.com/apps/
2. Select your app: **chata** (App ID: 1452514309497145)
3. Go to: **Messenger** → **Instagram Settings**
4. Under "Instagram Business Accounts", find your Page: **EgoInspiration** (Page ID: 830077620186727)
5. Click **"Generate Token"** or **"View Token"**
6. Copy the **long-lived Page Access Token**
7. This is your `ACCESS_TOKEN` value

### Step 2: Get Page ID (Instagram User ID)
- Your Page ID is: **830077620186727**
- This is your `INSTAGRAM_USER_ID` value

### Step 3: Update Render
1. Render → chata-bot → Environment
2. Set `ACCESS_TOKEN` = [the token from Step 1]
3. Set `INSTAGRAM_USER_ID` = `830077620186727`
4. Save and redeploy

## Test After Update

1. Send a test message to Instagram
2. Check Render logs for:
   - `📥 WEBHOOK RECEIVED POST REQUEST`
   - `🎯 Message sent to Instagram account: [ID]`
   - `✅ Found Instagram connection`

If you see these, your bot should reply!
