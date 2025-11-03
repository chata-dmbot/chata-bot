# Settings Tables Explanation

## Two Types of Settings

### 1. `settings` Table (Global/Default)
- **Purpose**: Global defaults for the entire app
- **Used for**: Fallback when no connection-specific settings exist
- **Example**: Default bot personality like "You are a helpful and friendly Instagram bot."
- **Location**: Used by `get_setting()` function
- **When it's used**: 
  - For the original hardcoded Chata account (if you don't have connection-specific settings)
  - As fallback when connection_id is None or settings don't exist

### 2. `client_settings` Table (Per-Connection)
- **Purpose**: Custom settings for each user's connected Instagram account
- **Used for**: Each user can have different bot personalities per account
- **Example**: One user might want their bot to be "professional" while another wants "casual"
- **Location**: Used by `get_client_settings(user_id, connection_id)` function
- **When it's used**:
  - When a message comes in for a specific Instagram connection
  - The bot uses the settings saved for that specific connection_id

## How It Works

1. **User connects Instagram account** → Creates entry in `instagram_connections` table
2. **User saves bot settings** → Creates/updates entry in `client_settings` table with `connection_id`
3. **Message arrives** → Bot looks up `client_settings` using `connection_id`
4. **Bot uses custom personality** → If found, uses it; otherwise falls back to `settings` table defaults

## Current Issue

If your bot is using default personality instead of saved settings:
- Check if `bot_personality` field is actually saved in `client_settings` table
- Check if `connection_id` is being passed correctly from webhook to `get_ai_reply_with_connection()`
- Check Render logs for: `📝 Bot personality (first 100 chars): ...` to see what's being used
