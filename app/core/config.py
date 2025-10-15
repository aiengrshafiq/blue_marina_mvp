# app/core/config.py
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))

# For MVP, we will hardcode the selling rate. In a real app, this would be in a DB.
SELLING_RATES = {
    "Fish": 100.0,
    "Meat": 120.0,
    "Produce": 50.0,
    "Dairy": 80.0,
}