# app/db/models.py
import enum
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base

class UserRole(enum.Enum):
    store = "store"
    purchaser = "purchaser"
    admin = "admin"

# class OrderStatus(enum.Enum):
#     PENDING_APPROVAL = "PENDING_APPROVAL"
#     REJECTED = "REJECTED"
#     PENDING_PURCHASE = "PENDING_PURCHASE"
#     PURCHASED = "PURCHASED"
#     DELIVERED = "DELIVERED"

class OrderStatus(enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    PENDING_PURCHASE = "PENDING_PURCHASE"
    PURCHASED = "PURCHASED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"  # <-- ADD THIS
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(Enum(UserRole))

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_id_str = Column(String, unique=True, index=True)
    category = Column(String, index=True)
    quantity = Column(Integer)
    expected_delivery_time = Column(DateTime)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING_PURCHASE)
    
    # Relationships
    store_id = Column(Integer, ForeignKey("users.id"))
    purchaser_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Purchase details
    buy_rate = Column(Float, nullable=True)
    proof_photo_url = Column(String, nullable=True)
    adjusted_quantity = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    store = relationship("User", foreign_keys=[store_id])
    purchaser = relationship("User", foreign_keys=[purchaser_id])