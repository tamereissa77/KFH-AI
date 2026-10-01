from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import uvicorn
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, EmailStr, ValidationError
import logging
import json
from contextlib import asynccontextmanager

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# JWT settings
SECRET_KEY = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zakerly_user:zakerly_password@postgres:5432/zakerly_db")

def get_db_connection():
    """Get database connection"""
    try:
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")

class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    confirm_password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class User(BaseModel):
    id: str
    full_name: str
    email: str
    created_at: datetime

class UserStats(BaseModel):
    totalBooks: int
    totalScripts: int
    totalSessions: int
    totalChats: int
    learningHours: float
    streak: int

class ActivityTrack(BaseModel):
    activity_type: str
    metadata: str = "{}"

class RecentActivity(BaseModel):
    courseName: str
    lastAccessed: str
    progress: float
    activityType: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Auth Service...")
    yield
    logger.info("Shutting down Auth Service...")

app = FastAPI(
    title="Zakerly Auth Service",
    description="Authentication service for Zakerly platform",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add validation error handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """Handle validation errors"""
    logger.error(f"Validation error: {exc}")
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation error",
            "details": str(exc),
            "timestamp": datetime.utcnow().isoformat()
        }
    )

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash password"""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    """Create access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # Get user from database
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, full_name, email, created_at FROM users WHERE id = %s",
                (user_id,)
            )
            user_data = cursor.fetchone()
        conn.close()
        
        if user_data is None:
            raise credentials_exception
        
        return User(
            id=str(user_data["id"]),
            full_name=user_data["full_name"],
            email=user_data["email"],
            created_at=user_data["created_at"]
        )
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        raise credentials_exception

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow(),
        "service": "auth-service"
    }

@app.post("/signup", response_model=Token)
async def signup(user_data: UserCreate):
    """User signup"""
    try:
        # Debug logging
        logger.info(f"Signup request received - email: {user_data.email}, full_name: {user_data.full_name}")
        logger.info(f"Password length: {len(user_data.password)}, confirm_password length: {len(user_data.confirm_password)}")
        
        # Validate passwords match
        if user_data.password != user_data.confirm_password:
            logger.warning(f"Password mismatch for user: {user_data.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Passwords do not match"
            )
        
        # Validate password length
        if len(user_data.password) < 8:
            logger.warning(f"Password too short for user: {user_data.email} (length: {len(user_data.password)})")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters long"
            )
        
        # Hash password
        hashed_password = get_password_hash(user_data.password)
        
        # Create user in database
        conn = get_db_connection()
        
        # Check if user already exists
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE email = %s", (user_data.email,))
            if cursor.fetchone():
                conn.close()
                logger.warning(f"Email already registered: {user_data.email}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )
            
            # Insert new user
            cursor.execute(
                """
                INSERT INTO users (full_name, email, password_hash) 
                VALUES (%s, %s, %s) 
                RETURNING id
                """,
                (user_data.full_name, user_data.email, hashed_password)
            )
            
            user_result = cursor.fetchone()
            user_id = user_result["id"]
            conn.commit()
        conn.close()
        
        # Create access token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user_id), "email": user_data.email, "full_name": user_data.full_name},
            expires_delta=access_token_expires
        )
        
        return Token(access_token=access_token, token_type="bearer")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during signup"
        )

@app.post("/login", response_model=Token)
async def login(user_credentials: UserLogin):
    """User login"""
    try:
        conn = get_db_connection()
        
        # Get user by email
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, full_name, email, password_hash FROM users WHERE email = %s",
                (user_credentials.email,)
            )
            
            user_data = cursor.fetchone()
        conn.close()
        
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        user_id, full_name, email, password_hash = user_data["id"], user_data["full_name"], user_data["email"], user_data["password_hash"]
        
        # Verify password
        if not verify_password(user_credentials.password, password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Create access token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user_id), "email": email, "full_name": full_name},
            expires_delta=access_token_expires
        )
        
        return Token(access_token=access_token, token_type="bearer")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during login"
        )

@app.get("/me", response_model=User)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user

@app.post("/verify-token")
async def verify_token(current_user: User = Depends(get_current_user)):
    """Verify if token is valid"""
    return {"valid": True, "user_id": current_user.id}

@app.post("/track-activity")
async def track_activity(
    activity_data: ActivityTrack,
    current_user: User = Depends(get_current_user)
):
    """Track user activity"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Insert activity record
            cursor.execute(
                """
                INSERT INTO user_activities (user_id, activity_type, metadata, activity_date) 
                VALUES (%s, %s, %s, %s)
                """,
                (current_user.id, activity_data.activity_type, activity_data.metadata, datetime.utcnow())
            )
            conn.commit()
        conn.close()
        
        return {"status": "success", "message": "Activity tracked"}
    except Exception as e:
        logger.error(f"Error tracking activity: {e}")
        raise HTTPException(status_code=500, detail="Failed to track activity")

@app.get("/stats", response_model=UserStats)
async def get_user_stats(current_user: User = Depends(get_current_user)):
    """Get user learning statistics"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Get books count (assuming books table exists)
            cursor.execute("SELECT COUNT(*) as count FROM books WHERE created_by = %s OR %s = %s", (current_user.id, current_user.id, current_user.id))
            books_result = cursor.fetchone()
            total_books = books_result["count"] if books_result else 0
            
            # Get scripts count (assuming lecture_scripts table exists)
            cursor.execute("SELECT COUNT(*) as count FROM lecture_scripts WHERE user_id = %s", (current_user.id,))
            scripts_result = cursor.fetchone()
            total_scripts = scripts_result["count"] if scripts_result else 0
            
            # Get chat sessions count (assuming chat_sessions table exists)
            cursor.execute("SELECT COUNT(*) as count FROM chat_sessions WHERE user_id = %s", (current_user.id,))
            sessions_result = cursor.fetchone()
            total_sessions = sessions_result["count"] if sessions_result else 0
            
            # Calculate learning hours (estimate 30 minutes per session)
            learning_hours = total_sessions * 0.5
            
            # Calculate streak (simplified - count consecutive days with activity)
            cursor.execute(
                """
                SELECT COUNT(DISTINCT DATE(activity_date)) as streak 
                FROM user_activities 
                WHERE user_id = %s 
                AND activity_date >= %s
                """,
                (current_user.id, datetime.utcnow() - timedelta(days=30))
            )
            streak_result = cursor.fetchone()
            streak = min(streak_result["streak"] if streak_result else 0, 30)
            
        conn.close()
        
        return UserStats(
            totalBooks=total_books,
            totalScripts=total_scripts,
            totalSessions=total_sessions,
            totalChats=total_sessions,
            learningHours=learning_hours,
            streak=streak
        )
    except Exception as e:
        logger.error(f"Error getting user stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user statistics")

@app.get("/recent-activity")
async def get_recent_activity(current_user: User = Depends(get_current_user)):
    """Get user's recent learning activity"""
    try:
        conn = get_db_connection()
        activities = []
        
        with conn.cursor() as cursor:
            # Get recent scripts
            cursor.execute(
                """
                SELECT title, created_at, 'script' as type 
                FROM lecture_scripts 
                WHERE user_id = %s 
                ORDER BY created_at DESC 
                LIMIT 5
                """,
                (current_user.id,)
            )
            scripts = cursor.fetchall()
            
            for script in scripts:
                activities.append({
                    "courseName": script["title"],
                    "lastAccessed": script["created_at"].strftime("%Y-%m-%d"),
                    "progress": 100.0,  # Scripts are considered complete when created
                    "activityType": "script"
                })
            
            # Get recent chat sessions
            cursor.execute(
                """
                SELECT session_name, updated_at, 'chat' as type 
                FROM chat_sessions 
                WHERE user_id = %s 
                ORDER BY updated_at DESC 
                LIMIT 5
                """,
                (current_user.id,)
            )
            chats = cursor.fetchall()
            
            for chat in chats:
                activities.append({
                    "courseName": chat["session_name"] or "Chat Session",
                    "lastAccessed": chat["updated_at"].strftime("%Y-%m-%d"),
                    "progress": 75.0,  # Estimate progress for chats
                    "activityType": "chat"
                })
        
        conn.close()
        
        # Sort by date and return most recent
        activities.sort(key=lambda x: x["lastAccessed"], reverse=True)
        return activities[:10]
        
    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        raise HTTPException(status_code=500, detail="Failed to get recent activity")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
