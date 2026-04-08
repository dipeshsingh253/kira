"""
Example background tasks for the skeleton project.
Shows how to implement async tasks with Dramatiq.
"""

import time
import dramatiq
from loguru import logger

from src.workers.broker import get_broker

# Ensure broker is set up
get_broker()


@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=30000)
def send_welcome_email(user_id: str, name: str, email: str) -> None:
    """
    Send welcome email to newly registered user.
    
    This is an example background task that shows:
    - How to define a task with Dramatiq
    - Error handling and retry logic
    - Logging for monitoring
    """
    logger.info(f"Processing welcome email task for user {user_id} ({email})")
    
    try:
        # Simulate email sending process
        logger.info(f"Sending welcome email to {name} <{email}>...")
        
        # Simulate processing time (remove in real implementation)
        time.sleep(1)
        
        # In real implementation, integrate with email service:
        # - SendGrid, AWS SES, Mailgun, etc.
        # - Replace this simulation with actual email sending
        
        logger.info(f"Welcome email sent successfully to {email}")
        
    except Exception as e:
        logger.error(f"Failed to send welcome email to {email}: {e}")
        raise  # Re-raise to trigger Dramatiq's retry mechanism