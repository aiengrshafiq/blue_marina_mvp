# app/services/logic.py
from app.core.config import SELLING_RATES

def calculate_purchase_details(category: str, quantity: int, buy_rate: float):
    selling_rate = SELLING_RATES.get(category)
    if not selling_rate or selling_rate == 0:
        raise ValueError("Selling rate not defined for this category")

    margin = ((selling_rate - buy_rate) / selling_rate) * 100
    
    adjusted_quantity = quantity
    if margin >= 30:
        adjusted_quantity = int(quantity * 1.05) # Fill +5%
    elif margin < 10:
        adjusted_quantity = int(quantity * 0.50) # Fill 50%
    
    return adjusted_quantity, margin