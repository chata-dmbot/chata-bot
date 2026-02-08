"""AI service — OpenAI prompt building and reply generation."""
import logging
import openai
import json
import time
from config import Config
from database import get_db_connection, get_param_placeholder

logger = logging.getLogger("chata.services.ai")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONVERSATION_EXAMPLES = [
    {
        "key": "conv_example_1",
        "title": "Conversation Example 1",
        "exchanges": [
            {
                "follower_message": "hey, just wanted to say I really liked your last post, how did you pull that off",
                "bot_reply_key": "reply_1"
            },
            {
                "follower_message": "nice, thanks for the explanation, do you have more stuff like that coming soon",
                "bot_reply_key": "reply_2"
            },
            {
                "follower_message": "cool, appreciate you taking the time to answer, keep doing your thing",
                "bot_reply_key": "reply_3"
            }
        ]
    },
    {
        "key": "conv_example_2",
        "title": "Conversation Example 2",
        "exchanges": [
            {
                "follower_message": "idk why but your content helped a lot today, been going through some stuff",
                "bot_reply_key": "reply_1"
            },
            {
                "follower_message": "thanks, really means something right now, I've just been overwhelmed lately",
                "bot_reply_key": "reply_2"
            },
            {
                "follower_message": "anyway I don't wanna keep you, hope everything's good on your side too",
                "bot_reply_key": "reply_3"
            }
        ]
    },
    {
        "key": "conv_example_3",
        "title": "Conversation Example 3",
        "exchanges": [
            {
                "follower_message": "hey quick question, do you ever do shoutouts or promos",
                "bot_reply_key": "reply_1"
            },
            {
                "follower_message": "ah ok cool, how does it usually work for you",
                "bot_reply_key": "reply_2"
            },
            {
                "follower_message": "got it, thanks for clearing that up, keep doing your thing",
                "bot_reply_key": "reply_3"
            }
        ]
    },
    {
        "key": "conv_example_4",
        "title": "Conversation Example 4",
        "exchanges": [
            {
                "follower_message": "yo I saw something in one of your older posts, do you still do stuff like that",
                "bot_reply_key": "reply_1"
            },
            {
                "follower_message": "nice, where can I check some of the new things you've been doing",
                "bot_reply_key": "reply_2"
            },
            {
                "follower_message": "sweet, I'll look through it later, thanks for the quick answer",
                "bot_reply_key": "reply_3"
            }
        ]
    }
]

# Keep for backward compatibility in prompt building
CONVERSATION_TEMPLATES = CONVERSATION_EXAMPLES
ALL_CONVERSATION_PROMPTS = CONVERSATION_EXAMPLES

MODEL_CONFIG = {
    "gpt-5-nano": {
        "token_param": "max_completion_tokens",
        "supports_temperature": False,
        "max_completion_cap": 3000,
    },
}

DEFAULT_MODEL_CONFIG = {
    "token_param": "max_tokens",
    "supports_temperature": True,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Reply generation
# ---------------------------------------------------------------------------

def get_ai_reply(history):
    # Lazy import to avoid circular dependency while get_setting lives in app
    from app import get_setting

    openai.api_key = Config.OPENAI_API_KEY
    try:
        client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)

        system_prompt = get_setting("bot_personality",
            "You are a helpful and friendly Instagram bot.")

        messages = [{"role": "system", "content": system_prompt}]
        messages += history

        model_name = "gpt-5-nano"
        model_config = MODEL_CONFIG.get(model_name, DEFAULT_MODEL_CONFIG)

        completion_kwargs = {
            "model": model_name,
            "messages": messages,
        }
        # temperature and max_tokens hardcoded per model config
        if model_config.get("supports_temperature", True):
            completion_kwargs["temperature"] = 0.7

        token_param = model_config.get("token_param", "max_tokens")
        max_tokens = model_config.get("max_completion_cap", 3000)
        if token_param == "max_completion_tokens":
            completion_kwargs["max_completion_tokens"] = max_tokens
        else:
            completion_kwargs["max_tokens"] = max_tokens
        openai_start = time.time()
        response = client.chat.completions.create(**completion_kwargs)
        openai_duration = time.time() - openai_start
        logger.info(f"OpenAI chat latency (global): {openai_duration:.2f}s; model={model_name}")

        if not response.choices:
            logger.warning(f"OpenAI returned no choices: {response}")
            return "Sorry, I'm having trouble replying right now."

        message = response.choices[0].message
        if not message or not getattr(message, "content", None):
            logger.warning(f"OpenAI returned empty content: {response}")
            return "Sorry, I'm having trouble replying right now."

        ai_reply = message.content.strip()
        if not ai_reply:
            logger.warning(f"OpenAI content was blank after strip: {response}")
            return "Sorry, I'm having trouble replying right now."

        return ai_reply

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I'm having trouble replying right now."

def get_ai_reply_with_connection(history, connection_id=None, conn=None):
    """
    Get AI reply using connection-specific settings if available.
    
    Args:
        history: Conversation history
        connection_id: Optional connection ID
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
    """
    # Lazy import to avoid circular dependency while get_client_settings lives in app
    from app import get_client_settings

    openai.api_key = Config.OPENAI_API_KEY
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    try:
        client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)

        # Extract latest message from follower
        latest_message = ""
        if history and len(history) > 0:
            # Get the last user message
            for msg in reversed(history):
                if msg.get('role') == 'user':
                    latest_message = msg.get('content', '').strip()
                    break

        # Get settings for this specific connection
        if connection_id:
            # Get user_id from connection - reuse provided connection
            cursor = conn.cursor()
            placeholder = get_param_placeholder()
            cursor.execute(f"SELECT user_id FROM instagram_connections WHERE id = {placeholder}", (connection_id,))
            result = cursor.fetchone()
            
            if result:
                user_id = result[0]
                # Pass connection to get_client_settings to avoid opening another one
                settings = get_client_settings(user_id, connection_id, conn)
                system_prompt = build_personality_prompt(settings, history=history, latest_message=latest_message)
                logger.info(f"Using connection-specific settings for connection {connection_id}")
                logger.debug(f"Prompt length: {len(system_prompt)} chars")
                logger.debug(f"Latest message: {latest_message[:50]}...")
            else:
                # Fallback to global settings
                logger.warning(f"Connection {connection_id} not found, using neutral persona fallback")
                fallback_settings = {
                    'bot_name': '',
                    'bot_personality': 'You must still act like a real human. Keep responses short and conversational.'
                }
                system_prompt = build_personality_prompt(fallback_settings, history=history, latest_message=latest_message)
        else:
            # Use global settings (for original Chata account)
            logger.warning("No connection_id passed to get_ai_reply_with_connection; using neutral persona fallback.")
            fallback_settings = {
                'bot_name': '',
                'bot_personality': 'You must still act like a real human. Keep responses short and conversational.'
            }
            system_prompt = build_personality_prompt(fallback_settings, history=history, latest_message=latest_message)

        # Since everything is now in the system prompt, we only send the system message
        messages = [{"role": "system", "content": system_prompt}]

        model_name = "gpt-5-nano"
        model_config = MODEL_CONFIG.get(model_name, DEFAULT_MODEL_CONFIG)

        completion_kwargs = {
            "model": model_name,
            "messages": messages,
        }
        # temperature and max_tokens are hardcoded per model config —
        # gpt-5-nano does not support temperature and caps at 3000 tokens.
        if model_config.get("supports_temperature", True):
            completion_kwargs["temperature"] = 0.7  # default; nano skips this

        token_param = model_config.get("token_param", "max_tokens")
        max_tokens = model_config.get("max_completion_cap", 3000)
        if token_param == "max_completion_tokens":
            completion_kwargs["max_completion_tokens"] = max_tokens
        else:
            completion_kwargs["max_tokens"] = max_tokens
        openai_start = time.time()
        response = client.chat.completions.create(**completion_kwargs)
        openai_duration = time.time() - openai_start
        logger.info(f"OpenAI chat latency (connection {connection_id or 'global'}): {openai_duration:.2f}s; model={model_name}")

        if not response.choices:
            logger.warning(f"OpenAI returned no choices: {response}")
            if should_close and conn:
                conn.close()
            return "Sorry, I'm having trouble replying right now."

        message = response.choices[0].message
        if not message or not getattr(message, "content", None):
            logger.warning(f"OpenAI returned empty content: {response}")
            if should_close and conn:
                conn.close()
            return "Sorry, I'm having trouble replying right now."

        ai_reply = message.content.strip()
        if not ai_reply:
            logger.warning(f"OpenAI content was blank after strip: {response}")
            if should_close and conn:
                conn.close()
            return "Sorry, I'm having trouble replying right now."

        if should_close and conn:
            conn.close()
        return ai_reply

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        if should_close and conn:
            conn.close()
        return "Sorry, I'm having trouble replying right now."


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_personality_prompt(settings, history=None, latest_message=None):
    """
    Build the system prompt using the new structured format.
    """
    def clean(value):
        if not value:
            return ""
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value).strip()

    name = clean(settings.get('bot_name')) or "you"
    age = clean(settings.get('bot_age')) or ""
    location = clean(settings.get('bot_location')) or ""
    occupation = clean(settings.get('bot_occupation')) or ""
    about = clean(settings.get('bot_personality')) or ""
    avoid_topics = clean(settings.get('avoid_topics')) or ""

    # Build promo links
    promo_links = []
    for link in settings.get('links') or []:
        url = clean(link.get('url'))
        title = clean(link.get('title'))
        if url:
            promo_links.append(f"{title}: {url}" if title else url)
    promo_links_text = ", ".join(promo_links) if promo_links else "None provided."

    # Build content highlights
    content_highlights = []
    posts = settings.get('posts') or []
    for idx, post in enumerate(posts, start=1):
        description = clean(post.get('description'))
        if description:
            content_highlights.append(f"{idx}. {description}")
    content_highlights_text = ", ".join(content_highlights) if content_highlights else "None provided."

    # Build post descriptions list - just list the descriptions directly
    post_descriptions = []
    for post in posts:
        description = clean(post.get('description'))
        if description:
            post_descriptions.append(description)
    post_descriptions_text = ", ".join(post_descriptions) if post_descriptions else "None provided."

    # Format conversation examples
    example_conversations = []
    samples = settings.get('conversation_samples') or {}
    if isinstance(samples, dict):
        for example in CONVERSATION_EXAMPLES:
            conversation_parts = []
            has_replies = False
            
            for exchange in example.get('exchanges', []):
                reply_key = f"{example['key']}_{exchange['bot_reply_key']}"
                reply = samples.get(reply_key)
                
                if reply:
                    has_replies = True
                    conversation_parts.append(f'Follower: "{exchange["follower_message"]}"')
                    conversation_parts.append(f'You: "{reply}"')
            
            if has_replies and conversation_parts:
                conversation_text = '\n'.join(conversation_parts)
                example_conversations.append(conversation_text)
    
    example_conversations_text = '\n\n'.join(example_conversations) if example_conversations else "No example conversations provided."

    # Format recent chat (last 20 messages)
    recent_chat_text = "No recent chat history."
    if history and len(history) > 0:
        # Get last 20 messages (10 from follower, 10 from bot ideally)
        last_messages = history[-20:] if len(history) > 20 else history
        chat_lines = []
        for msg in last_messages:
            role = msg.get('role', '')
            content = msg.get('content', '').strip()
            if content:
                if role == 'user':
                    chat_lines.append(f'Follower: "{content}"')
                elif role == 'assistant':
                    chat_lines.append(f'You: "{content}"')
        recent_chat_text = '\n'.join(chat_lines) if chat_lines else "No recent chat history."

    # Format latest message
    latest_message_text = latest_message if latest_message else ""

    # Build the prompt using the new structure (using regular string, not f-string)
    prompt_template = """You are {NAME}, a {AGE} year old {WHAT_YOU_DO} from {LOCATION}.

About you: {ABOUT}.

Stay fully in character. Never mention or imply anything automated.

Follow these rules:

1. Stay in character at all times.

2. Match the follower's tone, energy, slang, emojis, and length.

3. Keep replies short: one or two sentences. Avoid long paragraphs. Break up your thoughts so replies feel natural and easy to read.

4. Do not act like an assistant. Only help or give tips if the follower asks.

5. Let the follower lead. Do not force new topics or keep the chat going if they are closing it.

6. Avoid repeating information you already gave.

7. Small imperfections are fine if they feel natural. Do not overdo them.

8. Sound like a real person texting. No lists, no templates. Never use em dashes (—) or double hyphens (--).

9. Only share a promo link (OnlyFans, Linktree, etc.) at most once every 3 back-and-forth messages. If you shared a link in the last few replies, wait at least 3 exchanges before sharing another link.

10. Avoid ending with a question or asking things like "Want me to...?" or "Want me to tell you...?" Prefer short statements. Do not try to keep the chat going by asking the follower a question.

11. Variation and no repetition: Never reuse the same phrase, opener, or sign-off in consecutive replies. If you used a particular line or greeting in your last reply (or the one before), say something different this time. Rotate how you start and end messages. Vary sentence structure and word choice so each message feels fresh. A little ambiguity is fine—you do not need to repeat the same idea in the same way every time.

12. Match and take inspiration from the follower: Mirror their energy, vocabulary, and style. If they are brief, be brief. If they are excited or use certain words or emojis, echo that vibe. Take inspiration from what they say—reference their interests, their words, or their mood—so the conversation feels like a real back-and-forth, not a script. Let their message shape your reply; do not fall back on the same stock phrases regardless of what they wrote.

Avoid these topics: {TOPICS_TO_AVOID}.

If the follower brings them up, redirect gently in your own tone.

You can reference your content only when it fits naturally:

- Promo links: {PROMO_LINKS}

- Content highlights: {CONTENT_HIGHLIGHTS}

- Posts: {POST_DESCRIPTIONS}

Your main guidance for tone and style: the example conversations below. They define how you text. Match their length, tone, phrasing, and communication style. Use them as the primary reference for every reply.

Example conversations (your main style guide):

{EXAMPLE_CONVERSATIONS}

Here is the recent chat between you and this follower:

{RECENT_CHAT_LAST_20_MESSAGES}

Follower's latest message (this is the one you must answer now):

"{LATEST_MESSAGE}"

Reply with a single message as {NAME}, following the rules above and mirroring the style of the example conversations.

Before replying: check the recent chat. If you already used a phrase or opener in your last 1–2 messages, do not repeat it—vary your wording. Let the follower's latest message guide your tone and content.

Use the recent chat only as context, and answer only to the follower's latest message."""

    # Replace placeholders (using single braces since we're not using f-string)
    prompt = prompt_template.replace("{NAME}", name)
    prompt = prompt.replace("{AGE}", age)
    prompt = prompt.replace("{WHAT_YOU_DO}", occupation)
    prompt = prompt.replace("{LOCATION}", location)
    prompt = prompt.replace("{ABOUT}", about)
    prompt = prompt.replace("{TOPICS_TO_AVOID}", avoid_topics)
    prompt = prompt.replace("{PROMO_LINKS}", promo_links_text)
    prompt = prompt.replace("{CONTENT_HIGHLIGHTS}", content_highlights_text)
    prompt = prompt.replace("{POST_DESCRIPTIONS}", post_descriptions_text)
    prompt = prompt.replace("{EXAMPLE_CONVERSATIONS}", example_conversations_text)
    prompt = prompt.replace("{RECENT_CHAT_LAST_20_MESSAGES}", recent_chat_text)
    prompt = prompt.replace("{LATEST_MESSAGE}", latest_message_text)

    logger.debug(f"Built system prompt ({len(prompt)} chars)")
    logger.debug(f"Prompt start >>> {prompt} <<< Prompt end")

    return prompt
