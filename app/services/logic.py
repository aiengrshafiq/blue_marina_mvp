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

def validate_bid(bid_rate: float, locked_rate: float) -> bool:
    """Checks if a bid is within the ±30% guardrail."""
    lower_bound = locked_rate * 0.70
    upper_bound = locked_rate * 1.30
    return lower_bound <= bid_rate <= upper_bound

def recommend_bids_for_po(line_items: list) -> None:
    """
    Analyzes all bids for each line item in a PO and marks the best one as 'RECOMMENDED'.
    The best bid is the lowest valid bid.
    """
    for item in line_items:
        best_bid = None
        for bid in item.bids:
            # Reset any previous recommendations
            bid.status = "PENDING"
            
            if validate_bid(bid.bid_rate, item.locked_rate):
                if best_bid is None or bid.bid_rate < best_bid.bid_rate:
                    best_bid = bid
        
        if best_bid:
            best_bid.status = "RECOMMENDED"

def calculate_smart_allocation(line_item, approved_bid) -> float:
    """Calculates the allocated quantity based on the approved bid's profitability."""
    requested_qty = line_item.requested_quantity
    locked_rate = line_item.locked_rate
    approved_rate = approved_bid.bid_rate

    # Rule 1: Much cheaper than locked rate -> full quantity
    if approved_rate <= (locked_rate * 0.7): # 30% or more cheaper
        return requested_qty
    
    # Rule 2: More expensive than locked rate -> limit quantity
    elif approved_rate > locked_rate:
        return requested_qty * 0.10 # Allocate only 10%
        
    # Rule 3: Mid-range -> normal fill
    else:
        return requested_qty