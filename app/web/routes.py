# app/web/routes.py
import uuid
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from app.db.base import get_db
from app.db import models
from app.auth import get_current_user
from app.core.config import ARTICLES, WEEKLY_LOCKED_RATES
from app.services.azure_blob_service import file_uploader
from app.services import logic
from datetime import datetime
from datetime import date

router = APIRouter(tags=["Web"])
templates = Jinja2Templates(directory="app/web/templates")

# --- Auth Pages ---
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request})

@router.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse(url="/login")

# --- Shared Dashboard ---
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role == "store":
        purchase_orders = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.store_id == current_user.id).all()
        return templates.TemplateResponse("store/dashboard.html", {"request": request, "purchase_orders": purchase_orders, "user": current_user})
    
    if current_user.role == "purchaser":
        # Show line items that are pending bids
        line_items = db.query(models.OrderLineItem).options(joinedload(models.OrderLineItem.purchase_order), joinedload(models.OrderLineItem.article)).filter(models.PurchaseOrder.status == 'PENDING_BIDS').all()
        return templates.TemplateResponse("purchaser/dashboard.html", {"request": request, "line_items": line_items, "user": current_user})
    
    if current_user.role == "admin":
        # Show POs ready for logistics
        approved_pos = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.status == 'APPROVED').all()
        return templates.TemplateResponse("admin/dashboard.html", {"request": request, "purchase_orders": approved_pos, "user": current_user})

# --- Store Routes ---
@router.get("/create-po", response_class=HTMLResponse)
def create_po_page(request: Request, current_user: models.User = Depends(get_current_user)):
    if current_user.role != "store": return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("store/create_po.html", {"request": request, "articles": ARTICLES})



@router.post("/create-po")
async def handle_create_po(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != "store": 
        return RedirectResponse(url="/dashboard")
    
    form_data = await request.form()
    
    new_po = models.PurchaseOrder(
        po_number=f"PO-{uuid.uuid4().hex[:6].upper()}",
        store_id=current_user.id,
        status='PENDING_BIDS'
    )
    db.add(new_po)
    db.flush() # Flush to get the new_po.id

    # Get current week rates from the database
    current_week = date.today().isocalendar()[1]
    current_year = date.today().year
    weekly_rates_query = db.query(models.WeeklyRateLock).options(joinedload(models.WeeklyRateLock.article)).filter(
        models.WeeklyRateLock.week_number == current_week,
        models.WeeklyRateLock.year == current_year
    ).all()
    # Convert to a dictionary for easy lookup
    rates_dict = {rate.article.article_number: rate.selling_rate for rate in weekly_rates_query}

    items_added_count = 0
    i = 0
    while True:
        article_num = form_data.get(f"article_{i}")
        quantity_str = form_data.get(f"quantity_{i}")
        # rate_str = form_data.get(f"rate_{i}") # <-- REMOVED THIS LINE

        if not article_num:
            break

        # THE FIX: Removed the check for 'rate_str'
        if article_num and quantity_str:
            quantity = float(quantity_str)
            # rate = float(rate_str) # <-- REMOVED THIS LINE
            
            # THE FIX: Removed the check for 'rate > 0'
            if quantity > 0:
                article = db.query(models.Article).filter(models.Article.article_number == article_num).first()
                if article:
                    locked_rate = rates_dict.get(article.article_number, 0.0)
                    
                    # Add a check to ensure a rate was found
                    if locked_rate > 0:
                        line_item = models.OrderLineItem(
                            po_id=new_po.id,
                            article_id=article.id,
                            requested_quantity=quantity,
                            locked_rate=locked_rate # Use the rate from the database
                        )
                        db.add(line_item)
                        items_added_count += 1
        i += 1
    
    if items_added_count == 0:
        db.rollback() 
        return RedirectResponse(url="/create-po?error=empty", status_code=303)

    db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)



@router.get("/po/{po_id}", response_class=HTMLResponse)
def po_detail_page(request: Request, po_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != "store": return RedirectResponse(url="/dashboard")
    
    po = db.query(models.PurchaseOrder).options(
        joinedload(models.PurchaseOrder.line_items).joinedload(models.OrderLineItem.bids).joinedload(models.Bid.purchaser),
        joinedload(models.PurchaseOrder.line_items).joinedload(models.OrderLineItem.article)
    ).filter(models.PurchaseOrder.id == po_id).first()


    # Calculate margin for each bid to display in the UI
    for item in po.line_items:
        for bid in item.bids:
            if item.locked_rate > 0:
                margin = ((item.locked_rate - bid.bid_rate) / item.locked_rate) * 100
                bid.margin_percent = f"{margin:.1f}%" # Attach margin to the bid object
            else:
                bid.margin_percent = "N/A"
    
    # --- THIS IS THE FIX ---
    # Check if any bids on this PO have already been approved.
    has_approved_bids = any(
        bid.status == models.BidStatus.APPROVED.value 
        for item in po.line_items for bid in item.bids
    )

    # Only run the recommendation logic if the PO is still pending AND no bids have been approved yet.
    if po.status == models.POStatus.PENDING_BIDS.value and not has_approved_bids:
        logic.recommend_bids_for_po(po.line_items)
        db.commit()
        db.refresh(po) # Refresh to get the new 'RECOMMENDED' statuses

    return templates.TemplateResponse("store/po_detail.html", {"request": request, "po": po})

@router.post("/approve-bid/{bid_id}")
def approve_bid(bid_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != "store": 
        return RedirectResponse(url="/dashboard")

    # Eagerly load the related objects we know we'll need
    approved_bid = db.query(models.Bid).options(
        joinedload(models.Bid.line_item).joinedload(models.OrderLineItem.purchase_order)
    ).filter(models.Bid.id == bid_id).first()

    if not approved_bid:
        return RedirectResponse(url="/dashboard", status_code=303)

    line_item = approved_bid.line_item
    po = line_item.purchase_order

    # --- THIS IS THE FIX ---
    # Fetch all bids for the item and modify them in memory.
    # This is the idiomatic way and avoids session synchronization issues.
    all_bids_for_item = db.query(models.Bid).filter(models.Bid.line_item_id == line_item.id).all()
    for bid in all_bids_for_item:
        if bid.id == approved_bid.id:
            bid.status = models.BidStatus.APPROVED.value
        else:
            bid.status = models.BidStatus.REJECTED.value
    
    # Perform smart allocation
    line_item.allocated_quantity = logic.calculate_smart_allocation(line_item, approved_bid)
    
    # Commit the changes for this line item.
    db.commit()

    # --- Now, check if the entire PO is ready for approval in a fresh query ---
    total_items = db.query(models.OrderLineItem).filter(models.OrderLineItem.po_id == po.id).count()
    
    approved_items = db.query(models.OrderLineItem).join(models.Bid).filter(
        models.OrderLineItem.po_id == po.id,
        models.Bid.status == models.BidStatus.APPROVED.value
    ).distinct().count()

    if total_items == approved_items:
        po.status = models.POStatus.APPROVED.value
        db.commit()

    return RedirectResponse(url=f"/po/{po.id}", status_code=303)


# --- Purchaser Routes ---
@router.get("/bid/{line_item_id}", response_class=HTMLResponse)
def submit_bid_page(request: Request, line_item_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != "purchaser": return RedirectResponse(url="/dashboard")
    line_item = db.query(models.OrderLineItem).options(joinedload(models.OrderLineItem.article)).filter(models.OrderLineItem.id == line_item_id).first()
    return templates.TemplateResponse("purchaser/submit_bid.html", {"request": request, "line_item": line_item})

@router.post("/bid/{line_item_id}")
async def handle_submit_bid(
    line_item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    bid_rate: float = Form(...),
    proof_photo: UploadFile = File(...)
):
    if current_user.role != "purchaser": return RedirectResponse(url="/dashboard")
    
    # Upload photo proof
    file_content = await proof_photo.read()
    photo_url = file_uploader.upload_file(file_content, proof_photo.filename)
    
    # Create the bid
    new_bid = models.Bid(
        line_item_id=line_item_id,
        purchaser_id=current_user.id,
        bid_rate=bid_rate,
        proof_photo_url=photo_url
    )
    db.add(new_bid)
    db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/logout", response_class=RedirectResponse)
def logout():
    # This response will clear the cookie and redirect to the login page.
    response = RedirectResponse(url="/login")
    response.delete_cookie("access_token")
    return response


@router.get("/po/{po_id}/logistics", response_class=HTMLResponse)
def logistics_detail_page(request: Request, po_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != "admin": return RedirectResponse(url="/dashboard")
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == po_id).first()
    #return templates.TemplateResponse("admin/logistics_detail.html", {"request": request, "po": po})
    # --- THIS IS THE NEW LOGIC ---
    total_payout = 0
    total_invoice = 0
    
    # Calculate totals only if the order is delivered or completed
    if po.status in [models.POStatus.DELIVERED.value, models.POStatus.COMPLETED.value]:
        for item in po.line_items:
            # Find the approved bid for each item
            approved_bid = next((bid for bid in item.bids if bid.status == models.BidStatus.APPROVED.value), None)
            if approved_bid and item.allocated_quantity:
                total_payout += item.allocated_quantity * approved_bid.bid_rate
                total_invoice += item.allocated_quantity * item.locked_rate
    # -----------------------------

    return templates.TemplateResponse(
        "admin/logistics_detail.html", 
        {
            "request": request, 
            "po": po,
            "total_payout": total_payout,
            "total_invoice": total_invoice
        }
    )

@router.post("/po/{po_id}/assign-driver")
async def assign_driver(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    assigned_driver: str = Form(...),
    pickup_time: str = Form(...)
):
    if current_user.role != "admin": return RedirectResponse(url="/dashboard")
    
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == po_id).first()
    if po:
        po.assigned_driver = assigned_driver
        po.pickup_time = datetime.fromisoformat(pickup_time)
        po.status = models.POStatus.IN_LOGISTICS.value
        db.commit()
    
    return RedirectResponse(url=f"/po/{po_id}/logistics", status_code=303)

@router.post("/po/{po_id}/upload-proof")
async def upload_logistics_proof(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    proof_type: str = Form(...), # Will be 'pickup' or 'delivery'
    photo: UploadFile = File(...),
    pickup_temperature: float = Form(None)
):
    if current_user.role != "admin": return RedirectResponse(url="/dashboard")

    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == po_id).first()
    if po:
        file_content = await photo.read()
        photo_url = file_uploader.upload_file(file_content, photo.filename)
        
        if proof_type == 'pickup':
            po.pickup_photo_url = photo_url
            if pickup_temperature is not None:
                po.pickup_temperature = pickup_temperature
        elif proof_type == 'delivery':
            po.delivery_photo_url = photo_url
            po.status = models.POStatus.DELIVERED.value # Mark as delivered after final photo

        db.commit()

    return RedirectResponse(url=f"/po/{po_id}/logistics", status_code=303)


# --- ADD THIS NEW STORE CONFIRMATION ROUTE ---
@router.post("/po/{po_id}/confirm-receipt")
def handle_store_confirmation(
    po_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user),
    action: str = Form(...), # 'accept' or 'reject'
    notes: str = Form(None)
):
    # Security check: ensure user is a store and owns this PO
    if current_user.role != "store":
        return RedirectResponse(url="/dashboard")

    po = db.query(models.PurchaseOrder).filter(
        models.PurchaseOrder.id == po_id,
        models.PurchaseOrder.store_id == current_user.id
    ).first()

    # Only allow confirmation if the order has been delivered
    if po and po.status == models.POStatus.DELIVERED.value:
        if action == "accept":
            po.status = models.POStatus.COMPLETED.value
        elif action == "reject":
            # For now, we'll mark it COMPLETED but log the notes.
            # A future version could move it to a different "REJECTED" status.
            po.status = models.POStatus.COMPLETED.value
            po.grn_notes = f"REJECTED: {notes}"
        
        db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=303)


# --- ADD THIS NEW ADMIN REPORT ROUTE ---
@router.get("/summary-report", response_class=HTMLResponse)
def summary_report_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Security check: only admins can see this
    if current_user.role != "admin":
        return RedirectResponse(url="/dashboard")

    # Fetch all completed or delivered POs to include in the summary
    completed_pos = db.query(models.PurchaseOrder).filter(
        models.PurchaseOrder.status.in_([
            models.POStatus.COMPLETED.value,
            models.POStatus.DELIVERED.value
        ])
    ).all()

    total_revenue = 0
    total_cost = 0

    for po in completed_pos:
        for item in po.line_items:
            approved_bid = next((bid for bid in item.bids if bid.status == models.BidStatus.APPROVED.value), None)
            if approved_bid and item.allocated_quantity:
                total_revenue += item.allocated_quantity * item.locked_rate
                total_cost += item.allocated_quantity * approved_bid.bid_rate

    net_margin_amount = total_revenue - total_cost
    net_margin_percent = (net_margin_amount / total_revenue) * 100 if total_revenue > 0 else 0

    summary_data = {
        "total_pos": len(completed_pos),
        "total_revenue": total_revenue,
        "total_cost": total_cost,
        "net_margin_amount": net_margin_amount,
        "net_margin_percent": net_margin_percent,
    }

    return templates.TemplateResponse(
        "admin/summary_report.html",
        {"request": request, "summary": summary_data, "user": current_user}
    )


# --- START: NEW ADMIN RATE MANAGER ROUTE ---
@router.get("/rates-manager", response_class=HTMLResponse)
def rates_manager_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != "admin":
        return RedirectResponse(url="/dashboard")

    # Get current week and year
    current_week = date.today().isocalendar()[1]
    current_year = date.today().year()

    # Fetch rates for the current week
    rates = db.query(models.WeeklyRateLock).filter(
        models.WeeklyRateLock.week_number == current_week,
        models.WeeklyRateLock.year == current_year
    ).all()
    
    # Get all articles to populate the dropdown for adding new rates
    all_articles = db.query(models.Article).all()

    return templates.TemplateResponse(
        "admin/rates_manager.html",
        {
            "request": request,
            "rates": rates,
            "all_articles": all_articles,
            "current_week": current_week,
            "user": current_user
        }
    )

@router.post("/add-rate")
def handle_add_rate(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    article_id: int = Form(...),
    selling_rate: float = Form(...)
):
    if current_user.role != "admin":
        return RedirectResponse(url="/dashboard")

    current_week = date.today().isocalendar()[1]
    current_year = date.today().year()

    # Check if a rate for this article and week already exists to prevent duplicates
    existing_rate = db.query(models.WeeklyRateLock).filter(
        models.WeeklyRateLock.article_id == article_id,
        models.WeeklyRateLock.week_number == current_week,
        models.WeeklyRateLock.year == current_year
    ).first()

    if not existing_rate:
        new_rate = models.WeeklyRateLock(
            article_id=article_id,
            selling_rate=selling_rate,
            week_number=current_week,
            year=current_year
        )
        db.add(new_rate)
        db.commit()

    return RedirectResponse(url="/rates-manager", status_code=303)
# --- END: NEW ADMIN RATE MANAGER ROUTE ---