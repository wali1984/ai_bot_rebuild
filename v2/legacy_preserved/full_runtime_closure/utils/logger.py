import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

def get_logger(name):
    """
    Create a logger with consistent formatting for the WMA bot
    MEMORY LEAK FIX: Use RotatingFileHandler to prevent unbounded log buffer growth
    """
    logger = logging.getLogger(name)
    
    if not logger.handlers:  # Avoid duplicate handlers
        # Create logs directory if it doesn't exist
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        # Set level based on environment
        env = os.getenv('FLASK_ENV', 'production')
        if env == 'production':
            logger.setLevel(logging.WARNING)  # Only warnings and errors in production
        else:
            logger.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # MEMORY LEAK FIX: Use RotatingFileHandler instead of FileHandler
        # Limit each log file to 50MB, keep 3 backups (150MB total max)
        log_file = os.path.join(log_dir, f"{name}.log")
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=50*1024*1024,  # 50MB per file
            backupCount=3,           # Keep 3 old files
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger
