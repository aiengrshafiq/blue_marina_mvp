# app/core/config.py
import os
import logging
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY") # This will be None if not set
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_STORAGE_CONTAINER_NAME = "bluemarina-proofs"

# --- THIS IS THE CRITICAL FIX ---
# Add this sanity check. It will crash the app with a clear error if the key is missing.
if not SECRET_KEY or not isinstance(SECRET_KEY, str):
    raise RuntimeError("FATAL_ERROR: SECRET_KEY environment variable is not set!")
if not AZURE_STORAGE_CONNECTION_STRING:
    raise RuntimeError("FATAL_ERROR: AZURE_STORAGE_CONNECTION_STRING environment variable is not set!")

# --------------------------------

# For MVP, we will hardcode the selling rate.
SELLING_RATES = {
    "Fish": 100.0,
    "Meat": 120.0,
    "Produce": 50.0,
    "Dairy": 80.0,
}

# Article Master List
ARTICLES = [
    {"article_number": "FISH-001", "name": "Short Fish", "unit": "kg"},
    {"article_number": "FISH-002", "name": "Sultan Fish", "unit": "kg"},
    {"article_number": "MEAT-001", "name": "Beef Mince", "unit": "kg"},
    {"article_number": "MEAT-002", "name": "Mutton Chops", "unit": "kg"},
    {"article_number": "PROD-001", "name": "Tomatoes", "unit": "kg"},
    {"article_number": "DAIRY-001", "name": "Fresh Milk", "unit": "litre"},
]

# For MVP, we will manage the weekly locked rates here.
# In a real app, this would be in the WeeklyRateLock table.
WEEKLY_LOCKED_RATES = {
    "FISH-001": 100.0,
    "FISH-002": 150.0,
    "MEAT-001": 200.0,
    "MEAT-002": 250.0,
    "PROD-001": 10.0,
    "DAIRY-001": 5.0,
}