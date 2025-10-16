# app/main.py
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from starlette import status

from app.db import models
from app.db.base import get_db, engine
from app.web.routes import router as web_router
from app.auth import create_access_token, get_password_hash, verify_password

from app.core.config import ARTICLES

# Create database tables on startup
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Blue Marina MVP")

# REMOVED: The old exception handler is no longer needed.

# --- Token Endpoint ---
# This endpoint now handles the form submission, sets the cookie, and redirects.
@app.post("/token", tags=["Auth"])
async def login_for_access_token(response: RedirectResponse, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        # If login fails, redirect back to login page with an error message
        return RedirectResponse(url="/login?error=1", status_code=status.HTTP_302_FOUND)

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role}
    )
    
    # Create a redirect response to the dashboard
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    
    # Set the token in an HTTP-Only cookie
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

# --- Include Web Routes ---
app.include_router(web_router)

# --- On-the-fly User Creation for MVP ---
@app.on_event("startup")
def seed_initial_data():
    db = next(get_db())
    # ... (user creation logic remains the same)
    if not db.query(models.User).filter(models.User.username == "metro").first():
        user = models.User(username="metro", hashed_password=get_password_hash("password"), role=models.UserRole.store.value)
        db.add(user)
    if not db.query(models.User).filter(models.User.username == "buyer1").first():
        user = models.User(username="buyer1", hashed_password=get_password_hash("password"), role=models.UserRole.purchaser.value)
        db.add(user)
    if not db.query(models.User).filter(models.User.username == "admin").first():
        user = models.User(username="admin", hashed_password=get_password_hash("password"), role=models.UserRole.admin.value)
        db.add(user)

    if db.query(models.Article).count() == 0:
        for article_data in ARTICLES:
            article = models.Article(**article_data)
            db.add(article)

    db.commit()
    db.close()