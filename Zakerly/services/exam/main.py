from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import sys
from datetime import datetime
import logging
from contextlib import asynccontextmanager

# Add shared modules to path
sys.path.append('/app/shared')

from models import (
    QuestionGenerationRequest, QuestionResponse, HealthCheck
)
from database import get_database, DatabaseManager
from utils import setup_logging, get_redis
from exam_service import ExamService

# Setup logging
setup_logging("exam-service")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting Exam Service...")
    
    # Initialize database
    db = get_database()
    await db.initialize()
    
    # Initialize Redis
    redis_manager = get_redis()
    
    # Initialize exam service
    app.state.exam_service = ExamService(db, redis_manager)
    
    logger.info("Exam Service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Exam Service...")
    await db.close()
    redis_manager.disconnect()

app = FastAPI(
    title="Zakerly Exam Service",
    description="Intelligent exam and question generation service for Zakerly platform",
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

def get_exam_service() -> ExamService:
    """Dependency to get exam service"""
    return app.state.exam_service

@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint"""
    return HealthCheck(
        status="healthy",
        timestamp=datetime.utcnow(),
        service="exam-service",
        version="1.0.0"
    )

@app.post("/generate-questions", response_model=QuestionResponse)
async def generate_questions(
    request: QuestionGenerationRequest,
    exam_service: ExamService = Depends(get_exam_service)
):
    """Generate questions for a book"""
    try:
        logger.info(f"Question generation request for curriculum: {request.curriculum}, book: {request.book_title}")
        
        response = await exam_service.generate_questions(request)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating questions: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Additional exam-related endpoints can be added here
@app.get("/exams/{exam_id}")
async def get_exam(exam_id: str):
    """Get exam by ID - placeholder for future functionality"""
    return {"message": "Exam retrieval functionality coming soon"}

@app.post("/exams")
async def create_exam():
    """Create new exam - placeholder for future functionality"""
    return {"message": "Exam creation functionality coming soon"}

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )