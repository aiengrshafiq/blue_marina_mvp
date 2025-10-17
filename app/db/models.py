# app/db/models.py
import enum
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
# REMOVED: No longer need the Enum type from sqlalchemy
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base

class UserRole(enum.Enum):
    store = "store"
    purchaser = "purchaser"
    admin = "admin"

class POStatus(enum.Enum):
    PENDING_BIDS = "PENDING_BIDS"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    IN_LOGISTICS = "IN_LOGISTICS"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"

class BidStatus(enum.Enum):
    PENDING = "PENDING"
    RECOMMENDED = "RECOMMENDED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    # THE FIX: Change Enum to String
    role = Column(String)

class Article(Base):
    __tablename__ = "articles"
    id = Column(Integer, primary_key=True, index=True)
    article_number = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    unit = Column(String, default="kg")

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id = Column(Integer, primary_key=True, index=True)
    po_number = Column(String, unique=True, index=True)
    status = Column(String(50), default=POStatus.PENDING_BIDS.value)
    store_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # --- ADD THESE NEW LOGISTICS FIELDS ---
    assigned_driver = Column(String, nullable=True)
    pickup_time = Column(DateTime, nullable=True)
    pickup_temperature = Column(Float, nullable=True)
    pickup_photo_url = Column(String, nullable=True)
    delivery_photo_url = Column(String, nullable=True)
    grn_notes = Column(String, nullable=True)
    # ------------------------------------
    
    store = relationship("User")
    line_items = relationship("OrderLineItem", back_populates="purchase_order")

class OrderLineItem(Base):
    __tablename__ = "order_line_items"
    id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"))
    article_id = Column(Integer, ForeignKey("articles.id"))
    requested_quantity = Column(Float)
    allocated_quantity = Column(Float, nullable=True)
    locked_rate = Column(Float)
    
    purchase_order = relationship("PurchaseOrder", back_populates="line_items")
    article = relationship("Article")
    bids = relationship("Bid", back_populates="line_item")

class Bid(Base):
    __tablename__ = "bids"
    id = Column(Integer, primary_key=True, index=True)
    line_item_id = Column(Integer, ForeignKey("order_line_items.id"))
    purchaser_id = Column(Integer, ForeignKey("users.id"))
    bid_rate = Column(Float)
    proof_photo_url = Column(String)
    # THE FIX: Change Enum to String, provide a length
    status = Column(String(50), default=BidStatus.PENDING.value)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    line_item = relationship("OrderLineItem", back_populates="bids")
    purchaser = relationship("User")

class WeeklyRateLock(Base):
    __tablename__ = "weekly_rate_locks"
    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    selling_rate = Column(Float, nullable=False)
    week_number = Column(Integer, nullable=False) # e.g., 42 for the 42nd week of the year
    year = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    article = relationship("Article")