import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import time, timedelta, timezone
import json # Added for temporary data storage

# --- Configuration (MUST BE SET) ---
# 1. BOT TOKEN: Loaded from Render Environment Variable (Secret).
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE") 
# 2. TARGET CHAT ID: REPLACE WITH YOUR GROUP/CHAT ID (e.g., -1001234567890)
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID", "YOUR_TARGET_CHAT_ID_HERE") 
# 3. RENDER ENVIRONMENT VARS
PORT = int(os.environ.get("PORT", 8080))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "YOUR_RENDER_URL_HERE") # e.g., https://my-bot-service.onrender.com

# --- Bot Strings (Kazakh Language) ---
POLL_QUESTION = "Сіз бүгін түскі ас ішесіз бе?"
YES_OPTION = "Иә"
NO_OPTION = "Жоқ"
WELCOME_MESSAGE = (
    "🤖 *Түскі Ас Ботқа Қош Келдіңіз!* 🤖\n\n"
    "Бұл бот Webhook режимінде жұмыс істейді. Дауыс беруді бастау үшін: `/poll` пәрменін жіберіңіз.\n\n"
    "Ағымдағы нәтижелерді көру үшін `/results` пәрменін пайдаланыңыз."
)
POLL_STARTED = "📢 *Дауыс беру басталды!* 📢\n\n"
POLL_ENDED_ANNOUNCEMENT = "🛑 *Дауыс беру аяқталды!* 🛑\n\n"
POLL_INACTIVE_ALERT = "Бұл дауыс беру аяқталды немесе белсенді емес."
VOTE_REGISTERED_ALERT = "Дауысыңыз тіркелді! Ағымдағы нәтижелер үшін /results пәрменін пайдаланыңыз."
RESULTS_HEADER = "📋 *Түскі Ас Дауыс Беру Нәтижелері* 📋\n\n"
NOT_ACTIVE_MESSAGE = "Дауыс беру қазір белсенді емес. Оны бастау үшін `/poll` пәрменін пайдаланыңыз."
ONLY_IN_TARGET_CHAT = "Бұл пәрменді тек тағайындалған топта ғана қолдануға болады."

# --- State Management (In-Memory/Global - NOTE: This will reset on Free Tier spin-down) ---
# FOR PERSISTENCE: State is manually managed by the user using /poll and /endpoll.
poll_state = {
    'is_active': False,
    'yes_voters': {}, # {user_id: full_name}
    'no_voters': {},  # {user_id: full_name}
    'poll_message_id': None,
    'target_chat_id': TARGET_CHAT_ID 
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

def get_voter_name(update: Update) -> str:
    """Returns the voter's full name."""
    user = update.effective_user
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
    
    message = (
        f"{RESULTS_HEADER}"
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
        
    if not poll_state['is_active']:
        await update.message.reply_text(NOT_ACTIVE_MESSAGE)
        return

    results = format_results_message()
    await update.message.reply_text(results, parse_mode='Markdown')

async def manual_poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually starts the poll (replaces the scheduled start)."""
    global poll_state
    
    # Restrict usage to the target chat ID for security
    if str(update.effective_chat.id) != str(poll_state['target_chat_id']):
         await update.message.reply_text(ONLY_IN_TARGET_CHAT)
         return
         
    # 1. Reset state for the new poll
    poll_state['is_active'] = True
    poll_state['yes_voters'] = {}
    poll_state['no_voters'] = {}
    poll_state['poll_message_id'] = None
    
    logger.info("Starting new lunch poll via /poll command.")
    
    # 2. Send poll message
    try:
        message = await context.bot.send_message(
            chat_id=poll_state['target_chat_id'],
            text=f"{POLL_STARTED}{POLL_QUESTION}",
            reply_markup=create_poll_keyboard(),
            parse_mode='Markdown'
        )
        poll_state['poll_message_id'] = message.message_id
        save_state()
        await update.message.reply_text("✅ *Дауыс беру сәтті басталды!*")

    except Exception as e:
        logger.error(f"Error starting poll: {e}")
        poll_state['is_active'] = False 
        await update.message.reply_text("❌ Дауыс беруді бастау мүмкін болмады. Боттың топта хабарлама жіберуге рұқсаты бар-жоғын тексеріңіз.")
        
async def manual_end_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually ends the poll (replaces the scheduled end)."""
    global poll_state
    
    # Restrict usage to the target chat ID for security
    if str(update.effective_chat.id) != str(poll_state['target_chat_id']):
         await update.message.reply_text(ONLY_IN_TARGET_CHAT)
         return
         
    if not poll_state['is_active']:
        await update.message.reply_text(NOT_ACTIVE_MESSAGE)
        return

    poll_state['is_active'] = False
    logger.info("Ending lunch poll via /endpoll command.")
    
    final_results = format_results_message()
    
    # Send final notification and results (new message)
    await context.bot.send_message(
        chat_id=poll_state['target_chat_id'],
        text=f"{POLL_ENDED_ANNOUNCEMENT}{final_results}",
        parse_mode='Markdown'
    )
    save_state()
    await update.message.reply_text("✅ *Дауыс беру сәтті аяқталды және нәтижелері жарияланды!*")


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

    user_id = query.from_user.id
    user_name = get_voter_name(query)
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
    application.add_handler(CommandHandler("endpoll", manual_end_command))
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
