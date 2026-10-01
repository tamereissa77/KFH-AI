from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import sys
from datetime import datetime
import logging
from contextlib import asynccontextmanager
from fastapi import Response
from typing import List

# Add shared modules to path
sys.path.append('/app/shared')

from models import (
    ChatRequest, ChatResponse, HealthCheck, ChatSessionModel
)
from database import get_database, DatabaseManager
from utils import setup_logging, get_redis
from chat_service import ChatService

# Setup logging
setup_logging("chat-service")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting Chat Service...")
    
    # Initialize database
    db = get_database()
    await db.initialize()
    
    # Initialize Redis
    redis_manager = get_redis()
    
    # Initialize chat service
    app.state.chat_service = ChatService(db, redis_manager)
    
    logger.info("Chat Service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Chat Service...")
    await db.close()
    redis_manager.disconnect()

app = FastAPI(
    title="Zakerly Chat Service",
    description="Intelligent chat service for Zakerly platform",
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

def get_chat_service() -> ChatService:
    """Dependency to get chat service"""
    return app.state.chat_service

@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint"""
    return HealthCheck(
        status="healthy",
        timestamp=datetime.utcnow(),
        service="chat-service",
        version="1.0.0"
    )

@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Handle chat requests"""
    try:
        logger.info(f"Chat request for curriculum: {request.curriculum}, session: {request.session_id}")
        
        response = await chat_service.handle_chat(request)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling chat request: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/sessions", response_model=ChatSessionModel)
async def create_session(
    user_id: str,
    curriculum_name: str = None,
    book_title: str = None,
    session_name: str = None,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Create new chat session - supports both curriculum-based and book-based sessions"""
    try:
        if not curriculum_name and not book_title:
            raise HTTPException(status_code=400, detail="Either curriculum_name or book_title must be provided")
        
        # Use unified create_chat_session method
        session = await chat_service.create_chat_session(
            user_id=user_id,
            curriculum_name=curriculum_name,
            book_title=book_title,
            session_name=session_name
        )
        
        return session
        
    except HTTPException:
        raise
    except ValueError as ve:
        # Handle user validation errors with clear message
        error_msg = str(ve)
        logger.error(f"⚠️ Validation error creating session: {error_msg}")
        if "User not found" in error_msg or "log in again" in error_msg:
            raise HTTPException(
                status_code=401, 
                detail="Your session has expired. Please log out and log back in to continue."
            )
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        logger.error(f"❌ Error creating session: {e}")
        error_detail = str(e)
        # Check if it's a foreign key constraint error (backup check)
        if "foreign key constraint" in error_detail.lower() or "fk_user" in error_detail.lower():
            raise HTTPException(
                status_code=401,
                detail="Your session has expired. Please log out and log back in to continue."
            )
        raise HTTPException(status_code=500, detail=f"Internal server error: {error_detail}")

@app.get("/sessions/{session_id}", response_model=ChatSessionModel)
async def get_session(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Get chat session by ID"""
    try:
        session = await chat_service.get_chat_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/users/{user_id}/sessions", response_model=list[ChatSessionModel])
async def get_user_sessions(
    user_id: str,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Get all sessions for a user"""
    try:
        sessions = await chat_service.get_user_sessions(user_id)
        return sessions
        
    except Exception as e:
        logger.error(f"Error getting user sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/sessions/{session_id}/history")
async def get_chat_history(
    session_id: str,
    limit: int = 50,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Get chat history for session"""
    try:
        history = await chat_service.get_chat_history(session_id, limit)
        return {"history": history}
        
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Delete chat session"""
    try:
        success = await chat_service.delete_session(session_id)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"message": "Session deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Memory management endpoints
@app.get("/memory/stats/{session_id}")
async def get_memory_stats(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Get memory statistics for a session"""
    try:
        stats = await chat_service.get_memory_stats(session_id)
        return stats
    except Exception as e:
        logger.error(f"Error getting memory stats: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/memory/entities/{session_id}")
async def get_session_entities(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Get extracted entities for a session"""
    try:
        entities = await chat_service.get_session_entities(session_id)
        return entities
    except Exception as e:
        logger.error(f"Error getting session entities: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/memory/summary/{session_id}")
async def get_session_summary(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Get conversation summary for a session"""
    try:
        summary = await chat_service.get_session_summary(session_id)
        return summary
    except Exception as e:
        logger.error(f"Error getting session summary: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.delete("/memory/clear/{session_id}")
async def clear_session_memory(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Clear memory for a specific session"""
    try:
        success = await chat_service.clear_session_memory(session_id)
        if success:
            return {"message": "Session memory cleared successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to clear session memory")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error clearing session memory: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/memory/cleanup")
async def cleanup_expired_memories(
    chat_service: ChatService = Depends(get_chat_service)
):
    """Clean up expired memories across all sessions"""
    try:
        result = await chat_service.cleanup_expired_memories()
        return result
    except Exception as e:
        logger.error(f"Error cleaning up expired memories: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # Disable reload to prevent constant restarts
        log_level="info"
    )