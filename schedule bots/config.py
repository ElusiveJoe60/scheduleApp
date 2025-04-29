from dotenv import load_dotenv
import os

load_dotenv()

TGTOKEN = os.getenv("TG_TOKEN")
VK_TOKEN = os.getenv("VK_TOKEN")

DATABASE = 'reservations.db'