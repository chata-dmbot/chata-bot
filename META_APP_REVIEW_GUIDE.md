# Meta App Review Submission Guide

## 📋 Overview

**What Gets Approved:**
- ✅ **Your entire app** is reviewed and approved
- ✅ **Each permission** is individually reviewed and approved
- ✅ Once approved, your app can be switched to **Live Mode**

**What This Means:**
- After approval, **ANY Instagram user** can connect their account to your app
- **No more tester accounts needed** - the tester requirement disappears
- Users can use your full flow without being added as testers

---

## 📦 Required Submission Materials

### 1. **Detailed Permission Justification** (Text Descriptions)

For each permission you're requesting, you need to explain:

**Example for `instagram_basic`:**
```
"This permission allows our app to access the user's Instagram Business account 
information (username, profile picture, account ID) which is necessary to:
- Display the connected account in the user's dashboard
- Identify which Instagram account messages should be sent to
- Show account information in the bot settings page"
```

**Example for `instagram_manage_messages`:**
```
"This permission enables our app to:
- Receive incoming messages from followers via webhook
- Send automated AI-generated replies to followers
- Access message history to provide context for AI responses
- This is the core functionality of our chatbot service"
```

**Example for `pages_messaging`:**
```
"This permission is required because Instagram messaging is managed through 
Facebook Pages. We need this to:
- Connect Instagram Business accounts (which are linked to Facebook Pages)
- Send and receive messages through the Instagram API
- Manage the messaging connection between Instagram and our service"
```

### 2. **Screencasts (Video Demos)**

Create **one video per permission** showing:

**Video 1: Complete User Flow**
- User signs up/logs in
- User connects Instagram account (OAuth flow)
- User configures bot settings
- User receives a test message
- Bot automatically replies
- Show the reply in Instagram

**Video 2: Permission Usage Demonstration**
- Show where each permission is used in the app
- Highlight the specific features that require each permission
- Demonstrate the end-to-end message flow

**Video Requirements:**
- ✅ Clear, high-quality recording
- ✅ Show the full user journey
- ✅ Highlight where permissions are used
- ✅ Keep videos under 5 minutes each
- ✅ Show actual Instagram messages being sent/received

### 3. **Test User Credentials**

Provide Meta reviewers with:
- **Instagram Business Account credentials:**
  - Username/Email
  - Password
  - (Or a test account they can use)
- **Your app login credentials:**
  - Test account username/email
  - Password
  - Instructions on how to access the app

**Important:** As of 2023, Meta no longer uses "test users" - you need to provide **real account credentials** for reviewers to test with.

### 4. **Step-by-Step Instructions for Reviewers**

Create clear instructions like:

```
1. Go to https://getchata.com
2. Click "Sign Up" and create an account
3. Click "Connect Instagram" button
4. Authorize the app with your Instagram Business account
5. Go to Bot Settings and configure the AI personality
6. Send a test message to the connected Instagram account
7. Verify that the bot automatically replies within the app
8. Check Instagram to see the reply was sent
```

### 5. **Privacy Policy & Terms of Service Links**

- ✅ Privacy Policy URL: `https://getchata.com/privacy`
- ✅ Terms of Service URL: `https://getchata.com/terms`
- ✅ Data Deletion URL: `https://getchata.com/data-deletion`

**Requirements:**
- Must be publicly accessible
- Must explain how you collect, use, and store data
- Must include data deletion instructions

### 6. **Data Handling Questions**

Be prepared to answer:
- How do you collect user data?
- How do you store user data?
- Do you share data with third parties? (OpenAI, Stripe, etc.)
- How long do you retain data?
- How can users delete their data?

---

## 🎯 What Gets Approved

### **App Approval:**
- Meta reviews your **entire application**
- They check compliance with:
  - Platform Policies
  - Community Standards
  - Data Usage Policies
  - Security Requirements

### **Permission Approval:**
- Each permission is **individually reviewed**
- You must justify why you need each one
- Unnecessary permissions will be **rejected**

**Your Current Permissions:**
1. `instagram_basic` - ✅ Justified (account info)
2. `instagram_manage_messages` - ✅ Justified (core chatbot functionality)
3. `pages_messaging` - ✅ Justified (required for Instagram API)

---

## ✅ After Approval: What Changes?

### **Before Approval (Current State):**
- ❌ App is in "Development Mode"
- ❌ You must add users as "testers" in Meta Developer Console
- ❌ Users must be added as testers on Instagram
- ❌ Limited to 25 test users
- ❌ Manual process for each new user

### **After Approval (Live Mode):**
- ✅ App switches to "Live Mode"
- ✅ **ANY Instagram user** can connect their account
- ✅ **No tester accounts needed**
- ✅ **Unlimited users**
- ✅ **Automatic access** - users just connect and use

**This is the main benefit!** Your app becomes publicly available.

---

## ⚠️ Common Rejection Reasons (Avoid These!)

1. **Vague Permission Descriptions**
   - ❌ "We need this permission for our app to work"
   - ✅ "We use this permission to send automated replies to Instagram messages"

2. **Missing or Poor Screencasts**
   - ❌ No video, or video doesn't show permission usage
   - ✅ Clear video showing exactly where each permission is used

3. **No Test Credentials**
   - ❌ Reviewers can't access your app
   - ✅ Provide working login credentials

4. **Missing Privacy Policy**
   - ❌ No privacy policy link
   - ✅ Public, accessible privacy policy

5. **Requesting Unnecessary Permissions**
   - ❌ Requesting permissions you don't actually use
   - ✅ Only request what you absolutely need

6. **Incomplete Instructions**
   - ❌ Reviewers don't know how to test
   - ✅ Step-by-step guide for reviewers

---

## 📝 Submission Checklist

Before submitting, ensure you have:

- [ ] **Business Verification** completed (if required)
- [ ] **Permission justifications** written for each permission
- [ ] **Screencast videos** recorded and uploaded
- [ ] **Test credentials** prepared (Instagram + your app)
- [ ] **Step-by-step instructions** for reviewers
- [ ] **Privacy Policy** published and accessible
- [ ] **Terms of Service** published and accessible
- [ ] **Data deletion flow** implemented and accessible
- [ ] **Data handling questions** answered
- [ ] **App is fully functional** and tested

---

## 🚀 Submission Process

1. **Go to Meta Developer Dashboard**
   - Navigate to: `App Review > Permissions & Features`

2. **Select Permissions to Submit**
   - `instagram_basic`
   - `instagram_manage_messages`
   - `pages_messaging`

3. **Fill Out Forms**
   - Upload screencasts
   - Paste permission justifications
   - Provide test credentials
   - Add reviewer instructions
   - Link to privacy policy/terms

4. **Submit for Review**
   - Review typically takes **3-5 business days**
   - You'll receive email updates

5. **Respond to Feedback** (if needed)
   - Meta may ask for clarifications
   - Respond promptly with additional info

6. **Get Approved!**
   - Switch app to "Live Mode"
   - Remove tester restrictions
   - Start onboarding real users

---

## 💡 Tips for Success

1. **Be Specific:** Don't use generic descriptions - explain exactly how YOU use each permission

2. **Show, Don't Tell:** Screencasts are more powerful than text descriptions

3. **Test Everything:** Make sure your app works perfectly before submitting

4. **Be Honest:** Don't request permissions you don't actually need

5. **Prepare for Questions:** Meta reviewers may ask follow-up questions - be ready to respond quickly

6. **Keep It Simple:** Focus on your core use case - automated Instagram message replies

---

## 📞 Need Help?

If you get rejected:
- Read the feedback carefully
- Address each point they mention
- Resubmit with improvements
- Don't give up - most apps get approved on 2nd or 3rd try

---

## 🎯 Your Specific Use Case

**What You're Building:**
An AI-powered Instagram chatbot that automatically replies to messages

**Why You Need These Permissions:**
- `instagram_basic`: To identify and display connected accounts
- `instagram_manage_messages`: To receive and send messages (core feature)
- `pages_messaging`: Required by Instagram API for messaging functionality

**This is a clear, legitimate use case** - you should have a good chance of approval!

