# app/web/routes.py
import uuid
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.db import models
from app.auth import get_current_user # <<< THIS IS THE ONLY LINE THAT CHANGES
from app.services.logic import calculate_purchase_details
from datetime import datetime

router = APIRouter(tags=["Web"])
templates = Jinja2Templates(directory="app/web/templates")

# --- Auth Pages ---
# --- Auth Pages ---
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request})

@router.get("/", response_class=RedirectResponse)
def root():
    # Change this to redirect to the login page by default.
    return RedirectResponse(url="/login")

# --- Shared Dashboard ---
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role == models.UserRole.store:
        orders = db.query(models.Order).filter(models.Order.store_id == current_user.id).all()
        return templates.TemplateResponse("store/dashboard.html", {"request": request, "orders": orders, "user": current_user})
    
    if current_user.role == models.UserRole.purchaser:
        # Show orders pending purchase or assigned to this purchaser
        orders = db.query(models.Order).filter(
            (models.Order.status == models.OrderStatus.PENDING_PURCHASE) | 
            (models.Order.purchaser_id == current_user.id)
        ).all()
        return templates.TemplateResponse("purchaser/dashboard.html", {"request": request, "orders": orders, "user": current_user})
    
    if current_user.role == models.UserRole.admin:
        orders = db.query(models.Order).all()
        return templates.TemplateResponse("admin/dashboard.html", {"request": request, "orders": orders, "user": current_user})

# --- Store Routes ---
@router.get("/create-order", response_class=HTMLResponse)
def create_order_page(request: Request, current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.store:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("store/create_order.html", {"request": request, "user": current_user})

@router.post("/create-order")
def handle_create_order(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    category: str = Form(...),
    quantity: int = Form(...),
    delivery_time: str = Form(...)
):
    if current_user.role != models.UserRole.store:
        return RedirectResponse(url="/dashboard", status_code=303)
    
    order = models.Order(
        order_id_str=f"BM-{uuid.uuid4().hex[:6].upper()}",
        category=category,
        quantity=quantity,
        expected_delivery_time=datetime.fromisoformat(delivery_time),
        store_id=current_user.id,
        status=models.OrderStatus.PENDING_PURCHASE
    )
    db.add(order)
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)

# --- Purchaser Routes ---
@router.post("/accept-order/{order_id}")
def accept_order(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.purchaser:
        return RedirectResponse(url="/dashboard", status_code=303)
    
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order and order.status == models.OrderStatus.PENDING_PURCHASE:
        order.purchaser_id = current_user.id
        db.commit()
    return RedirectResponse(url=f"/order/{order_id}", status_code=303)

@router.get("/order/{order_id}", response_class=HTMLResponse)
def order_detail_page(order_id: int, request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.purchaser:
        return RedirectResponse(url="/dashboard", status_code=303)
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    return templates.TemplateResponse("purchaser/order_detail.html", {"request": request, "order": order, "user": current_user})

@router.post("/submit-purchase/{order_id}")
def submit_purchase(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    buy_rate: float = Form(...)
):
    if current_user.role != models.UserRole.purchaser:
        return RedirectResponse(url="/dashboard", status_code=303)
        
    order = db.query(models.Order).filter(models.Order.id == order_id, models.Order.purchaser_id == current_user.id).first()
    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)

    adjusted_qty, margin = calculate_purchase_details(order.category, order.quantity, buy_rate)
    
    order.buy_rate = buy_rate
    order.adjusted_quantity = adjusted_qty
    order.status = models.OrderStatus.PENDING_APPROVAL
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)

# --- Admin Routes ---
@router.post("/approve-order/{order_id}")
def approve_order(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.admin:
        return RedirectResponse(url="/dashboard", status_code=303)
    
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order:
        order.status = models.OrderStatus.PURCHASED # Ready for manual fleet assignment
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)

@router.post("/reject-order/{order_id}")
def reject_order(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.admin:
        return RedirectResponse(url="/dashboard", status_code=303)

    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order:
        order.status = models.OrderStatus.REJECTED # Goes back to purchaser
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


# --- Admin Fleet Routes (Manual) ---
@router.post("/dispatch-order/{order_id}")
def dispatch_order(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order and order.status == models.OrderStatus.PURCHASED:
        order.status = models.OrderStatus.OUT_FOR_DELIVERY
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)

@router.post("/mark-delivered/{order_id}")
def mark_delivered(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.admin:
        raise HTTPException(status_code=403, detail="Not authorized")

    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if order and order.status == models.OrderStatus.OUT_FOR_DELIVERY:
        order.status = models.OrderStatus.DELIVERED
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)

# --- Store Confirmation Route ---
@router.post("/confirm-delivery/{order_id}")
def confirm_delivery(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.store:
        raise HTTPException(status_code=403, detail="Not authorized")

    order = db.query(models.Order).filter(models.Order.id == order_id, models.Order.store_id == current_user.id).first()
    if order and order.status == models.OrderStatus.DELIVERED:
        # For MVP, we can just change the status. For Phase 2, this would close the order.
        order.status = models.OrderStatus.PURCHASED # Or a new 'COMPLETED' status
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/confirm-delivery/{order_id}")
def confirm_delivery(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != models.UserRole.store:
        raise HTTPException(status_code=403, detail="Not authorized")

    order = db.query(models.Order).filter(models.Order.id == order_id, models.Order.store_id == current_user.id).first()
    if order and order.status == models.OrderStatus.DELIVERED:
        # THIS IS THE FIX: Set the status to COMPLETED instead of PURCHASED
        order.status = models.OrderStatus.COMPLETED
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)