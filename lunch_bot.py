import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import time, timedelta, timezone

# --- Configuration ---
# 1. BOT TOKEN: Loaded from Render Environment Variable (Secret).
#    If testing locally, replace "YOUR_BOT_TOKEN_HERE" with your actual token.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8558478796:AAECHjNWWAQqefRjKX_W4h7lJzJschVpfWU") 
# 2. TARGET CHAT ID: REPLACE WITH YOUR GROUP/CHAT ID (e.g., -1001234567890)
#    MUST be a string for the bot to use it correctly.
TARGET_CHAT_ID = "-1003232384383" 

# Kazakh language strings
POLL_QUESTION = "Сіз бүгін түскі ас ішесіз бе?"
YES_OPTION = "Иә"
NO_OPTION = "Жоқ"
WELCOME_MESSAGE = (
    "🤖 *Түскі Ас Ботқа Қош Келдіңіз!* 🤖\n\n"
    "Мен күнделікті түскі асқа тапсырыс беру үшін дауыс беруді басқарамын.\n\n"
    "🗓️ *Күнделікті кесте:*\n"
    "  - Басталуы: 18:00 (KAZ уақытымен)\n"
    "  - Аяқталуы: Келесі күні 10:00 (KAZ уақытымен)\n\n"
    "Ағымдағы нәтижелерді көру үшін `/results` пәрменін пайдаланыңыз."
)
POLL_STARTED = "📢 *Дауыс беру басталды!* 📢\n\n"
POLL_ENDED_ANNOUNCEMENT = "🛑 *Дауыс беру аяқталды!* 🛑\n\n"
POLL_INACTIVE_ALERT = "Бұл дауыс беру аяқталды немесе белсенді емес."
VOTE_REGISTERED_ALERT = "Дауысыңыз тіркелді! Ағымдағы нәтижелер үшін /results пәрменін пайдаланыңыз."
RESULTS_HEADER = "📋 *Түскі Ас Дауыс Беру Нәтижелері* 📋\n\n"
NOT_ACTIVE_MESSAGE = "Дауыс беру қазір белсенді емес. Келесі дауыс беруді күтіңіз."
ONLY_IN_TARGET_CHAT = "Бұл пәрменді тек тағайындалған топта ғана қолдануға болады."


# Time zone: UTC +5 is used for standard time in Kazakhstan (e.g., Almaty/Astana time).
# If you are in a UTC+6 region, change 'hours=5' to 'hours=6'.
KAZ_TZ = timezone(timedelta(hours=5))

# Scheduling times (relative to KAZ_TZ)
START_HOUR = 18  # 6:00 PM (Evening before)
END_HOUR = 10    # 10:00 AM (Morning of)

# --- State Management (In-Memory) ---
# Stores the current voting state for the active poll.
poll_state = {
    'is_active': False,
    'yes_voters': {}, # {user_id: full_name}
    'no_voters': {},  # {user_id: full_name}
    'poll_message_id': None,
    'target_chat_id': TARGET_CHAT_ID 
}

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

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

# --- Job Functions (Scheduled Tasks) ---

async def start_poll(context: ContextTypes.DEFAULT_TYPE):
    """Starts the daily lunch poll at 6:00 PM (18:00 KAZ TZ)."""
    global poll_state
    
    # 1. Reset state for the new poll
    poll_state['is_active'] = True
    poll_state['yes_voters'] = {}
    poll_state['no_voters'] = {}
    poll_state['poll_message_id'] = None
    
    logger.info("Starting new lunch poll.")
    
    # 2. Send poll message
    try:
        message = await context.bot.send_message(
            chat_id=poll_state['target_chat_id'],
            text=f"{POLL_STARTED}{POLL_QUESTION}",
            reply_markup=create_poll_keyboard(),
            parse_mode='Markdown'
        )
        poll_state['poll_message_id'] = message.message_id
        
        # 3. Schedule the poll end for 10:00 AM the next day
        
        # Calculate the time for 10:00 AM tomorrow (next run time + 1 day)
        # Note: context.job.next_run_time is already in the scheduler's timezone (KAZ_TZ)
        next_day = context.job.next_run_time.astimezone(KAZ_TZ) + timedelta(days=1)
        end_time_local = next_day.replace(hour=END_HOUR, minute=0, second=0, microsecond=0)
        
        # Remove any existing 'end_poll' job to prevent duplicates
        existing_jobs = context.job_queue.get_jobs_by_name("end_poll")
        for job in existing_jobs:
            job.schedule_removal()
            
        context.job_queue.run_once(
            end_poll,
            when=end_time_local,
            chat_id=poll_state['target_chat_id'],
            name="end_poll",
        )
        logger.info(f"Poll end scheduled for {end_time_local.strftime('%Y-%m-%d %H:%M:%S %Z')}.")
        
    except Exception as e:
        logger.error(f"Error starting poll. Check if the bot can send proactive messages in the group: {e}")
        # Revert state if sending failed to avoid incorrect poll state
        poll_state['is_active'] = False 

async def end_poll(context: ContextTypes.DEFAULT_TYPE):
    """Ends the poll and sends the final results at 10:00 AM.
    Does NOT attempt to edit the poll message (no Admin rights required).
    """
    global poll_state
    
    if not poll_state['is_active']:
        logger.info("Attempted to end poll, but no poll was active.")
        return

    poll_state['is_active'] = False
    logger.info("Ending lunch poll.")
    
    final_results = format_results_message()
    
    # Send final notification and results (new message)
    await context.bot.send_message(
        chat_id=poll_state['target_chat_id'],
        text=f"{POLL_ENDED_ANNOUNCEMENT}{final_results}",
        parse_mode='Markdown'
    )

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message and explains the bot."""
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode='Markdown')

async def results_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the current voting results."""
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
    """Manually starts the poll (for testing or emergency use)."""
    # Restrict usage to the target chat ID for security
    if str(update.effective_chat.id) != str(poll_state['target_chat_id']):
         await update.message.reply_text(ONLY_IN_TARGET_CHAT)
         return
         
    # Cancel any pending end_poll job before manual start
    existing_jobs = context.job_queue.get_jobs_by_name("end_poll")
    for job in existing_jobs:
        job.schedule_removal()
        
    await start_poll(context)
    await update.message.reply_text("Дауыс беру қолмен (manual) басталды.")

# --- Callback Query Handler (Button Clicks) ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks (Yes/No votes)."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    if not poll_state['is_active']:
        # If poll is inactive, notify the user with a temporary alert message
        await query.answer(text=POLL_INACTIVE_ALERT, show_alert=True)
        return

    user_id = query.from_user.id
    user_name = get_voter_name(query)
    vote_type = query.data # 'vote_yes' or 'vote_no'
    
    # Check current vote state and update lists
    if vote_type == 'vote_yes':
        if user_id in poll_state['yes_voters']:
            # Already voted Yes, send confirmation but don't change state
            await query.answer(text=f"Сіздің дауысыңыз *{YES_OPTION}* болып тіркелген.", parse_mode='Markdown')
            return
        
        poll_state['yes_voters'][user_id] = user_name
        poll_state['no_voters'].pop(user_id, None) # Remove if they were 'No'
        
    elif vote_type == 'vote_no':
        if user_id in poll_state['no_voters']:
            # Already voted No, send confirmation but don't change state
            await query.answer(text=f"Сіздің дауысыңыз *{NO_OPTION}* болып тіркелген.", parse_mode='Markdown')
            return
            
        poll_state['no_voters'][user_id] = user_name
        poll_state['yes_voters'].pop(user_id, None) # Remove if they were 'Yes'

    # Send a small notification that the vote was registered (confirms the action)
    # The message includes a reminder about the /results command for transparency
    await query.answer(text=VOTE_REGISTERED_ALERT)


# --- Application Initialization ---

async def setup_jobs(application: Application):
    """Sets up the initial scheduled job when the application starts."""
    j = application.job_queue
    
    # Set the time for the first run (today at 6:00 PM)
    daily_start_time = time(hour=START_HOUR, minute=0, second=0, tzinfo=KAZ_TZ)

    # Schedule the start_poll function to run every day at 6:00 PM KAZ_TZ
    # It uses a daily schedule, and start_poll schedules the end_poll as a run_once job.
    j.run_daily(
        start_poll, 
        daily_start_time, 
        chat_id=poll_state['target_chat_id'], 
        name="start_poll_daily"
    )
    logger.info(f"Daily poll start scheduled for {START_HOUR}:00 KAZ_TZ.")

def main():
    """Starts the bot."""
    # Ensure configuration is complete before running
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("FATAL: BOT_TOKEN is missing. Please set the Render Secret or update the code.")
        return
    if TARGET_CHAT_ID == "YOUR_TARGET_CHAT_ID_HERE":
         logger.error("FATAL: TARGET_CHAT_ID is missing. Please update the configuration in lunch_bot.py.")
         return
    
    # Validate Chat ID format (must be a negative string starting with -100)
    if not TARGET_CHAT_ID.startswith("-100"):
        logger.warning(f"Warning: TARGET_CHAT_ID '{TARGET_CHAT_ID}' does not look like a typical Telegram Supergroup ID (-100...). Please verify.")


    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).post_init(setup_jobs).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("results", results_command))
    application.add_handler(CommandHandler("poll", manual_poll_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Run the bot until the user presses Ctrl-C (this handles the persistent polling loop on Render)
    logger.info("Bot started successfully. Polling for updates...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
