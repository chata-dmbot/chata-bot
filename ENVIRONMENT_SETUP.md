# Chata Environment Variables Setup

## Required Environment Variables

Create a `.env` file in your project root with the following variables:

### Flask Configuration
```bash
SECRET_KEY=your-super-secret-key-change-this-in-production
FLASK_ENV=production
```

### Database Configuration
```bash
DATABASE_URL=postgresql://username:password@host:port/database
```

### OpenAI Configuration
```bash
OPENAI_API_KEY=sk-your-openai-api-key
```

### Meta/Facebook/Instagram Configuration
```bash
VERIFY_TOKEN=your-webhook-verify-token
ACCESS_TOKEN=your-facebook-page-access-token
INSTAGRAM_USER_ID=your-facebook-page-id
FACEBOOK_APP_ID=your-facebook-app-id
FACEBOOK_APP_SECRET=your-facebook-app-secret
FACEBOOK_REDIRECT_URI=https://your-domain.com/auth/instagram/callback
```

### Email Configuration (SendGrid)
```bash
SENDGRID_API_KEY=your-sendgrid-api-key
```

### Production Settings
```bash
PORT=5000
```

## Security Notes

1. **NEVER** commit the `.env` file to version control
2. **ALWAYS** use strong, unique values for SECRET_KEY
3. **ROTATE** API keys regularly
4. **USE** environment-specific values for different deployments

## Render Deployment

Set these environment variables in your Render dashboard:
1. Go to your service settings
2. Navigate to "Environment" tab
3. Add each variable with its production value
