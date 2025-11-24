# Local Testing Guide 🏠

## Why Test Locally?

✅ **Faster Development** - No need to push/deploy for each change  
✅ **Instant Feedback** - See errors and logs immediately in your terminal  
✅ **Easy Debugging** - Use print statements, breakpoints, and debugger  
✅ **No Production Impact** - Test without affecting real users  
✅ **Free** - No deployment time or resource limits  

---

## Quick Start (5 minutes)

### Step 1: Create `.env` File

Create a `.env` file in your project root with all your environment variables:

```env
# Database (use SQLite locally, or your local PostgreSQL)
DATABASE_URL=  # Leave empty to use SQLite (chata.db)

# Flask
SECRET_KEY=your-local-secret-key-here

# OpenAI
OPENAI_API_KEY=your-openai-key

# Meta/Instagram
VERIFY_TOKEN=chata_verify_token
ACCESS_TOKEN=your-access-token
INSTAGRAM_USER_ID=your-instagram-user-id
FACEBOOK_APP_ID=your-facebook-app-id
FACEBOOK_APP_SECRET=your-facebook-app-secret
FACEBOOK_REDIRECT_URI=http://localhost:5000/auth/instagram/callback

# Stripe (use TEST keys!)
STRIPE_PUBLISHABLE_KEY=pk_test_xxxxx
STRIPE_SECRET_KEY=sk_test_xxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxx  # Get this from Stripe CLI (see below)
STRIPE_STARTER_PLAN_PRICE_ID=price_xxxxx
STRIPE_STANDARD_PLAN_PRICE_ID=price_xxxxx
STRIPE_ADDON_PRICE_ID=price_xxxxx

# Email (optional for local testing)
SENDGRID_API_KEY=your-sendgrid-key
```

**⚠️ Important:** Use **TEST** keys from Stripe (not live keys!)

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Run the App Locally

```bash
python app.py
```

Or with Flask CLI:
```bash
flask run
```

You should see:
```
Starting Chata application...
Database initialized successfully
✅ All required environment variables are set
 * Running on http://0.0.0.0:5000
```

**Open in browser:** http://localhost:5000

---

## Viewing Logs Locally 📋

**All logs appear directly in your terminal!**

- ✅ **Print statements** → Show in terminal
- ✅ **Errors** → Full traceback in terminal
- ✅ **Flask debug mode** → Detailed error pages in browser
- ✅ **Stripe webhook logs** → See in terminal when using Stripe CLI

**Example:**
```bash
$ python app.py
Starting Chata application...
Database initialized successfully
✅ All required environment variables are set
📥 Received Stripe webhook: checkout.session.completed
🛒 Processing checkout session: cs_test_xxxxx
✅ Subscription created for user 123
```

---

## Testing Stripe Webhooks Locally 🔔

### Option A: Stripe CLI (Recommended)

**1. Install Stripe CLI:**

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

**2. Login to Stripe:**
```bash
stripe login
```

**3. Start your Flask app:**
```bash
# Terminal 1
python app.py
```

**4. Forward webhooks to local server:**
```bash
# Terminal 2
stripe listen --forward-to http://localhost:5000/webhook/stripe
```

**You'll see:**
```
> Ready! Your webhook signing secret is whsec_xxxxx (^C to quit)
```

**5. Copy the webhook secret to your `.env`:**
```env
STRIPE_WEBHOOK_SECRET=whsec_xxxxx
```

**6. Restart your Flask app** (to load the new secret)

**7. Test it:**
- Make a test payment in your app
- Watch both terminals - you'll see webhook events!

### Option B: Stripe Dashboard (Alternative)

1. Go to Stripe Dashboard → Developers → Webhooks
2. Add endpoint: `http://localhost:5000/webhook/stripe`
3. Use the webhook secret from Stripe dashboard
4. **Note:** You'll need to expose localhost (use ngrok or similar)

---

## Testing Workflow 🔄

### Typical Development Cycle:

1. **Make code changes** in your editor
2. **Save file** (Flask auto-reloads if debug=True)
3. **Test in browser** at http://localhost:5000
4. **Check terminal** for logs/errors
5. **Fix issues** → Repeat

**No git push needed!** 🎉

### When to Push to Render:

- ✅ After testing locally and everything works
- ✅ When you want to test with real Instagram webhooks
- ✅ When ready for production deployment

---

## Debug Routes (Local Testing)

Access these routes locally:

- `http://localhost:5000/debug/user-stats` - Check user stats
- `http://localhost:5000/debug/stripe-customers` - Check Stripe customers
- `http://localhost:5000/debug/simulate-reply` - Simulate replies (POST)
- `http://localhost:5000/debug/set-reply-count` - Set reply count (POST)

---

## Common Issues & Solutions

### Issue: "Database not found"
**Solution:** The app will create `chata.db` automatically on first run.

### Issue: "Stripe webhook signature verification failed"
**Solution:** Make sure `STRIPE_WEBHOOK_SECRET` in `.env` matches the one from `stripe listen`

### Issue: "Port 5000 already in use"
**Solution:** 
```bash
# Use a different port
PORT=5001 python app.py
```

### Issue: "Module not found"
**Solution:**
```bash
pip install -r requirements.txt
```

---

## Pro Tips 💡

1. **Use VS Code debugger** - Set breakpoints and step through code
2. **Keep terminal open** - All logs appear there
3. **Use print() statements** - They show up immediately in terminal
4. **Test Stripe in test mode** - Use test cards: `4242 4242 4242 4242`
5. **Check database** - Use a SQLite browser to inspect `chata.db`

---

## Environment Variables: Local vs Production

| Variable | Local | Production (Render) |
|----------|-------|---------------------|
| `DATABASE_URL` | Empty (uses SQLite) | PostgreSQL URL |
| `STRIPE_*_KEY` | `sk_test_...` | `sk_live_...` (when ready) |
| `STRIPE_WEBHOOK_SECRET` | From `stripe listen` | From Stripe Dashboard |
| `FACEBOOK_REDIRECT_URI` | `http://localhost:5000/...` | `https://chata-bot.onrender.com/...` |
| `FLASK_DEBUG` | `True` | `False` |

---

## Next Steps

1. ✅ Create `.env` file with your test keys
2. ✅ Run `python app.py`
3. ✅ Test locally at http://localhost:5000
4. ✅ Set up Stripe CLI for webhook testing
5. ✅ Develop and test without pushing!

**Happy coding!** 🚀

