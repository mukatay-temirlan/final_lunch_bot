import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue, CallbackContext 
from datetime import time, timedelta, timezone, datetime 
import json 

# --- Configuration (MUST BE SET) ---
# 1. BOT TOKEN: Loaded from Render Environment Variable (Secret).
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8558478796:AAECHjNWWAQqefRjKX_W4h7lJzJschpfWU") 
# 2. TARGET CHAT ID: REPLACE WITH YOUR GROUP/CHAT ID (e.g., -1001234567890)
# NOTE: Target Chat ID must be an integer (e.g., -1001234567890).
TARGET_CHAT_ID_RAW = os.environ.get("TARGET_CHAT_ID", "-1003197836887")

# --- Time Constants (GMT+5/UTC+5 Time Zone) ---
KAZAKHSTAN_TZ = timezone(timedelta(hours=5)) # UTC+5 Time Zone

# Scheduled times: Monday to Friday
POLL_START_TIME = time(8, 0, 0, tzinfo=KAZAKHSTAN_TZ)   # Poll starts at 08:00 AM UTC+5
POLL_END_TIME = time(10, 30, 0, tzinfo=KAZAKHSTAN_TZ) # Poll closes at 10:30 AM UTC+5

# --- RENDER ENVIRONMENT VARS ---
PORT = int(os.environ.get("PORT", 8080))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "YOUR_RENDER_URL_HERE") # e.g., https://my-bot-service.onrender.com

# --- Bot Strings (Kazakh Language) ---
POLL_QUESTION = "Сіз түскі ас ішесіз бе?"
# --- UPDATED BUTTON LABELS WITH EMOJIS FOR COLOR ---
YES_OPTION = "🟢 Иә"
NO_OPTION = "🔴 Жоқ"
WELCOME_MESSAGE = (
    "🤖 *Түскі Ас Ботқа Қош Келдіңіз!* 🤖\n\n"
    "Бұл бот Webhook режимінде жұмыс істейді.\n\n"
    f"**Автоматты дауыс беру: Дүйсенбі-Жұма, {POLL_START_TIME.strftime('%H:%M')} - {POLL_END_TIME.strftime('%H:%M')} (UTC+5 уақыты).**\n"
    "Дауыс беру *автоматты түрде* басталып, нәтижелерді жариялаумен аяқталады.\n\n"
    "Ағымдағы нәтижелерді көру үшін `/results` пәрменін пайдаланыңыз.\n"
    "Өткен күндердегі нәтижелерді көру үшін: `/history YYYY-MM-DD`.\n"
    "Әкімшілер `/poll` пәрменін *автоматты дауыс беру басталмаған* күндері ғана қолмен бастай алады.\n"
    "Топ иесі нәтижелерді өшіру үшін `/deletehistory YYYY-MM-DD` пәрменін қолдана алады."
)
POLL_STARTED = "📢 *Дауыс беру басталды!* 📢\n\n"
POLL_ENDED_ANNOUNCEMENT = "🛑 *Дауыс беру аяқталды!* 🛑\n\n"
POLL_INACTIVE_ALERT = "Бұл дауыс беру аяқталды немесе белсенді емес."
POLL_ENDED_BY_TIME = f"Дауыс беру уақыты аяқталды ({POLL_END_TIME.strftime('%H:%M')})."
VOTE_REGISTERED_ALERT = "Сіздің дауысыңыз тіркелді. Рахмет!" 
VOTE_CHANGED_ALERT = "Сіздің дауысыңыз өзгертілді. Рахмет!" 
RESULTS_HEADER = "📋 *Түскі Ас Дауыс Беру Нәтижелері* 📋\n\n"
NOT_ACTIVE_MESSAGE = f"Дауыс беру қазір белсенді емес. Келесі дауыс беруді сағат {POLL_START_TIME.strftime('%H:%M')}-де күтіңіз." 
ONLY_IN_TARGET_CHAT = "Бұл пәрменді тек тағайындалған топта ғана қолдануға болады."
MANUAL_POLL_STARTED = "✅ *Дауыс беру қолмен іске қосылды. Бұрынғы нәтижелер жойылды.*"
NOT_ADMIN_MESSAGE = "❌ Бұл әрекетті орындауға сіздің әкімші құқығыңыз жоқ."
NOT_CREATOR_MESSAGE = "❌ Бұл әрекетті орындауға сіздің топ иесі құқығыңыз жоқ."
RESULTS_BUTTON = "🔵 Нәтижелерді көру"
VOTER_ONLY_ALERT = "❌ Нәтижелерді көру үшін алдымен дауыс беріңіз."
RESULTS_IN_ALERT_HEADER = "📋 Түскі Ас Дауыс Беру Нәтижелері (Ағымдағы)"
MANUAL_POLL_LOCKED_MESSAGE = f"❌ *Қолмен дауыс беруді бастау мүмкін емес.*\n\nБүгінгі түскі асқа арналған дауыс беру *автоматты түрде басталды* немесе *қолмен басталды*."
HISTORY_NOT_FOUND = "❌ Бұл күнге арналған дауыс беру нәтижелері табылған жоқ. Күнді `YYYY-MM-DD` форматында тексеріңіз."
HISTORY_DELETED_SUCCESS = "🗑️ *Нәтижелер* ({}) *сәтті өшірілді.*"


# Global variable to hold the integer chat ID, initialized in main()
TARGET_CHAT_ID = None 

# --- State Management (In-Memory/Global - NOTE: This will reset on Free Tier spin-down) ---
# poll_state: Current active poll data
poll_state = {
    'is_active': False,
    'yes_voters': {}, 
    'no_voters': {},  
    'poll_message_id': None,
    'target_chat_id': None, 
    'lunch_date': None,       
    'is_manual': False, # New flag: True if started by /poll, False if by scheduled job
}
STATE_FILE = "poll_state.json" 
PAST_POLLS_FILE = "past_polls.json"

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- State Persistence (File I/O) ---
def load_state():
    """Loads current poll state from a file."""
    global poll_state
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
            yes_voters_converted = {int(k): v for k, v in data.get('yes_voters', {}).items()}
            no_voters_converted = {int(k): v for k, v in data.get('no_voters', {}).items()}
            
            poll_state.update(data)
            poll_state['yes_voters'] = yes_voters_converted
            poll_state['no_voters'] = no_voters_converted
            if 'target_chat_id' in data:
                poll_state['target_chat_id'] = int(data['target_chat_id'])
            # Ensure new flag exists
            if 'is_manual' not in poll_state:
                poll_state['is_manual'] = False
    except (FileNotFoundError, json.JSONDecodeError):
        logger.info("No saved state found or file corrupted. Starting clean.")
        pass

def save_state():
    """Saves current poll state to a file."""
    try:
        state_to_save = poll_state.copy()
        state_to_save['yes_voters'] = {str(k): v for k, v in poll_state['yes_voters'].items()}
        state_to_save['no_voters'] = {str(k): v for k, v in poll_state['no_voters'].items()}
        if state_to_save.get('target_chat_id') is not None:
            state_to_save['target_chat_id'] = str(poll_state['target_chat_id']) 
            
        with open(STATE_FILE, 'w') as f:
            json.dump(state_to_save, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving state: {e}")
        
def load_past_polls():
    """Loads all past poll data for history feature."""
    try:
        with open(PAST_POLLS_FILE, 'r') as f:
            data = json.load(f)
            archived_polls = {}
            for date, poll in data.items():
                # Convert voter IDs back to integers
                poll['yes_voters'] = {int(k): v for k, v in poll.get('yes_voters', {}).items()}
                poll['no_voters'] = {int(k): v for k, v in poll.get('no_voters', {}).items()}
                archived_polls[date] = poll
            return archived_polls
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_past_polls(data):
    """Saves all past poll data for history feature."""
    try:
        state_to_save = {}
        for date, poll in data.items():
            state_to_save[date] = {
                # Convert integer keys back to strings for JSON
                'yes_voters': {str(k): v for k, v in poll.get('yes_voters', {}).items()},
                'no_voters': {str(k): v for k, v in poll.get('no_voters', {}).items()},
                'end_time': poll.get('end_time'),
                'status': poll.get('status')
            }
            
        with open(PAST_POLLS_FILE, 'w') as f:
            json.dump(state_to_save, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving past poll data: {e}")


# --- Utility Functions ---

def get_voter_name(user: User) -> str:
    """Returns the voter's full name from a Telegram User object."""
    if user.last_name:
        return f"{user.first_name} {user.last_name}"
    return user.first_name

def create_poll_keyboard():
    """Generates the inline keyboard for the poll, including the Results button."""
    keyboard = [
        [
            InlineKeyboardButton(YES_OPTION, callback_data='vote_yes'),
            InlineKeyboardButton(NO_OPTION, callback_data='vote_no'),
        ],
        [
            InlineKeyboardButton(RESULTS_BUTTON, callback_data='show_results'),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def format_results_message(state_to_format=None):
    """Generates the formatted results string based on the provided state or current poll_state."""
    state = state_to_format if state_to_format is not None else poll_state
    
    clean_yes_option = "Иә"
    clean_no_option = "Жоқ"
    
    yes_list = "\n- " + "\n- ".join(state['yes_voters'].values()) if state['yes_voters'] else "Ешкім дауыс бермеді"
    no_list = "\n- " + "\n- ".join(state['no_voters'].values()) if state['no_voters'] else "Ешкім дауыс бермеді"
    
    total_votes = len(state['yes_voters']) + len(state['no_voters'])
    
    # Include the date/source
    date_info = f"📅 Күні: *{state['lunch_date']}* (Бастауы: {'Қолмен' if state.get('is_manual') else 'Автоматты'})" if state.get('lunch_date') else "📅 Күні: *Белгісіз*"
    
    message = (
        f"{date_info}\n\n"
        f"Сұрақ: _{POLL_QUESTION}_\n\n"
        f"✅ *{clean_yes_option}* ({len(state['yes_voters'])}):\n"
        f"{yes_list}\n\n"
        f"❌ *{clean_no_option}* ({len(state['no_voters'])}):\n"
        f"{no_list}\n\n"
        f"Барлығы дауыс берді: *{total_votes}*"
    )
    return message

def check_and_expire_poll() -> bool:
    """
    Checks if the poll is currently expired. Archives results if expired.
    Returns True if the poll was active and is now expired, False otherwise.
    """
    if not poll_state['is_active'] or not poll_state['lunch_date']:
        return False

    try:
        now_kz = datetime.now(KAZAKHSTAN_TZ)
        poll_date_dt = datetime.strptime(poll_state['lunch_date'], '%Y-%m-%d').date()

        # Check if today is the lunch day and time is past POLL_END_TIME (excluding tzinfo for comparison), 
        # OR if today is past the lunch day
        is_past_end_time = (now_kz.date() == poll_date_dt and now_kz.time() > POLL_END_TIME.replace(tzinfo=None)) or (now_kz.date() > poll_date_dt)

        if is_past_end_time:
            poll_state['is_active'] = False
            
            # --- ARCHIVE RESULTS ---
            archivable_data = {
                'yes_voters': poll_state['yes_voters'],
                'no_voters': poll_state['no_voters'],
                'end_time': now_kz.isoformat(),
                'status': 'Completed_AutoExpired' if not poll_state.get('is_manual') else 'Completed_ManualExpired',
                'is_manual': poll_state.get('is_manual', False) # Save the source type
            }
            past_polls = load_past_polls()
            past_polls[poll_state['lunch_date']] = archivable_data
            save_past_polls(past_polls)
            # -----------------------

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
    """
    Starts the poll automatically (only Mon-Fri).
    """
    global poll_state
    
    load_state() 

    if poll_state['target_chat_id'] is None:
        logger.error("start_poll_job failed: TARGET_CHAT_ID is not set in poll_state.")
        return

    # 1. Get today's date and weekday in UTC+5 time
    now_kz = datetime.now(KAZAKHSTAN_TZ)
    # Weekday: 0=Monday, 6=Sunday
    current_weekday = now_kz.weekday() 
    lunch_date_str = now_kz.strftime('%Y-%m-%d')
    
    # 2. Check for Mon-Fri schedule
    # Days (0, 1, 2, 3, 4) correspond to Mon, Tue, Wed, Thu, Fri
    if current_weekday >= 5: # Saturday or Sunday
        logger.info(f"Scheduled job skipped: Not a weekday ({lunch_date_str}).")
        return
        
    # 3. Check if active for today (Only restart if state reset failed or bot rebooted)
    if poll_state['is_active'] and poll_state['lunch_date'] == lunch_date_str:
        logger.info("Scheduled job skipped: Poll already active for today.")
        return
        
    # 4. Reset state and set new parameters
    poll_state['is_active'] = True
    poll_state['yes_voters'] = {}
    poll_state['no_voters'] = {}
    poll_state['poll_message_id'] = None
    poll_state['lunch_date'] = lunch_date_str # Set today's date
    poll_state['is_manual'] = False # Automatically started
    
    # 5. Construct and send poll message
    date_text = f"📅 Күні: *{lunch_date_str}*."
    full_poll_text = (
        f"{POLL_STARTED}"
        f"{date_text}\n\n"
        f"{POLL_QUESTION}"
    )

    try:
        message = await context.bot.send_message(
            chat_id=poll_state['target_chat_id'],
            text=full_poll_text,
            reply_markup=create_poll_keyboard(), 
            parse_mode='Markdown'
        )
        poll_state['poll_message_id'] = message.message_id
        save_state()
        logger.info(f"New automated poll started for {lunch_date_str}.")

    except Exception as e:
        logger.error(f"Error starting automated poll: {e}. Ensuring state is inactive.")
        poll_state['is_active'] = False
        save_state()


async def end_poll_job(context: CallbackContext):
    """Ends the poll automatically at the set end time and shows results."""
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
        
        # --- ARCHIVE RESULTS ---
        archivable_data = {
            'yes_voters': poll_state['yes_voters'],
            'no_voters': poll_state['no_voters'],
            'end_time': now_kz.isoformat(),
            'status': 'Completed_Scheduled' if not poll_state.get('is_manual') else 'Completed_Manual',
            'is_manual': poll_state.get('is_manual', False)
        }
        past_polls = load_past_polls()
        past_polls[today_date_str] = archivable_data 
        save_past_polls(past_polls)
        # -----------------------

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

async def is_admin_or_creator(context: ContextTypes.DEFAULT_TYPE, chat_id, user_id):
    """Checks if a user is an admin or creator of the chat."""
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

async def is_creator(context: ContextTypes.DEFAULT_TYPE, chat_id, user_id):
    """Checks if a user is the creator of the chat."""
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status == 'creator'
    except Exception as e:
        logger.error(f"Error checking creator status: {e}")
        return False

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message and explains the bot."""
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode='Markdown')

async def results_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends the current voting results. Available to all users.
    """
    load_state() 
    
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
    await update.message.reply_text(f"{RESULTS_HEADER}{results}", parse_mode='Markdown')


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Retrieves and sends the voting results for a specific past date.
    Usage: /history YYYY-MM-DD (or defaults to yesterday if no date is given)
    """
    if not context.args:
        # Default to previous day if no date is specified
        yesterday_kz = datetime.now(KAZAKHSTAN_TZ) - timedelta(days=1)
        target_date_str = yesterday_kz.strftime('%Y-%m-%d')
        
    else:
        target_date_str = context.args[0]
        
    past_polls = load_past_polls()
    
    if target_date_str in past_polls:
        archived_poll = past_polls[target_date_str]
        temp_state = {
            'yes_voters': archived_poll['yes_voters'],
            'no_voters': archived_poll['no_voters'],
            'lunch_date': target_date_str,
            'is_manual': archived_poll.get('is_manual', False)
        }
        
        results = format_results_message(temp_state) 
        
        await update.message.reply_text(
            f"🕰️ *Өткен Дауыс Беру Нәтижелері* ({target_date_str})\n\n{RESULTS_HEADER}{results}", 
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(HISTORY_NOT_FOUND)

async def delete_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Allows the group creator to delete a specific day's history.
    Usage: /deletehistory YYYY-MM-DD
    """
    target_chat_id = poll_state.get('target_chat_id')
    if update.effective_chat.id != target_chat_id:
        await update.message.reply_text(ONLY_IN_TARGET_CHAT)
        return

    # Check 1: Must be the group creator
    if not await is_creator(context, target_chat_id, update.effective_user.id):
        await update.message.reply_text(NOT_CREATOR_MESSAGE)
        return
        
    if not context.args:
        await update.message.reply_text("❌ Өшіру үшін күнді `YYYY-MM-DD` форматында көрсетіңіз. Мысалы: `/deletehistory 2025-11-30`")
        return
        
    date_to_delete = context.args[0]
    past_polls = load_past_polls()
    
    if date_to_delete in past_polls:
        past_polls.pop(date_to_delete)
        save_past_polls(past_polls)
        await update.message.reply_text(HISTORY_DELETED_SUCCESS.format(date_to_delete), parse_mode='Markdown')
    else:
        await update.message.reply_text(HISTORY_NOT_FOUND)


async def manual_poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Allows group administrators to manually start/restart the poll.
    Only allowed if the automated poll has NOT started for today.
    And only one manual poll per day is allowed.
    """
    load_state()

    # Check 1: Must be in the target group
    target_chat_id = poll_state.get('target_chat_id')
    if update.effective_chat.id != target_chat_id:
        await update.message.reply_text(ONLY_IN_TARGET_CHAT)
        return

    user = update.effective_user
    
    # Check 2: Must be an administrator or creator of the chat
    if not await is_admin_or_creator(context, target_chat_id, user.id):
        await update.message.reply_text(NOT_ADMIN_MESSAGE)
        return
        
    # Check 3: Check if a poll (auto or manual) has already started today
    now_kz = datetime.now(KAZAKHSTAN_TZ)
    lunch_date_str = now_kz.strftime('%Y-%m-%d')
    
    is_active_for_today = poll_state['is_active'] and poll_state['lunch_date'] == lunch_date_str
    
    # Check if today's poll was already started by the scheduled job (is_manual is False)
    was_auto_started = is_active_for_today and not poll_state.get('is_manual', True) # Defaulting to True for safety check
    
    # Check if a poll was already manually started today (is_manual is True, regardless of active status)
    # We check past polls for this day to see if a manual poll was archived
    past_polls = load_past_polls()
    was_manual_archived_today = past_polls.get(lunch_date_str, {}).get('is_manual', False)

    if was_auto_started or poll_state.get('is_manual', False) or was_manual_archived_today:
        await update.message.reply_text(MANUAL_POLL_LOCKED_MESSAGE, parse_mode='Markdown')
        return

    # --- Manual Poll Start ---
    
    # Reset state and set new parameters
    poll_state['is_active'] = True
    poll_state['yes_voters'] = {}
    poll_state['no_voters'] = {}
    poll_state['poll_message_id'] = None
    poll_state['lunch_date'] = lunch_date_str 
    poll_state['is_manual'] = True # Set manual flag

    # Construct and send poll message
    date_text = f"📅 Күні: *{lunch_date_str}*."
    full_poll_text = (
        f"{POLL_STARTED}"
        f"{date_text}\n\n"
        f"{POLL_QUESTION}"
    )
    
    try:
        message = await context.bot.send_message(
            chat_id=poll_state['target_chat_id'],
            text=full_poll_text,
            reply_markup=create_poll_keyboard(), 
            parse_mode='Markdown'
        )
        poll_state['poll_message_id'] = message.message_id
        save_state()
        
        await update.message.reply_text(MANUAL_POLL_STARTED, parse_mode='Markdown')
        logger.info(f"New manual poll started for {lunch_date_str}.")

    except Exception as e:
        logger.error(f"Error starting manual poll: {e}. Ensuring state is inactive.")
        poll_state['is_active'] = False
        save_state()
        await update.message.reply_text("❌ Қолмен дауыс беруді бастау кезінде қате пайда болды.")
        
# --- Callback Query Handler (Button Clicks) ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks (Yes/No votes and Results button)."""
    query = update.callback_query
    
    load_state() 
    user = query.from_user
    user_id = user.id

    # --- Results Button Logic (show_results) ---
    if query.data == 'show_results':
        
        # Check 1: Voter-Only Access (The user must have voted to see the current results)
        has_voted = user_id in poll_state['yes_voters'] or user_id in poll_state['no_voters']
        
        if not has_voted:
            await query.answer(text=VOTER_ONLY_ALERT, show_alert=True)
            return
            
        results_text = format_results_message()
        
        # Format for Alert Box (plain text)
        plain_results_text = results_text.replace('*', '').replace('_', '').replace('📅 Күні:', 'Күні:')
        
        alert_content = f"{RESULTS_IN_ALERT_HEADER}\n\n{plain_results_text}"
        
        # Max length of an alert text is 200 characters. If the list is long, we truncate it.
        if len(alert_content) > 200:
             # Find the last newline before 190 chars and truncate there
            truncate_point = plain_results_text[:190].rfind('\n')
            if truncate_point > 0:
                alert_content = f"{RESULTS_IN_ALERT_HEADER}\n\n{plain_results_text[:truncate_point]}..."
            else:
                 alert_content = f"{RESULTS_IN_ALERT_HEADER}\n\n{plain_results_text[:190]}..."

        await query.answer(text=alert_content, show_alert=True)
        return

    # --- Voting Logic (vote_yes/vote_no) ---
    
    # Check 2: Automatic Expiry Check
    is_expired = check_and_expire_poll()
    if is_expired:
        await query.answer(text=POLL_ENDED_BY_TIME, show_alert=True)
        return

    # Check 3: Poll must be active
    if not poll_state['is_active']:
        await query.answer(text=POLL_INACTIVE_ALERT, show_alert=True)
        return

    user_name = get_voter_name(user) 
    vote_type = query.data 
    vote_changed = False 
    
    # --- IMPLEMENTATION OF "LAST VOTE COUNTS" ---
    if vote_type == 'vote_yes':
        if user_id in poll_state['no_voters']:
            poll_state['no_voters'].pop(user_id) 
            vote_changed = True
        
        if user_id in poll_state['yes_voters']:
            await query.answer(text=f"Сіздің дауысыңыз *Иә* болып тіркелген.", show_alert=False) 
            return 
            
        poll_state['yes_voters'][user_id] = user_name
        
    elif vote_type == 'vote_no':
        if user_id in poll_state['yes_voters']:
            poll_state['yes_voters'].pop(user_id) 
            vote_changed = True
        
        if user_id in poll_state['no_voters']:
            await query.answer(text=f"Сіздің дауысыңыз *Жоқ* болып тіркелген.", show_alert=False)
            return 
            
        poll_state['no_voters'][user_id] = user_name

    save_state()
    load_state() 
    
    confirmation_message = VOTE_CHANGED_ALERT if vote_changed else VOTE_REGISTERED_ALERT
    await query.answer(text=confirmation_message, show_alert=False)


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
        TARGET_CHAT_ID = int(TARGET_CHAT_ID_RAW)
        poll_state['target_chat_id'] = TARGET_CHAT_ID 
    except ValueError:
        logger.error(f"FATAL: TARGET_CHAT_ID environment variable '{TARGET_CHAT_ID_RAW}' is not a valid integer.")
        return
        
    load_state()

    # 2. Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    # 3. Schedule and Start JobQueue 
    if job_queue:
        # Schedule only for Mon (0) to Fri (4)
        WEEKDAY_SCHEDULE = (0, 1, 2, 3, 4) 
        
        job_queue.run_daily(
            start_poll_job, 
            POLL_START_TIME, 
            days=WEEKDAY_SCHEDULE, # Mon-Fri
            name='daily_poll_start'
        )
        
        job_queue.run_daily(
            end_poll_job, 
            POLL_END_TIME, 
            days=(0, 1, 2, 3, 4, 5, 6), # Every day check (to catch polls started manually on weekends)
            name='daily_poll_end'
        )
        
        logger.info(f"Jobs scheduled for start (Mon-Fri) at {POLL_START_TIME.strftime('%H:%M')} and end (Daily) at {POLL_END_TIME.strftime('%H:%M')} UTC+5.")

        job_queue.start()
        logger.info("JobQueue scheduler started successfully.")
    else:
        logger.error("FATAL ERROR: JobQueue could not be initialized. Please ensure 'python-telegram-bot[job-queue]' is installed.")

    # 4. Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("results", results_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("deletehistory", delete_history_command)) # New command
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
