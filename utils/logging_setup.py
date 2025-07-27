"""
Logging setup and configuration
Handles log file management and shutdown logging
"""

import logging
import os
import atexit
import signal
from datetime import datetime
from zoneinfo import ZoneInfo

def setup_logging():
    """Setup logging that clears the log file each session"""
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove any existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # File handler that overwrites the log file each session (mode='w')
    file_handler = logging.FileHandler(
        'bot.log',  # In the same directory as the script
        mode='w',   # This clears the file each time
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)  # Keep scheduler logs
    
    # Log startup message with session info
    melbourne_time = datetime.now(ZoneInfo("Australia/Melbourne"))
    logging.info("=" * 60)
    logging.info("🤖 PLEX BOT SESSION START")
    logging.info("🕐 Session started: %s", melbourne_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
    logging.info("📁 Log file: %s", os.path.abspath('bot.log'))
    logging.info("📝 This log file is cleared each session")
    logging.info("=" * 60)
    
    # Setup shutdown logging
    _setup_shutdown_handlers()

def _setup_shutdown_handlers():
    """Setup handlers for clean shutdown logging"""
    
    def log_shutdown():
        melbourne_time = datetime.now(ZoneInfo("Australia/Melbourne"))
        logging.info("=" * 60)
        logging.info("🛑 PLEX BOT SESSION END")
        logging.info("🕐 Session ended: %s", melbourne_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
        logging.info("📊 Session duration logged above")
        logging.info("=" * 60)

    # Register shutdown handlers
    atexit.register(log_shutdown)
    signal.signal(signal.SIGTERM, lambda signum, frame: log_shutdown())
    signal.signal(signal.SIGINT, lambda signum, frame: log_shutdown())
