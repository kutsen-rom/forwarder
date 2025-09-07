import os
import asyncio
import threading
import sys
from flask import Flask
from waitress import serve
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User, Channel, Chat
from dotenv import load_dotenv
from sources_config import SOURCES, get_all_sources, get_keywords_for_source, get_source_name

# Load environment variables from .env file
load_dotenv()

# Minimal HTTP server for Render health checks
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Service is Running", 200

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

# Get sources from config
source_chat_ids = get_all_sources()

print("🔧 Configuration loaded:")
print(f"   API ID: {api_id}")
print(f"   Destination Group: {dest_group_id}")
print(f"   Monitoring {len(SOURCES)} sources:")

for source_name, source_info in SOURCES.items():
    keywords = source_info["KEYWORDS"]
    print(f"     • {source_name}: {len(keywords)} keywords")

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

async def copy_message_content(message, dest_chat_id, source_chat_name, sender_name, sender_username=None):
    """Copy message content instead of forwarding"""
    try:
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
        sender_username = get_sender_username(sender)
        
        # Get the source chat info
        source_chat_id = event.chat_id
        source_chat_entity = await event.get_chat()
        source_chat_name = get_sender_name(source_chat_entity)
        source_config_name = get_source_name(source_chat_id)
        
        # Get keywords specific to this source
        source_keywords = get_keywords_for_source(source_chat_id)
        source_keywords_lower = [kw.lower() for kw in source_keywords]
        
        print(f"📨 New message from {sender_name} in {source_config_name}: {message_text[:100]}...")
        
        # Check if message contains any of this source's keywords
        matched_keywords = contains_keyword(message_text, source_keywords_lower)
        
        if matched_keywords:
            print(f"   ✅ Keywords matched for {source_config_name}: {matched_keywords}")
            print(f"   ➡️ Attempting to forward...")
            
            # First try to forward the message
            try:
                await client.forward_messages(dest_group_id, event.message)
                print(f"   ✅ Message forwarded successfully!")
                
            except Exception as forward_error:
                print(f"   ⚠️ Forward failed: {forward_error}")
                print(f"   ➡️ Trying to copy message content instead...")
                
                # If forwarding fails, try to copy the content
                copy_success = await copy_message_content(
                    event.message, dest_group_id, source_config_name, sender_name, sender_username
                )
                if copy_success:
                    print(f"   ✅ Message content copied successfully!")
                else:
                    print(f"   ❌ Both forwarding and copying failed!")
                    
        else:
            print(f"   ❌ No keywords matched for {source_config_name} (ignoring)")
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def main():
    print("🚀 Starting message forwarder...")
    print(f"🔍 Monitoring {len(SOURCES)} sources with source-specific keywords")
    
    try:
        await client.start()
        
        # Verify connection and permissions
        me = await client.get_me()
        me_name = get_sender_name(me)
        
        # Verify destination group access
        try:
            dest_entity = await client.get_entity(dest_group_id)
            dest_name = get_sender_name(dest_entity)
        except Exception as e:
            print(f"❌ Cannot access destination group: {e}")
            return
        
        # Verify source chats access and collect info for startup message
        source_info_list = []
        inaccessible_sources = []
        
        for source_name, source_info in SOURCES.items():
            chat_id = source_info["SOURCE"]
            try:
                chat_entity = await client.get_entity(chat_id)
                chat_display_name = get_sender_name(chat_entity)
                keywords = source_info["KEYWORDS"]
                
                source_info_list.append({
                    'config_name': source_name,
                    'display_name': chat_display_name,
                    'keywords': keywords,
                    'keyword_count': len(keywords)
                })
                

                
            except Exception as e:
                print(f"❌ Cannot access source {source_name} ({chat_id}): {e}")
                inaccessible_sources.append(source_name)
                # Remove inaccessible chat from monitoring
                if chat_id in source_chat_ids:
                    source_chat_ids.remove(chat_id)
        
        if not source_chat_ids:
            print("❌ No accessible source chats to monitor!")
            return
        
        # Send detailed startup message
        try:
            startup_message = "🤖 Forwarder bot is now online and monitoring!\n\n"
            startup_message += f"**Monitoring {len(source_info_list)} sources:**\n"
            
            for source in source_info_list:
                startup_message += f"• {source['display_name']}\n"
            
            startup_message += "\n"
            
            for source in source_info_list:
                keyword_sample = ", ".join(source['keywords'])
                
                startup_message += f"**{source['display_name']} Keywords:** {keyword_sample}\n"
                startup_message += f"**Total Keywords:** {source['keyword_count']}\n\n"
            
            if inaccessible_sources:
                startup_message += f"⚠️ **Unable to access:** {', '.join(inaccessible_sources)}\n\n"
            
            startup_message += "I will forward messages containing your keywords. If forwarding is restricted, I'll copy the message content instead."
            
            await client.send_message(dest_group_id, startup_message)
            
        except Exception as e:
            print(f"⚠️ Could not send startup message: {e}")
        
        print("✅ Bot is running and ready to forward messages!")
        print("💡 Send messages with specific keywords to monitored sources to test")
        
        await client.run_until_disconnected()
        
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())