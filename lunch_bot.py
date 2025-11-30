import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue, CallbackContext 
from datetime import time, timedelta, timezone, datetime 
import json 

# --- Configuration (MUST BE SET) ---
# 1. BOT TOKEN: Loaded from Render Environment Variable (Secret).
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8558478796:AAECHjNWWAQqefRjKX_W4h7lJzJschVpfWU") 
# 2. TARGET CHAT ID: REPLACE WITH YOUR GROUP/CHAT ID (e.g., -1001234567890)
# NOTE: Target Chat ID must be an integer (e.g., -1001234567890).
TARGET_CHAT_ID_RAW = os.environ.get("TARGET_CHAT_ID", "-1003232384383")

# --- Time Constants (Kazakhstan Time Zone - UTC+6) ---
KAZAKHSTAN_TZ = timezone(timedelta(hours=6))
POLL_START_TIME = time(8, 0, 0, tzinfo=KAZAKHSTAN_TZ)   # Poll starts at 08:00 AM KZT (TIME WITH TZINFO)
POLL_END_TIME = time(10, 30, 0, tzinfo=KAZAKHSTAN_TZ) # Poll closes at 10:30 AM KZT (TIME WITH TZINFO)

# --- RENDER ENVIRONMENT VARS ---
PORT = int(os.environ.get("PORT", 8080))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "YOUR_RENDER_URL_HERE") # e.g., https://my-bot-service.onrender.com

# --- Bot Strings (Kazakh Language) ---
POLL_QUESTION = "Сіз түскі ас ішесіз бе?"
YES_OPTION = "Иә"
NO_OPTION = "Жоқ"
WELCOME_MESSAGE = (
    "🤖 *Түскі Ас Ботқа Қош Келдіңіз!* 🤖\n\n"
    "Бұл бот Webhook режимінде жұмыс істейді.\n\n"
    "**Дауыс беру уақыты: 08:00 - 10:30 (Астана уақыты).**\n"
    "Дауыс беру *автоматты түрде* сағат 08:00-де басталып, 10:30-да нәтижелерді жариялаумен аяқталады.\n\n"
    "Ағымдағы нәтижелерді көру үшін `/results` пәрменін пайдаланыңыз.\n"
    "*Әкімшілер қолмен бастау үшін `/poll` пәрменін қолдана алады.*"
)
POLL_STARTED = "📢 *Дауыс беру басталды!* 📢\n\n"
POLL_ENDED_ANNOUNCEMENT = "🛑 *Дауыс беру аяқталды!* 🛑\n\n"
POLL_INACTIVE_ALERT = "Бұл дауыс беру аяқталды немесе белсенді емес."
POLL_ENDED_BY_TIME = "Дауыс беру уақыты аяқталды (10:30)."
VOTE_REGISTERED_ALERT = "Сіздің дауысыңыз тіркелді. Рахмет!" 
RESULTS_HEADER = "📋 *Түскі Ас Дауыс Беру Нәтижелері* 📋\n\n"
NOT_ACTIVE_MESSAGE = "Дауыс беру қазір белсенді емес. Келесі дауыс беруді сағат 08:00-де күтіңіз." 
ONLY_IN_TARGET_CHAT = "Бұл пәрменді тек тағайындалған топта ғана қолдануға болады."
# New strings for manual poll feature
MANUAL_POLL_STARTED = "✅ *Дауыс беру қолмен іске қосылды.*"
NOT_ADMIN_MESSAGE = "❌ Бұл әрекетті орындауға сіздің әкімші құқығыңыз жоқ."

# Global variable to hold the integer chat ID, initialized in main()
TARGET_CHAT_ID = None 

# --- State Management (In-Memory/Global - NOTE: This will reset on Free Tier spin-down) ---
poll_state = {
    'is_active': False,
    'yes_voters': {}, 
    'no_voters': {},  
    'poll_message_id': None,
    'target_chat_id': None, # Will be set in main()
    'lunch_date': None,       
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
            # Ensure target_chat_id is loaded as an integer if available
            if 'target_chat_id' in data:
                 # It might be stored as string or int, ensure it's an int
                poll_state['target_chat_id'] = int(data['target_chat_id'])
    except (FileNotFoundError, json.JSONDecodeError):
        logger.info("No saved state found or file corrupted. Starting clean.")
        # If load fails, target_chat_id remains None until main() runs
        pass

def save_state():
    """Saves poll state to a file."""
    try:
        # Copy and ensure target_chat_id is stored as string for JSON serialization
        state_to_save = poll_state.copy()
        if state_to_save.get('target_chat_id') is not None:
            state_to_save['target_chat_id'] = str(poll_state['target_chat_id']) 
        with open(STATE_FILE, 'w') as f:
            json.dump(state_to_save, f, indent=4)
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

def check_and_expire_poll() -> bool:
    """
    Checks if the poll is currently expired based on the set lunch date and KZT time (10:30 AM).
    If expired, it sets is_active to False and saves state.
    Returns True if the poll was active and is now expired, False otherwise.
    """
    if not poll_state['is_active'] or not poll_state['lunch_date']:
        return False

    try:
        # 1. Get current date/time in Kazakhstan time
        now_kz = datetime.now(KAZAKHSTAN_TZ)
        
        # 2. Convert poll date string to a date object
        poll_date_dt = datetime.strptime(poll_state['lunch_date'], '%Y-%m-%d').date()

        # Check if today is the lunch day and time is past POLL_END_TIME (excluding tzinfo for comparison), OR if today is past the lunch day
        is_past_end_time = (now_kz.date() == poll_date_dt and now_kz.time() > POLL_END_TIME.replace(tzinfo=None)) or (now_kz.date() > poll_date_dt)

        if is_past_end_time:
            poll_state['is_active'] = False
            save_state()
            logger.info(f"Poll for {poll_state['lunch_date']} automatically expired by check at {now_kz.time()}.")
            return True
        
        return False
        
    except ValueError:
        logger.error("Invalid date format stored in poll_state. Expiring poll to be safe.")
        poll_state['is_active'] = False
        save_state()
        return True 

# --- Scheduled Job Functions ---

async def start_poll_job(context: CallbackContext):
    """Starts the poll automatically at 08:00 AM KZT or when manually triggered."""
    global poll_state
    
    load_state() 

    if poll_state['target_chat_id'] is None:
        logger.error("start_poll_job failed: TARGET_CHAT_ID is not set in poll_state.")
        return

    # 1. Get today's date in YYYY-MM-DD format (Automatic Date)
    now_kz = datetime.now(KAZAKHSTAN_TZ)
    lunch_date_str = now_kz.strftime('%Y-%m-%d')
    
    logger.info(f"Start job triggered for {lunch_date_str}.")

    if poll_state['is_active'] and poll_state['lunch_date'] == lunch_date_str:
        # This check is mainly for the scheduled job, but harmless for manual trigger if state is checked beforehand
        logger.info("Poll already active for today. Skipping start.")
        return
        
    # 2. Reset state and set new parameters
    poll_state['is_active'] = True
    poll_state['yes_voters'] = {}
    poll_state['no_voters'] = {}
    poll_state['poll_message_id'] = None
    poll_state['lunch_date'] = lunch_date_str # Set today's date
    
    # 3. Construct the poll message
    date_text = f"📅 Күні: *{lunch_date_str}*."
    
    full_poll_text = (
        f"{POLL_STARTED}"
        f"{date_text}\n\n"
        f"{POLL_QUESTION}"
    )

    # 4. Send poll message
    try:
        message = await context.bot.send_message(
            chat_id=poll_state['target_chat_id'],
            text=full_poll_text,
            reply_markup=create_poll_keyboard(),
            parse_mode='Markdown'
        )
        poll_state['poll_message_id'] = message.message_id
        save_state()
        logger.info(f"New poll started for {lunch_date_str}.")

    except Exception as e:
        logger.error(f"Error starting poll: {e}. Ensuring state is inactive.")
        poll_state['is_active'] = False
        save_state()


async def end_poll_job(context: CallbackContext):
    """Ends the poll automatically at 10:30 AM KZT and shows results."""
    global poll_state
    
    load_state() 
    
    now_kz = datetime.now(KAZAKHSTAN_TZ)
    today_date_str = now_kz.strftime('%Y-%m-%d')
    
    logger.info(f"Scheduled end job triggered for {today_date_str}.")
    
    if poll_state['target_chat_id'] is None:
        logger.error("end_poll_job failed: TARGET_CHAT_ID is not set in poll_state.")
        return

    # Only end the poll if it is active AND it is the correct day
    if poll_state['is_active'] and poll_state['lunch_date'] == today_date_str:
        
        poll_state['is_active'] = False
        save_state()
        logger.info(f"Poll for {today_date_str} successfully ended by scheduled job.")

        final_results = format_results_message()
        
        # Announce results
        try:
            await context.bot.send_message(
                chat_id=poll_state['target_chat_id'],
                text=f"{POLL_ENDED_ANNOUNCEMENT}{final_results}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error sending final results: {e}")
            
    else:
        logger.info(f"End job skipped. Poll not active or not for today ({poll_state['lunch_date']}).")
        


# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message and explains the bot."""
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode='Markdown')

async def results_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the current voting results."""
    load_state() 
    
    # If the global TARGET_CHAT_ID wasn't set (e.g., initial run), fall back to global constant for comparison
    target_chat_id_for_check = poll_state.get('target_chat_id') or TARGET_CHAT_ID

    # Check 1: Chat validation
    is_private_chat = update.message.chat.type == "private"
    is_target_chat = update.effective_chat.id == target_chat_id_for_check

    if not is_private_chat and not is_target_chat:
        await update.message.reply_text(ONLY_IN_TARGET_CHAT)
        return
        
    # Check 2: Automatic Expiry Check
    is_expired = check_and_expire_poll()
    if is_expired:
        await update.message.reply_text(f"{POLL_ENDED_ANNOUNCEMENT}{format_results_message()}", parse_mode='Markdown')
        return

    if not poll_state['is_active']:
        await update.message.reply_text(NOT_ACTIVE_MESSAGE)
        return

    results = format_results_message()
    await update.message.reply_text(results, parse_mode='Markdown')

async def manual_poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Allows group administrators to manually start the poll using /poll.
    """
    load_state()

    # Check 1: Must be in the target group
    target_chat_id = poll_state.get('target_chat_id')
    if update.effective_chat.id != target_chat_id:
        await update.message.reply_text(ONLY_IN_TARGET_CHAT)
        return

    user = update.effective_user
    
    try:
        # Check 2: Must be an administrator or creator of the chat
        chat_member = await context.bot.get_chat_member(target_chat_id, user.id)
        
        if chat_member.status not in ['administrator', 'creator']:
            await update.message.reply_text(NOT_ADMIN_MESSAGE)
            return

        # Check 3: Only allow manual poll if no poll is currently active for today
        now_kz = datetime.now(KAZAKHSTAN_TZ)
        today_date_str = now_kz.strftime('%Y-%m-%d')
        
        if poll_state['is_active'] and poll_state['lunch_date'] == today_date_str:
            await update.message.reply_text("❌ *Қате:* Бүгінгі күнге арналған дауыс беру қазірдің өзінде белсенді.", parse_mode='Markdown')
            return

        # Start the poll immediately (reusing start_poll_job logic)
        await start_poll_job(context)
        await update.message.reply_text(MANUAL_POLL_STARTED, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error checking admin status or starting manual poll: {e}")
        await update.message.reply_text("❌ Қолмен дауыс беруді бастау кезінде қате пайда болды.")
        
# --- Callback Query Handler (Button Clicks) ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks (Yes/No votes)."""
    query = update.callback_query
    await query.answer() # Immediately answer the callback query to remove the loading state

    load_state() 

    # Check 1: Automatic Expiry Check
    is_expired = check_and_expire_poll()
    if is_expired:
        # Send a failure alert and stop processing
        await query.answer(text=POLL_ENDED_BY_TIME, show_alert=True)
        return

    # Check 2: Poll must be active
    if not poll_state['is_active']:
        await query.answer(text=POLL_INACTIVE_ALERT, show_alert=True)
        return

    user = query.from_user
    user_id = user.id
    user_name = get_voter_name(user) 

    vote_type = query.data # 'vote_yes' or 'vote_no'
    
    # Check current vote state and update lists
    if vote_type == 'vote_yes':
        if user_id in poll_state['yes_voters']:
            await query.answer(text=f"Сіздің дауысыңыз *{YES_OPTION}* болып тіркелген.", show_alert=False) 
            return
        
        poll_state['yes_voters'][user_id] = user_name
        poll_state['no_voters'].pop(user_id, None) 
        
    elif vote_type == 'vote_no':
        if user_id in poll_state['no_voters']:
            await query.answer(text=f"Сіздің дауысыңыз *{NO_OPTION}* болып тіркелген.", show_alert=False)
            return
            
        poll_state['no_voters'][user_id] = user_name
        poll_state['yes_voters'].pop(user_id, None) 

    save_state()
    # 2) When users click yes or no, there should be a notification like your response has been recorded
    await query.answer(text=VOTE_REGISTERED_ALERT, show_alert=False)


# --- Application Initialization (Webhook Mode) ---

def main():
    """
    Starts the bot in Webhook mode and sets up the automatic scheduling (JobQueue).
    """
    global TARGET_CHAT_ID, poll_state
    
    # 1. Configuration Validation and Type Conversion
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("FATAL: BOT_TOKEN is missing. Please set the Render Secret.")
        return
    
    if RENDER_EXTERNAL_URL == "YOUR_RENDER_URL_HERE":
         logger.error("FATAL: RENDER_EXTERNAL_URL is missing. Please set the Render Environment Variable.")
         return

    try:
        # Ensure TARGET_CHAT_ID is set globally as an integer from the environment
        TARGET_CHAT_ID = int(TARGET_CHAT_ID_RAW)
        # Update poll_state with the validated integer chat ID
        poll_state['target_chat_id'] = TARGET_CHAT_ID 
    except ValueError:
        logger.error(f"FATAL: TARGET_CHAT_ID environment variable '{TARGET_CHAT_ID_RAW}' is not a valid integer.")
        return
        
    # Load any potentially saved state (unreliable on free tier but necessary)
    load_state()

    # 2. Create the Application and JobQueue
    # FIX for AttributeError: 'ApplicationBuilder' object has no attribute 'tzinfo'
    # The 'tzinfo' parameter is removed from Application.builder() and only the time objects
    # used in run_daily need to contain the timezone information.
    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    # 3. Schedule and Start JobQueue 
    if job_queue:
        # The time objects (POLL_START_TIME, POLL_END_TIME) now contain tzinfo directly (see line 19/20)
        job_queue.run_daily(
            start_poll_job, 
            POLL_START_TIME, 
            days=(0, 1, 2, 3, 4, 5, 6),
            name='daily_poll_start'
        )
        
        job_queue.run_daily(
            end_poll_job, 
            POLL_END_TIME, 
            days=(0, 1, 2, 3, 4, 5, 6),
            name='daily_poll_end'
        )
        
        logger.info(f"Jobs scheduled for start at {POLL_START_TIME.strftime('%H:%M')} and end at {POLL_END_TIME.strftime('%H:%M')} KZT.")

        # --- FIX: Start the scheduler manually for webhook mode ---
        job_queue.start()
        logger.info("JobQueue scheduler started successfully.")
    else:
        logger.error("JobQueue could not be initialized. Please ensure 'python-telegram-bot[job-queue]' is installed.")
        # If job_queue is None, the application cannot run scheduled tasks.

    # 4. Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("results", results_command))
    # NEW: Handler for manual poll command with admin check
    application.add_handler(CommandHandler("poll", manual_poll_command)) 
    application.add_handler(CallbackQueryHandler(button_handler))

    # 5. Start Webhook
    webhook_url = f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}"
    
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=webhook_url
    )
    logger.info(f"Bot started in Webhook mode, listening on port {PORT}. Webhook URL: {webhook_url}")

if __name__ == '__main__':
    main()
