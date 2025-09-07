import os
import asyncio
import threading
from flask import Flask
from waitress import serve
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User, Channel, Chat
from dotenv import load_dotenv

# Minimal HTTP server for Render health checks
app = Flask(__name__)

@app.route('/')
def health_check():
    return "🤖 Telegram Forwarder Bot is Running", 200

@app.route('/health')
def health():
    return "OK", 200

def run_web_server():
    """Run a simple HTTP server on port 8000"""
    print("Starting HTTP server on port 8000...")
    serve(app, host='0.0.0.0', port=8000)

# Start HTTP server in background thread
web_thread = threading.Thread(target=run_web_server, daemon=True)
web_thread.start()

# Import keyword configuration
from keywords_config import ALL_KEYWORDS

# Load environment variables from .env file
load_dotenv()

def get_env_var(name, required=True):
    value = os.getenv(name)
    if required and value is None:
        print(f"Error: Environment variable {name} is required but not set")
        sys.exit(1)
    return value

# Get configuration
api_id = int(get_env_var('API_ID'))
api_hash = get_env_var('API_HASH')
dest_group_id = int(get_env_var('DEST_GROUP_ID'))
session_string = get_env_var('SESSION_STRING')

# Get multiple source chats - comma separated list
source_chats_str = get_env_var('SOURCE_CHAT_IDS')
source_chat_ids = [int(chat_id.strip()) for chat_id in source_chats_str.split(',') if chat_id.strip()]

# Get keywords from config
keywords = ALL_KEYWORDS
keywords_lower = [kw.lower() for kw in keywords]

print("🔧 Configuration loaded:")
print(f"   API ID: {api_id}")
print(f"   Source Chats: {len(source_chat_ids)} chats")
print(f"   Destination Group: {dest_group_id}")
print(f"   Keywords: {len(keywords)} keywords")
if len(keywords) <= 10:
    print(f"   Keyword List: {', '.join(keywords)}")

# Create Telegram client
client = TelegramClient(StringSession(session_string), api_id, api_hash)

def get_sender_name(sender):
    """Get the appropriate name for different sender types"""
    if isinstance(sender, User):
        if sender.first_name and sender.last_name:
            return f"{sender.first_name} {sender.last_name}"
        elif sender.first_name:
            return sender.first_name
        elif sender.username:
            return f"@{sender.username}"
        else:
            return "Unknown User"
    
    elif isinstance(sender, Channel) or isinstance(sender, Chat):
        return getattr(sender, 'title', 'Unknown Channel/Chat')
    
    return "Unknown Sender"

def get_sender_username(sender):
    """Get username if available"""
    if isinstance(sender, User):
        return getattr(sender, 'username', None)
    return None

def get_chat_name(chat_id, chat_entity=None):
    """Get chat name for logging"""
    if chat_entity:
        return get_sender_name(chat_entity)
    return f"Chat {chat_id}"

def contains_keyword(message_text, keywords_list):
    """Check if message contains any of the keywords (case-insensitive)"""
    message_lower = message_text.lower()
    matched_keywords = []
    
    for keyword in keywords_list:
        # For multi-word keywords, check if all words are present
        if ' ' in keyword:
            keyword_words = keyword.split()
            if all(word in message_lower for word in keyword_words):
                matched_keywords.append(keyword)
        # For single-word keywords, simple contains check
        elif keyword in message_lower:
            matched_keywords.append(keyword)
    
    return matched_keywords

async def copy_message_content(message, dest_chat_id, source_chat_name):
    """Copy message content instead of forwarding"""
    try:
        # Get sender information
        sender = await message.get_sender()
        sender_name = get_sender_name(sender)
        sender_username = get_sender_username(sender)
        
        # Build the message header with source chat info
        if sender_username:
            header = f"**From {sender_name} (@{sender_username}) in {source_chat_name}:**\n\n"
        else:
            header = f"**From {sender_name} in {source_chat_name}:**\n\n"
        
        message_text = message.text or ""
        full_message = header + message_text
        
        # Send as a new message (copy)
        await client.send_message(
            dest_chat_id,
            full_message,
            link_preview=False
        )
        return True
        
    except Exception as e:
        print(f"   ❌ Error copying message: {e}")
        return False

@client.on(events.NewMessage(chats=source_chat_ids))
async def handler(event):
    try:
        message_text = event.message.text or ""
        sender = await event.get_sender()
        sender_name = get_sender_name(sender)
        
        # Get the source chat entity for better logging
        source_chat_entity = await event.get_chat()
        source_chat_name = get_sender_name(source_chat_entity)
        
        print(f"📨 New message from {sender_name} in {source_chat_name}: {message_text[:100]}...")
        
        # Check if message contains any of our keywords
        matched_keywords = contains_keyword(message_text, keywords_lower)
        
        if matched_keywords:
            print(f"   ✅ Keywords matched: {matched_keywords}")
            print(f"   ➡️ Attempting to forward...")
            
            # First try to forward the message
            try:
                await client.forward_messages(dest_group_id, event.message)
                print(f"   ✅ Message forwarded successfully!")
                
            except Exception as forward_error:
                print(f"   ⚠️ Forward failed: {forward_error}")
                print(f"   ➡️ Trying to copy message content instead...")
                
                # If forwarding fails, try to copy the content
                copy_success = await copy_message_content(event.message, dest_group_id, source_chat_name)
                if copy_success:
                    print(f"   ✅ Message content copied successfully!")
                else:
                    print(f"   ❌ Both forwarding and copying failed!")
                    
        else:
            print(f"   ❌ No keywords matched (ignoring)")
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def main():
    print("🚀 Starting Telegram message forwarder...")
    print(f"🔍 Monitoring {len(source_chat_ids)} source chats")
    print(f"   Total keywords: {len(keywords)}")
    
    try:
        await client.start()
        
        # Verify connection and permissions
        me = await client.get_me()
        me_name = get_sender_name(me)
        print(f"✅ Logged in as: {me_name}")
        
        # Verify destination group access
        try:
            dest_entity = await client.get_entity(dest_group_id)
            dest_name = get_sender_name(dest_entity)
            print(f"✅ Destination group: {dest_name}")
        except Exception as e:
            print(f"❌ Cannot access destination group: {e}")
            return
        
        # Verify source chats access and list them
        source_chat_names = []
        for chat_id in source_chat_ids:
            try:
                chat_entity = await client.get_entity(chat_id)
                chat_name = get_sender_name(chat_entity)
                source_chat_names.append(chat_name)
                print(f"✅ Source chat: {chat_name}")
            except Exception as e:
                print(f"❌ Cannot access source chat {chat_id}: {e}")
                # Remove inaccessible chats from monitoring
                source_chat_ids.remove(chat_id)
        
        if not source_chat_ids:
            print("❌ No accessible source chats to monitor!")
            return
        
        # Send startup message
        try:
            source_list = "\n".join([f"• {name}" for name in source_chat_names])
            keyword_sample = ", ".join(keywords[:5]) + ("..." if len(keywords) > 5 else "")
            
            await client.send_message(
                dest_group_id, 
                f"🤖 Forwarder bot is now online and monitoring!\n\n"
                f"**Monitoring {len(source_chat_names)} sources:**\n{source_list}\n\n"
                f"**Keywords:** {keyword_sample}\n"
                f"**Total Keywords:** {len(keywords)}\n\n"
                "I will forward messages containing your keywords. "
                "If forwarding is restricted, I'll copy the message content instead."
            )
            print("✅ Startup message sent to destination group")
        except Exception as e:
            print(f"⚠️ Could not send startup message: {e}")
        
        print("✅ Bot is running and ready to forward messages!")
        print("💡 Send messages with your keywords to any monitored chat to test")
        
        await client.run_until_disconnected()
        
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())