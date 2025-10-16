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

    # --- THIS IS THE FIX ---
    # Use a simple counter instead of checking the relationship list.
    items_added_count = 0
    i = 0
    while True:
        article_num = form_data.get(f"article_{i}")
        quantity_str = form_data.get(f"quantity_{i}")
        rate_str = form_data.get(f"rate_{i}")

        if not article_num:
            break

        if article_num and quantity_str and rate_str:
            quantity = float(quantity_str)
            rate = float(rate_str)
            
            if quantity > 0 and rate > 0:
                article = db.query(models.Article).filter(models.Article.article_number == article_num).first()
                if article:
                    line_item = models.OrderLineItem(
                        po_id=new_po.id,
                        article_id=article.id,
                        requested_quantity=quantity,
                        locked_rate=rate
                    )
                    db.add(line_item)
                    items_added_count += 1 # Increment our counter
        i += 1
    
    # Now, check our reliable counter.
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
    return templates.TemplateResponse("admin/logistics_detail.html", {"request": request, "po": po})

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
    photo: UploadFile = File(...)
):
    if current_user.role != "admin": return RedirectResponse(url="/dashboard")

    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == po_id).first()
    if po:
        file_content = await photo.read()
        photo_url = file_uploader.upload_file(file_content, photo.filename)
        
        if proof_type == 'pickup':
            po.pickup_photo_url = photo_url
        elif proof_type == 'delivery':
            po.delivery_photo_url = photo_url
            po.status = models.POStatus.DELIVERED.value # Mark as delivered after final photo

        db.commit()

    return RedirectResponse(url=f"/po/{po_id}/logistics", status_code=303)