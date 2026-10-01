from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import httpx
import os
import sys
from datetime import datetime
import logging
from contextlib import asynccontextmanager
import json
from fastapi import Response

# Add shared modules to path
sys.path.append('/app/shared')

from models import (
    ChatRequest, ChatResponse, QuestionGenerationRequest, 
    LectureRequest, HealthCheck, BookModel
)
from utils import setup_logging, get_redis

# Setup logging
setup_logging("api-gateway")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting API Gateway...")
    
    # Initialize Redis for rate limiting and caching
    redis_manager = get_redis()
    app.state.redis = redis_manager
    
    # Increase HTTP client timeout for file uploads and long operations
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(10000.0))  # 30 minutes timeout
    app.state.rate_limiter = RateLimiter(app.state.redis)
    
    logger.info("API Gateway started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down API Gateway...")
    await app.state.http_client.aclose()
    redis_manager.disconnect()

app = FastAPI(
    title="Zakerly API Gateway",
    description="API Gateway for Zakerly microservices platform",
    version="1.0.0",
    lifespan=lifespan
)


# CORS middleware - Configured to allow ZeroTier network access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins including ZeroTier IPs (172.24.111.111:3001)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service URLs
INGESTION_SERVICE_URL = os.getenv("INGESTION_SERVICE_URL", "http://ingestion-service:8000")
CHAT_SERVICE_URL = os.getenv("CHAT_SERVICE_URL", "http://chat-service:8000")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000")
EXAM_SERVICE_URL = os.getenv("EXAM_SERVICE_URL", "http://exam-service:8000")
SCRIPT_SERVICE_URL = os.getenv("SCRIPT_SERVICE_URL", "http://script-service:8000")
PRESENTATION_SERVICE_URL = os.getenv("PRESENTATION_SERVICE_URL", "http://presentation-service:8005")

class RateLimiter:
    """Simple rate limiter using Redis"""
    
    def __init__(self, redis_manager, max_requests: int = 100, window_seconds: int = 60):
        self.redis = redis_manager
        self.max_requests = max_requests
        self.window_seconds = window_seconds
    
    async def is_allowed(self, client_id: str) -> bool:
        """Check if request is allowed"""
        try:
            if not self.redis.client:
                return True  # Allow if Redis is not available
            
            key = f"rate_limit:{client_id}"
            current = self.redis.client.get(key)
            
            if current is None:
                # First request in window
                self.redis.client.setex(key, self.window_seconds, 1)
                return True
            
            if int(current) >= self.max_requests:
                return False
            
            # Increment counter
            self.redis.client.incr(key)
            return True
            
        except Exception as e:
            logger.error(f"Rate limiter error: {e}")
            return True  # Allow on error

async def check_rate_limit(request: Request):
    """Rate limiting dependency"""
    client_ip = request.client.host
    
    if not await request.app.state.rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please try again later."
        )

async def forward_request(
    service_url: str,
    endpoint: str,
    method: str = "GET",
    data: dict = None,
    files: dict = None,
    params: dict = None
) -> dict:
    """Forward request to microservice"""
    try:
        url = f"{service_url}{endpoint}"
        
        client = app.state.http_client
        if method == "GET":
            response = await client.get(url, params=params)
        elif method == "POST":
            if files:
                response = await client.post(url, files=files, data=data, params=params)
            else:
                response = await client.post(url, json=data, params=params)
        elif method == "PUT":
            response = await client.put(url, json=data, params=params)
        elif method == "DELETE":
            response = await client.delete(url)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        response.raise_for_status()
        return response.json()
        
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error forwarding to {service_url}{endpoint}: {e}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Service error: {e.response.text}"
        )
    except Exception as e:
        logger.error(f"Error forwarding to {service_url}{endpoint}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Gateway error: {str(e)}"
        )


@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint"""
    return HealthCheck(
        status="healthy",
        timestamp=datetime.utcnow(),
        service="api-gateway",
        version="1.0.0"
    )

# Ingestion Service Endpoints
@app.post("/api/v1/upload", response_model=BookModel, dependencies=[Depends(check_rate_limit)])
async def upload_book(curriculum_id: int, file: UploadFile = File(...)):
    """Upload book file for a specific curriculum"""
    try:
        # Prepare file for forwarding
        file_content = await file.read()
        files = {"file": (file.filename, file_content, file.content_type)}
        params = {"curriculum_id": curriculum_id}
        
        result = await forward_request(
            INGESTION_SERVICE_URL,
            "/upload",
            method="POST",
            files=files,
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in upload endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/books", dependencies=[Depends(check_rate_limit)])
async def list_books(curriculum_id: int = None, category_id: int = None):
    """List books by curriculum or category"""
    try:
        params = {}
        if curriculum_id:
            params["curriculum_id"] = curriculum_id
        elif category_id:
            params["category_id"] = category_id
        
        result = await forward_request(
            INGESTION_SERVICE_URL,
            "/books",
            method="GET",
            params=params if params else None
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in list books endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Curriculum Endpoints
@app.post("/api/v1/curriculums", dependencies=[Depends(check_rate_limit)])
async def create_curriculum(request: Request):
    """Create a new curriculum"""
    try:
        data = await request.json()
        result = await forward_request(
            INGESTION_SERVICE_URL,
            "/curriculums",
            method="POST",
            data=data
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create curriculum endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/curriculums", dependencies=[Depends(check_rate_limit)])
async def list_curriculums():
    """List all curriculums"""
    try:
        result = await forward_request(
            INGESTION_SERVICE_URL,
            "/curriculums",
            method="GET"
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in list curriculums endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/curriculums/{curriculum_id}", dependencies=[Depends(check_rate_limit)])
async def get_curriculum(curriculum_id: int):
    """Get curriculum by ID"""
    try:
        result = await forward_request(
            INGESTION_SERVICE_URL,
            f"/curriculums/{curriculum_id}",
            method="GET"
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get curriculum endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/v1/curriculums/{curriculum_id}", dependencies=[Depends(check_rate_limit)])
async def update_curriculum(curriculum_id: int, request: Request):
    """Update curriculum by ID"""
    try:
        data = await request.json()
        result = await forward_request(
            INGESTION_SERVICE_URL,
            f"/curriculums/{curriculum_id}",
            method="PUT",
            data=data
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update curriculum endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/curriculums/{curriculum_id}", dependencies=[Depends(check_rate_limit)])
async def delete_curriculum(curriculum_id: int):
    """Delete curriculum by ID"""
    try:
        result = await forward_request(
            INGESTION_SERVICE_URL,
            f"/curriculums/{curriculum_id}",
            method="DELETE"
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete curriculum endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/curriculums/{curriculum_id}/books", dependencies=[Depends(check_rate_limit)])
async def list_curriculum_books(curriculum_id: int):
    """List all books in a curriculum"""
    try:
        result = await forward_request(
            INGESTION_SERVICE_URL,
            f"/curriculums/{curriculum_id}/books",
            method="GET"
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in list curriculum books endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/books/{book_id}", dependencies=[Depends(check_rate_limit)])
async def get_book(book_id: int):
    """Get book by ID"""
    try:
        result = await forward_request(
            INGESTION_SERVICE_URL,
            f"/books/{book_id}",
            method="GET"
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get book endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/books/{book_id}", dependencies=[Depends(check_rate_limit)])
async def delete_book(book_id: int):
    """Delete book"""
    try:
        result = await forward_request(
            INGESTION_SERVICE_URL,
            f"/books/{book_id}",
            method="DELETE"
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete book endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Chat Service Endpoints
@app.post("/api/v1/chat", response_model=ChatResponse, dependencies=[Depends(check_rate_limit)])
async def chat(request: ChatRequest):
    """Handle chat request"""
    try:
        result = await forward_request(
            CHAT_SERVICE_URL,
            "/chat",
            method="POST",
            data=request.dict()
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/generate-questions", dependencies=[Depends(check_rate_limit)])
async def generate_questions(request: QuestionGenerationRequest):
    """Generate questions - routed to exam service"""
    try:
        result = await forward_request(
            EXAM_SERVICE_URL,
            "/generate-questions",
            method="POST",
            data=request.dict()
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in generate questions endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/generate-lecture", dependencies=[Depends(check_rate_limit)])
async def generate_lecture(request: LectureRequest):
    """Generate lecture - routed to script service"""
    try:
        result = await forward_request(
            SCRIPT_SERVICE_URL,
            "/generate-lecture",
            method="POST",
            data=request.dict()
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in generate lecture endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Session Management Endpoints
@app.post("/api/v1/sessions", dependencies=[Depends(check_rate_limit)])
async def create_session(user_id: str, curriculum_name: str = None, book_title: str = None, session_name: str = None):
    """Create chat session - supports both curriculum-based and book-based sessions"""
    try:
        # Validate that either curriculum_name or book_title is provided
        if not curriculum_name and not book_title:
            raise HTTPException(
                status_code=422,
                detail="Either curriculum_name or book_title must be provided"
            )
        
        # Pass as query parameters to match chat service expectation
        params = {"user_id": user_id}
        
        if curriculum_name:
            params["curriculum_name"] = curriculum_name
        elif book_title:
            params["book_title"] = book_title
            
        if session_name:
            params["session_name"] = session_name
        
        result = await forward_request(
            CHAT_SERVICE_URL,
            "/sessions",
            method="POST",
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create session endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/sessions/{session_id}", dependencies=[Depends(check_rate_limit)])
async def get_session(session_id: str):
    """Get session"""
    try:
        result = await forward_request(
            CHAT_SERVICE_URL,
            f"/sessions/{session_id}",
            method="GET"
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get session endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/users/{user_id}/sessions", dependencies=[Depends(check_rate_limit)])
async def get_user_sessions(user_id: str):
    """Get user sessions"""
    try:
        result = await forward_request(
            CHAT_SERVICE_URL,
            f"/users/{user_id}/sessions",
            method="GET"
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get user sessions endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/sessions/{session_id}/history", dependencies=[Depends(check_rate_limit)])
async def get_chat_history(session_id: str, limit: int = 50):
    """Get chat history"""
    try:
        params = {"limit": limit}
        result = await forward_request(
            CHAT_SERVICE_URL,
            f"/sessions/{session_id}/history",
            method="GET",
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get chat history endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/sessions/{session_id}", dependencies=[Depends(check_rate_limit)])
async def delete_session(session_id: str):
    """Delete session"""
    try:
        result = await forward_request(
            CHAT_SERVICE_URL,
            f"/sessions/{session_id}",
            method="DELETE"
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete session endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/status")
async def get_system_status():
    """Get system status"""
    try:
        status = {
            "gateway": "healthy",
            "services": {}
        }
        
        # Check ingestion service
        try:
            await forward_request(INGESTION_SERVICE_URL, "/health", method="GET")
            status["services"]["ingestion"] = "healthy"
        except:
            status["services"]["ingestion"] = "unhealthy"
        
        # Check chat service
        try:
            await forward_request(CHAT_SERVICE_URL, "/health", method="GET")
            status["services"]["chat"] = "healthy"
        except:
            status["services"]["chat"] = "unhealthy"
        
        # Check auth service
        try:
            await forward_request(AUTH_SERVICE_URL, "/health", method="GET")
            status["services"]["auth"] = "healthy"
        except:
            status["services"]["auth"] = "unhealthy"
        
        # Check exam service
        try:
            await forward_request(EXAM_SERVICE_URL, "/health", method="GET")
            status["services"]["exam"] = "healthy"
        except:
            status["services"]["exam"] = "unhealthy"
        
        # Check script service
        try:
            await forward_request(SCRIPT_SERVICE_URL, "/health", method="GET")
            status["services"]["script"] = "healthy"
        except:
            status["services"]["script"] = "unhealthy"
        
        return status
        
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Authentication Endpoints
@app.post("/api/v1/auth/signup")
async def signup(request: Request):
    """User signup"""
    try:
        data = await request.json()
        result = await forward_request(
            AUTH_SERVICE_URL,
            "/signup",
            method="POST",
            data=data
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in signup endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/auth/login")
async def login(request: Request):
    """User login"""
    try:
        data = await request.json()
        result = await forward_request(
            AUTH_SERVICE_URL,
            "/login",
            method="POST",
            data=data
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in login endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/auth/me", dependencies=[Depends(check_rate_limit)])
async def get_current_user(request: Request):
    """Get current user info"""
    try:
        # Forward the authorization header
        headers = {}
        if "authorization" in request.headers:
            headers["authorization"] = request.headers["authorization"]
        
        client = app.state.http_client
        response = await client.get(
            f"{AUTH_SERVICE_URL}/me",
            headers=headers
        )
        response.raise_for_status()
        return response.json()
        
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error getting current user: {e}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Auth service error: {e.response.text}"
        )
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/auth/verify-token", dependencies=[Depends(check_rate_limit)])
async def verify_token(request: Request):
    """Verify authentication token"""
    try:
        # Forward the authorization header
        headers = {}
        if "authorization" in request.headers:
            headers["authorization"] = request.headers["authorization"]
        
        client = app.state.http_client
        response = await client.post(
            f"{AUTH_SERVICE_URL}/verify-token",
            headers=headers
        )
        response.raise_for_status()
        return response.json()
        
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error verifying token: {e}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Auth service error: {e.response.text}"
        )
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Enhanced Curriculum Script Generation Endpoint
@app.post("/api/v1/curriculum-scripts/generate", dependencies=[Depends(check_rate_limit)])
async def generate_curriculum_script(request: Request, user_id: str):
    """Generate script based on curriculum scope - routed to script service"""
    try:
        data = await request.json()
        params = {"user_id": user_id}
        
        result = await forward_request(
            SCRIPT_SERVICE_URL,
            "/curriculum-scripts/generate",
            method="POST",
            data=data,
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in generate curriculum script endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Lecture Scripts Endpoints
@app.post("/api/v1/scripts", dependencies=[Depends(check_rate_limit)])
async def create_script(request: Request, user_id: str):
    """Create a new lecture script - routed to script service"""
    try:
        data = await request.json()
        params = {"user_id": user_id}
        
        result = await forward_request(
            SCRIPT_SERVICE_URL,
            "/scripts",
            method="POST",
            data=data,
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create script endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/scripts/{script_id}", dependencies=[Depends(check_rate_limit)])
async def get_script(script_id: str, user_id: str):
    """Get a specific lecture script by ID - routed to script service"""
    try:
        params = {"user_id": user_id}
        result = await forward_request(
            SCRIPT_SERVICE_URL,
            f"/scripts/{script_id}",
            method="GET",
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get script endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/users/{user_id}/scripts", dependencies=[Depends(check_rate_limit)])
async def get_user_scripts(user_id: str):
    """Get all lecture scripts for a user - routed to script service"""
    try:
        result = await forward_request(
            SCRIPT_SERVICE_URL,
            f"/users/{user_id}/scripts",
            method="GET"
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get user scripts endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/v1/scripts/{script_id}", dependencies=[Depends(check_rate_limit)])
async def update_script(script_id: str, request: Request, user_id: str):
    """Update a lecture script - routed to script service"""
    try:
        data = await request.json()
        params = {"user_id": user_id}
        
        result = await forward_request(
            SCRIPT_SERVICE_URL,
            f"/scripts/{script_id}",
            method="PUT",
            data=data,
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update script endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/scripts/{script_id}", dependencies=[Depends(check_rate_limit)])
async def delete_script(script_id: str, user_id: str):
    """Delete a lecture script - routed to script service"""
    try:
        params = {"user_id": user_id}
        result = await forward_request(
            SCRIPT_SERVICE_URL,
            f"/scripts/{script_id}",
            method="DELETE",
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete script endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== PRESENTATION ENDPOINTS ====================

@app.post("/api/v1/presentations/generate", dependencies=[Depends(check_rate_limit)])
async def generate_presentation(request: Request, user_id: str):
    """Generate presentation - routed to presentation service"""
    try:
        data = await request.json()
        params = {"user_id": user_id}
        
        result = await forward_request(
            PRESENTATION_SERVICE_URL,
            "/curriculum-presentations/generate",
            method="POST",
            data=data,
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in generate presentation endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/presentations", dependencies=[Depends(check_rate_limit)])
async def create_presentation(request: Request, user_id: str):
    """Create a new presentation - routed to presentation service"""
    try:
        data = await request.json()
        params = {"user_id": user_id}
        
        result = await forward_request(
            PRESENTATION_SERVICE_URL,
            "/presentations",
            method="POST",
            data=data,
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create presentation endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/presentations/{presentation_id}", dependencies=[Depends(check_rate_limit)])
async def get_presentation(presentation_id: str, user_id: str):
    """Get a specific presentation by ID - routed to presentation service"""
    try:
        params = {"user_id": user_id}
        result = await forward_request(
            PRESENTATION_SERVICE_URL,
            f"/presentations/{presentation_id}",
            method="GET",
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get presentation endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/users/{user_id}/presentations", dependencies=[Depends(check_rate_limit)])
async def get_user_presentations(user_id: str):
    """Get all presentations for a user - routed to presentation service"""
    try:
        result = await forward_request(
            PRESENTATION_SERVICE_URL,
            f"/users/{user_id}/presentations",
            method="GET"
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get user presentations endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/v1/presentations/{presentation_id}", dependencies=[Depends(check_rate_limit)])
async def update_presentation(presentation_id: str, request: Request, user_id: str):
    """Update a presentation - routed to presentation service"""
    try:
        data = await request.json()
        params = {"user_id": user_id}
        
        result = await forward_request(
            PRESENTATION_SERVICE_URL,
            f"/presentations/{presentation_id}",
            method="PUT",
            data=data,
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update presentation endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/presentations/{presentation_id}", dependencies=[Depends(check_rate_limit)])
async def delete_presentation(presentation_id: str, user_id: str):
    """Delete a presentation - routed to presentation service"""
    try:
        params = {"user_id": user_id}
        result = await forward_request(
            PRESENTATION_SERVICE_URL,
            f"/presentations/{presentation_id}",
            method="DELETE",
            params=params
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete presentation endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url)
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url)
        }
    )

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )