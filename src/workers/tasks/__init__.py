# Import all tasks to ensure they are registered with Dramatiq
# This file serves as the entry point for the worker process

# Email-related tasks
from .email_tasks import *