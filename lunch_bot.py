import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import time, timedelta, timezone, datetime # Import datetime for date parsing
import json 

# --- Configuration (MUST BE SET) ---
# 1. BOT TOKEN: Loaded from Render Environment Variable (Secret).
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8558478796:AAECHjNWWAQqefRjKX_W4h7lJzJschVpfWU") 
# 2. TARGET CHAT ID: REPLACE WITH YOUR GROUP/CHAT ID (e.g., -1001234567890)
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID", "-1003232384383") 
# 3. RENDER ENVIRONMENT VARS
PORT = int(os.environ.get("PORT", 8080))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "YOUR_RENDER_URL_HERE") # e.g., https://my-bot-service.onrender.com

# --- Bot Strings (Kazakh Language) ---
# Question is now general, date is added separately
POLL_QUESTION = "Сіз түскі ас ішесіз бе?"
YES_OPTION = "Иә"
NO_OPTION = "Жоқ"
WELCOME_MESSAGE = (
    "🤖 *Түскі Ас Ботқа Қош Келдіңіз!* 🤖\n\n"
    "Бұл бот Webhook режимінде жұмыс істейді.\n\n"
    "Дауыс беруді бастау үшін кез келген қатысушы келесі пәрменді қолдануы керек:\n"
    "`/poll YYYY-MM-DD`\n\n"
    "Ағымдағы нәтижелерді көру үшін `/results` пәрменін пайдаланыңыз."
)
POLL_STARTED = "📢 *Дауыс беру басталды!* 📢\n\n"
POLL_ENDED_ANNOUNCEMENT = "🛑 *Дауыс беру аяқталды!* 🛑\n\n"
POLL_INACTIVE_ALERT = "Бұл дауыс беру аяқталды немесе белсенді емес."
VOTE_REGISTERED_ALERT = "Дауысыңыз тіркелді! Ағымдағы нәтижелер үшін /results пәрменін пайдаланыңыз."
RESULTS_HEADER = "📋 *Түскі Ас Дауыс Беру Нәтижелері* 📋\n\n"
# NOTE: The instructions for starting the poll are updated here
NOT_ACTIVE_MESSAGE = "Дауыс беру қазір белсенді емес. Оны бастау үшін `/poll YYYY-MM-DD` пәрменін пайдаланыңыз." 
ONLY_IN_TARGET_CHAT = "Бұл пәрменді тек тағайындалған топта ғана қолдануға болады."
# NOT_ADMIN_MESSAGE has been removed as admins are no longer required

# --- State Management (In-Memory/Global - NOTE: This will reset on Free Tier spin-down) ---
poll_state = {
    'is_active': False,
    'yes_voters': {}, # {user_id: full_name}
    'no_voters': {},  # {user_id: full_name}
    'poll_message_id': None,
    'target_chat_id': TARGET_CHAT_ID,
    'lunch_date': None,       # Date of the planned lunch
}
STATE_FILE = "poll_state.json" 

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- State Persistence (Simple file read/write - not reliable on Render Free Tier but included for structure) ---
def load_state():
    """Loads poll state from a file."""
    global poll_state
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
            poll_state.update(data)
            poll_state['target_chat_id'] = TARGET_CHAT_ID # Ensure it uses the env variable after load
    except (FileNotFoundError, json.JSONDecodeError):
        logger.info("No saved state found or file corrupted. Starting clean.")

def save_state():
    """Saves poll state to a file."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(poll_state, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving state: {e}")

# --- Utility Functions ---

def get_voter_name(user: User) -> str:
    """Returns the voter's full name from a Telegram User object."""
    if user.last_name:
        return f"{user.first_name} {user.last_name}"
    return user.first_name

def create_poll_keyboard():
    """Generates the inline keyboard for the poll."""
    keyboard = [
        [
            InlineKeyboardButton(YES_OPTION, callback_data='vote_yes'),
            InlineKeyboardButton(NO_OPTION, callback_data='vote_no'),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def format_results_message():
    """Generates the formatted results string."""
    yes_list = "\n- " + "\n- ".join(poll_state['yes_voters'].values()) if poll_state['yes_voters'] else "Ешкім дауыс бермеді"
    no_list = "\n- " + "\n- ".join(poll_state['no_voters'].values()) if poll_state['no_voters'] else "Ешкім дауыс бермеді"
    
    total_votes = len(poll_state['yes_voters']) + len(poll_state['no_voters'])
    
    # Only include Date
    date_info = f"📅 Күні: *{poll_state['lunch_date']}*" if poll_state['lunch_date'] else "📅 Күні: *Белгісіз*"
    
    message = (
        f"{RESULTS_HEADER}"
        f"{date_info}\n\n"
        f"Сұрақ: _{POLL_QUESTION}_\n\n"
        f"✅ *{YES_OPTION}* ({len(poll_state['yes_voters'])}):\n"
        f"{yes_list}\n\n"
        f"❌ *{NO_OPTION}* ({len(poll_state['no_voters'])}):\n"
        f"{no_list}\n\n"
        f"Барлығы дауыс берді: *{total_votes}*"
    )
    return message


# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message and explains the bot."""
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode='Markdown')

async def results_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the current voting results."""
    # Load state first as the service might have spun up from sleep
    load_state() 
    
    # Only allow command if in the target chat OR if chat is private (for single user testing)
    is_private_chat = update.message.chat.type == "private"
    is_target_chat = str(update.effective_chat.id) == str(poll_state['target_chat_id'])

    if not is_private_chat and not is_target_chat:
        await update.message.reply_text(ONLY_IN_TARGET_CHAT)
        return
        
    # NOTE: Since there is no /endpoll, the poll remains active until a new one is started or the server resets.
    if not poll_state['is_active']:
        await update.message.reply_text(NOT_ACTIVE_MESSAGE)
        return

    results = format_results_message()
    await update.message.reply_text(results, parse_mode='Markdown')

async def manual_poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the poll. Usage: /poll YYYY-MM-DD"""
    global poll_state
    
    # Check 1: Must be in the target group chat
    current_chat_id = str(update.effective_chat.id)
    if current_chat_id != str(poll_state['target_chat_id']):
         await update.message.reply_text(ONLY_IN_TARGET_CHAT)
         return
    
    # Check 2: Parse arguments
    args = context.args
    if not args or len(args) > 1:
        await update.message.reply_text(
            "❌ *Қате:* Түскі ас күнін көрсетіңіз. Үлгі: `/poll YYYY-MM-DD`",
            parse_mode='Markdown'
        )
        return

    lunch_date_str = args[0]

    # Validate Date
    try:
        # Check if it's a valid date format YYYY-MM-DD
        datetime.strptime(lunch_date_str, '%Y-%m-%d')
    except ValueError:
        await update.message.reply_text(
            "❌ *Қате:* Күн форматы дұрыс емес. YYYY-MM-DD үлгісін қолданыңыз.",
            parse_mode='Markdown'
        )
        return

    # A poll is always closed when a new one is started.
    is_active_before_new_poll = poll_state['is_active']
    
    # 1. Reset state and set new parameters
    poll_state['is_active'] = True
    poll_state['yes_voters'] = {}
    poll_state['no_voters'] = {}
    poll_state['poll_message_id'] = None
    poll_state['lunch_date'] = lunch_date_str
    
    logger.info(f"Starting new lunch poll for {lunch_date_str}.")

    # Announce results of the *previous* poll if it was active
    if is_active_before_new_poll:
        # Generate results message based on *old* state data before reset (though reset happens above, 
        # for simplicity, we rely on the fact that results will be generated from the new state, but 
        # user feedback says a new poll replaces the old one without explicit result announcement.)
        pass # Not announcing old results as per user's preference to keep it simple (no /endpoll)
    
    # 2. Construct the poll message
    date_text = f"📅 Күні: *{lunch_date_str}*."
    
    full_poll_text = (
        f"{POLL_STARTED}"
        f"{date_text}\n\n"
        f"{POLL_QUESTION}"
    )

    # 3. Send poll message
    try:
        message = await context.bot.send_message(
            chat_id=poll_state['target_chat_id'],
            text=full_poll_text,
            reply_markup=create_poll_keyboard(),
            parse_mode='Markdown'
        )
        poll_state['poll_message_id'] = message.message_id
        save_state()
        await update.message.reply_text("✅ *Дауыс беру сәтті басталды!*", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error starting poll: {e}")
        poll_state['is_active'] = False 
        await update.message.reply_text("❌ Дауыс беруді бастау мүмкін болмады. Боттың топта хабарлама жіберуге рұқсаты бар-жоғын тексеріңіз.", parse_mode='Markdown')
        
# Removed async def manual_end_command...


# --- Callback Query Handler (Button Clicks) ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks (Yes/No votes)."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press
    
    # Load state on button click
    load_state() 

    if not poll_state['is_active']:
        await query.answer(text=POLL_INACTIVE_ALERT, show_alert=True)
        return

    user = query.from_user
    user_id = user.id
    user_name = get_voter_name(user) # Pass the User object

    vote_type = query.data # 'vote_yes' or 'vote_no'
    
    # Check current vote state and update lists
    if vote_type == 'vote_yes':
        if user_id in poll_state['yes_voters']:
            await query.answer(text=f"Сіздің дауысыңыз *{YES_OPTION}* болып тіркелген.", show_alert=True)
            return
        
        poll_state['yes_voters'][user_id] = user_name
        poll_state['no_voters'].pop(user_id, None) # Remove if they were 'No'
        
    elif vote_type == 'vote_no':
        if user_id in poll_state['no_voters']:
            await query.answer(text=f"Сіздің дауысыңыз *{NO_OPTION}* болып тіркелген.", show_alert=True)
            return
            
        poll_state['no_voters'][user_id] = user_name
        poll_state['yes_voters'].pop(user_id, None) # Remove if they were 'Yes'

    save_state()
    await query.answer(text=VOTE_REGISTERED_ALERT)


# --- Application Initialization (Webhook Mode) ---

def main():
    """Starts the bot in Webhook mode."""
    # Ensure configuration is complete before running
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("FATAL: BOT_TOKEN is missing. Please set the Render Secret.")
        return
    if TARGET_CHAT_ID == "YOUR_TARGET_CHAT_ID_HERE":
         logger.error("FATAL: TARGET_CHAT_ID is missing. Please set the Render Environment Variable.")
         return
    if RENDER_EXTERNAL_URL == "YOUR_RENDER_URL_HERE":
         logger.error("FATAL: RENDER_EXTERNAL_URL is missing. Please set the Render Environment Variable.")
         return
    
    # Load any potentially saved state (though unreliable on free tier)
    load_state()

    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("results", results_command))
    application.add_handler(CommandHandler("poll", manual_poll_command))
    # application.add_handler(CommandHandler("endpoll", manual_end_command)) # Removed /endpoll handler
    application.add_handler(CallbackQueryHandler(button_handler))

    # --- Start Webhook ---
    # The URL Telegram sends updates to is RENDER_EXTERNAL_URL/BOT_TOKEN
    webhook_url = f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}"
    
    # Set up the webhook before running the bot
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=webhook_url
    )
    logger.info(f"Bot started in Webhook mode, listening on port {PORT}. Webhook URL: {webhook_url}")

if __name__ == '__main__':
    main()
