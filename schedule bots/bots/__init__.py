# bots/__init__.py
from .tgBot import main as run_telegram_bot
from .vkBot import VkBot

__all__ = ['run_telegram_bot', 'VkBot']