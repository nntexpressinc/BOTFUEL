import asyncio
import logging
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import requests
import json
import time

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
MOTIVE_API_KEY = "22dd2300-492d-4ce1-9f0d-772b1deefde9"  # Enter your API key
TELEGRAM_BOT_TOKEN = "7582469651:AAGr3GFNmboRj0yF65f2F3EOLkWVclFhmIQ"  # Enter your bot token
CHECK_INTERVAL = 60  # 60 seconds (check once per minute)
DEFAULT_FUEL_THRESHOLD = 30  # Default warning threshold (percentage)
NOTIFICATION_TIMEOUT = 2 * 60 * 60  # 2 hours (in seconds)

# Global variables
fuel_threshold = DEFAULT_FUEL_THRESHOLD
active_users = set()  # Set to store user IDs who have started the bot
notification_times = {}  # Dictionary to store last notification time per user and vehicle


def save_data(data, filename):
    """Save data to file"""
    try:
        with open(filename, 'w') as f:
            json.dump(data, f)
        logger.info(f"Data saved to {filename}")
        return True
    except Exception as e:
        logger.error(f"Error saving data to {filename}: {e}")
        return False


def load_data(filename, default=None):
    """Load data from file"""
    if default is None:
        default = {}
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return json.load(f)
        return default
    except Exception as e:
        logger.error(f"Error loading data from {filename}: {e}")
        return default


def save_active_users():
    """Save active users"""
    return save_data(list(active_users), 'active_users.json')


def load_active_users():
    """Load active users"""
    global active_users
    users = load_data('active_users.json', [])
    active_users = set(str(user) for user in users)  # Convert to string format
    logger.info(f"Loaded {len(active_users)} active users")


def save_notification_times():
    """Save notification times"""
    return save_data(notification_times, 'notification_times.json')


def load_notification_times():
    """Load notification times"""
    global notification_times
    notification_times = load_data('notification_times.json', {})
    logger.info(f"Loaded notification times for {len(notification_times)} users")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greeting and showing main information when the bot starts"""
    user_id = str(update.effective_chat.id)
    
    # Add user to active users list
    active_users.add(user_id)
    save_active_users()
    
    keyboard = [
        [InlineKeyboardButton("View all vehicles", callback_data="list_all")],
        [InlineKeyboardButton("Change warning threshold", callback_data="change_threshold")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Hello! I'm a bot that monitors fuel levels of vehicles.\n"
        f"Current warning threshold: {fuel_threshold}%\n\n"
        f"What would you like to do?",
        reply_markup=reply_markup
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "list_all":
        await list_all_vehicles(update, context)
    elif query.data == "change_threshold":
        await query.edit_message_text(
            "Enter a new warning threshold (e.g., '25' - warn when below 25%).\n"
            "Use the command: /threshold <number>."
        )
    elif query.data.startswith("page_"):
        page = int(query.data.split("_")[1])
        await list_all_vehicles(update, context, page)
    elif query.data == "start":
        keyboard = [
            [InlineKeyboardButton("View all vehicles", callback_data="list_all")],
            [InlineKeyboardButton("Change warning threshold", callback_data="change_threshold")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"Hello! I'm a bot that monitors fuel levels of vehicles.\n"
            f"Current warning threshold: {fuel_threshold}%\n\n"
            f"What would you like to do?",
            reply_markup=reply_markup
        )


def get_vehicles_data(page=1, per_page=10):
    """Get vehicle data from Motive API"""
    url = f"https://api.gomotive.com/v1/vehicle_locations?per_page={per_page}&page_no={page}"
    headers = {
        "accept": "application/json",
        "x-api-key": MOTIVE_API_KEY
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"API request error: {e}")
        return None


async def list_all_vehicles(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1) -> None:
    """Show list of all vehicles"""
    per_page = 5  # Number of vehicles to show per page
    vehicles_data = get_vehicles_data(page, per_page)
    
    if not vehicles_data or "vehicles" not in vehicles_data or not vehicles_data["vehicles"]:
        # If page is empty and it's not the first page, go back to previous page
        if page > 1:
            return await list_all_vehicles(update, context, page-1)
        
        message = "No vehicle information found."
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
        return
    
    text = f"🚚 Vehicle List (page {page}):\n\n"
    
    for item in vehicles_data["vehicles"]:
        vehicle = item["vehicle"]
        number = vehicle.get("number", "Unknown")
        make = vehicle.get("make", "Unknown")
        model = vehicle.get("model", "Unknown")
        
        fuel_percent = None
        if vehicle.get("current_location") and "fuel_primary_remaining_percentage" in vehicle["current_location"]:
            fuel_percent = vehicle["current_location"]["fuel_primary_remaining_percentage"]
        
        text += f"🔹 Vehicle: {number} - {make} {model}\n"
        
        if fuel_percent is not None:
            fuel_status = "⚠️ LOW!" if fuel_percent < fuel_threshold else "✅ Sufficient"
            text += f"   Fuel: {fuel_percent}% {fuel_status}\n\n"
        else:
            text += f"   Fuel: No data\n\n"
    
    # Add pagination buttons
    keyboard = []
    pagination_row = []
    
    if page > 1:
        pagination_row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"page_{page-1}"))
    
    # Only show "Next" button if there is data on the next page
    next_page_data = get_vehicles_data(page+1, per_page)
    if next_page_data and "vehicles" in next_page_data and next_page_data["vehicles"]:
        pagination_row.append(InlineKeyboardButton("➡️ Next", callback_data=f"page_{page+1}"))
    
    if pagination_row:
        keyboard.append(pagination_row)
    
    keyboard.append([InlineKeyboardButton("🔄 Main Menu", callback_data="start")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


async def change_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Change fuel warning threshold"""
    global fuel_threshold
    
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Please enter the correct format: /threshold <number>"
        )
        return
    
    new_threshold = int(context.args[0])
    if 1 <= new_threshold <= 100:
        fuel_threshold = new_threshold
        await update.message.reply_text(f"Fuel warning threshold changed to {fuel_threshold}%.")
    else:
        await update.message.reply_text("Please enter a value between 1 and 100.")


def can_send_notification(user_id, vehicle_id):
    """Check if we can send a notification for this vehicle to this user"""
    current_time = time.time()
    
    # Convert user_id and vehicle_id to string format
    user_id_str = str(user_id)
    vehicle_id_str = str(vehicle_id)
    
    # Initialize if needed
    if user_id_str not in notification_times:
        notification_times[user_id_str] = {}
    
    # Check if this vehicle has been notified for this user recently
    if vehicle_id_str in notification_times[user_id_str]:
        last_time = float(notification_times[user_id_str][vehicle_id_str])  # Convert to float if it's string
        time_diff = current_time - last_time
        
        # If less than timeout period has passed, don't send notification
        if time_diff < NOTIFICATION_TIMEOUT:
            return False
    
    # Update the last notification time
    notification_times[user_id_str][vehicle_id_str] = current_time
    save_notification_times()
    return True


async def check_fuel_levels(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check fuel levels of all vehicles and send warnings"""
    logger.info("Checking vehicle fuel levels...")
    
    # Get data for all vehicles
    page = 1
    all_vehicles = []
    
    while True:
        vehicles_data = get_vehicles_data(page, 100)  # 100 vehicles per page
        
        if not vehicles_data or "vehicles" not in vehicles_data or not vehicles_data["vehicles"]:
            break
        
        all_vehicles.extend(vehicles_data["vehicles"])
        
        # If there are fewer than 100 vehicles on this page, it's the last page
        if len(vehicles_data["vehicles"]) < 100:
            break
        
        page += 1
    
    if not all_vehicles:
        logger.error("Error getting vehicle data")
        return
    
    # For each active user
    for user_id in active_users:
        low_fuel_vehicles = []
        
        for item in all_vehicles:
            vehicle = item["vehicle"]
            vehicle_id = vehicle.get("id")
            
            number = vehicle.get("number", "Unknown")
            make = vehicle.get("make", "Unknown")
            model = vehicle.get("model", "Unknown")
            fuel_percent = None
            
            if vehicle.get("current_location") and "fuel_primary_remaining_percentage" in vehicle["current_location"]:
                fuel_percent = vehicle["current_location"]["fuel_primary_remaining_percentage"]
            
            # If fuel level is low and we can send notification (based on timeout)
            if fuel_percent is not None and fuel_percent < fuel_threshold and can_send_notification(user_id, vehicle_id):
                low_fuel_vehicles.append({
                    "number": number,
                    "make": make,
                    "model": model,
                    "fuel_percent": fuel_percent
                })
        
        # Send individual notifications for each vehicle that needs warning
        for vehicle in low_fuel_vehicles:
            try:
                message = "⚠️ LOW FUEL WARNING ⚠️\n\n"
                message += f"🚚 Vehicle: {vehicle['number']} - {vehicle['make']} {vehicle['model']}\n"
                message += f"⛽ Fuel: {vehicle['fuel_percent']}%\n"
                
                await context.bot.send_message(chat_id=int(user_id), text=message)
                logger.info(f"Warning sent to user {user_id} for vehicle {vehicle['number']}")
            except Exception as e:
                logger.error(f"Failed to send message to user {user_id}: {e}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help"""
    help_text = (
        "🔹 Available commands:\n\n"
        "/start - Restart the bot\n"
        "/list - View list of all vehicles\n"
        "/threshold <number> - Change fuel warning threshold\n"
        "/help - Show help\n\n"
        f"Current warning threshold: {fuel_threshold}%"
    )
    await update.message.reply_text(help_text)


def main() -> None:
    """Start the bot"""
    # Load active users and notification times from file
    load_active_users()
    load_notification_times()
    
    # Create bot
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_all_vehicles))
    application.add_handler(CommandHandler("threshold", change_threshold))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add periodic fuel check
    job_queue = application.job_queue
    job_queue.run_repeating(check_fuel_levels, interval=CHECK_INTERVAL, first=10)
    
    # Start the bot
    logger.info("Bot started")
    application.run_polling()


if __name__ == "__main__":
    main()
