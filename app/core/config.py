# app/core/config.py
import os
import logging
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY") # This will be None if not set
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))

# --- THIS IS THE CRITICAL FIX ---
# Add this sanity check. It will crash the app with a clear error if the key is missing.
if not SECRET_KEY or not isinstance(SECRET_KEY, str):
    raise RuntimeError("FATAL_ERROR: SECRET_KEY environment variable is not set!")
# --------------------------------

# For MVP, we will hardcode the selling rate.
SELLING_RATES = {
    "Fish": 100.0,
    "Meat": 120.0,
    "Produce": 50.0,
    "Dairy": 80.0,
}