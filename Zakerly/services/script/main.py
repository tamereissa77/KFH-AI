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
    LectureRequest, LectureScript, LectureScriptRequest, LectureScriptUpdate,
    CurriculumScriptRequest, HealthCheck
)
from database import get_database, DatabaseManager
from utils import setup_logging, get_redis
from memory import SimpleMemoryManager
from script_service import ScriptService

# Setup logging
setup_logging("script-service")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting Script Service...")
    
    # Initialize database
    db = get_database()
    await db.initialize()
    
    # Initialize memory manager
    memory_manager = SimpleMemoryManager(db)
    
    # Initialize script service
    app.state.script_service = ScriptService(db, memory_manager)
    
    logger.info("Script Service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Script Service...")
    await db.close()
    # Memory manager doesn't need explicit cleanup

app = FastAPI(
    title="Zakerly Script Service",
    description="Intelligent lecture and script generation service for Zakerly platform",
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

def get_script_service() -> ScriptService:
    """Dependency to get script service"""
    return app.state.script_service

@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint"""
    return HealthCheck(
        status="healthy",
        timestamp=datetime.utcnow(),
        service="script-service",
        version="1.0.0"
    )

@app.post("/generate-lecture")
async def generate_lecture(
    request: LectureRequest,
    script_service: ScriptService = Depends(get_script_service)
):
    """Generate lecture for a book topic"""
    try:
        logger.info(f"Lecture generation request for curriculum: {request.curriculum}")
        
        response = await script_service.generate_lecture(request)
        
        return {"lecture": response}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating lecture: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Lecture Scripts endpoints
@app.post("/scripts")
async def create_script(
    request: LectureScriptRequest,
    user_id: str,
    script_service: ScriptService = Depends(get_script_service)
):
    """Create a new lecture script"""
    try:
        script = await script_service.create_lecture_script(user_id, request)
        return script
    except ValueError as ve:
        # Handle user validation errors with clear message
        error_msg = str(ve)
        logger.error(f"⚠️ Validation error creating script: {error_msg}")
        if "User not found" in error_msg or "log in again" in error_msg:
            raise HTTPException(
                status_code=401, 
                detail="Your session has expired. Please log out and log back in to continue."
            )
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        logger.error(f"Error creating script: {e}")
        # Check if it's a foreign key constraint error (backup check)
        error_detail = str(e)
        if "foreign key constraint" in error_detail.lower() or "fk_lecture_script_user" in error_detail.lower():
            raise HTTPException(
                status_code=401,
                detail="Your session has expired. Please log out and log back in to continue."
            )
        raise HTTPException(status_code=500, detail=f"Internal server error: {error_detail}")

@app.get("/scripts/{script_id}")
async def get_script(
    script_id: str,
    user_id: str,
    script_service: ScriptService = Depends(get_script_service)
):
    """Get a specific lecture script by ID"""
    try:
        script = await script_service.get_lecture_script(script_id, user_id)
        if not script:
            raise HTTPException(status_code=404, detail="Script not found")
        return script
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting script {script_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/users/{user_id}/scripts")
async def get_user_scripts(
    user_id: str,
    script_service: ScriptService = Depends(get_script_service)
):
    """Get all lecture scripts for a user"""
    try:
        scripts = await script_service.get_user_scripts(user_id)
        return scripts
    except Exception as e:
        logger.error(f"Error getting user scripts: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.put("/scripts/{script_id}")
async def update_script(
    script_id: str,
    request: LectureScriptUpdate,
    user_id: str,
    script_service: ScriptService = Depends(get_script_service)
):
    """Update a lecture script"""
    try:
        script = await script_service.update_lecture_script(script_id, user_id, request)
        if not script:
            raise HTTPException(status_code=404, detail="Script not found")
        return script
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating script {script_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.delete("/scripts/{script_id}")
async def delete_script(
    script_id: str,
    user_id: str,
    script_service: ScriptService = Depends(get_script_service)
):
    """Delete a lecture script"""
    try:
        success = await script_service.delete_lecture_script(script_id, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Script not found")
        return {"message": "Script deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting script {script_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Enhanced Curriculum Script Generation endpoint
@app.post("/curriculum-scripts/generate")
async def generate_curriculum_script(
    request: CurriculumScriptRequest,
    user_id: str,
    script_service: ScriptService = Depends(get_script_service)
):
    """Generate script based on curriculum scope (whole_curriculum, whole_book, specific_topics)"""
    try:
        logger.info(f"Received curriculum script request: {request}")
        logger.info(f"User ID: {user_id}")
        
        # Validate request fields
        if not request.curriculum_id:
            raise HTTPException(status_code=422, detail="curriculum_id is required")
        if not request.title:
            raise HTTPException(status_code=422, detail="title is required")
        if not request.scope:
            raise HTTPException(status_code=422, detail="scope is required")
        if request.scope not in ['whole_curriculum', 'whole_book', 'specific_topics']:
            raise HTTPException(status_code=422, detail="scope must be one of: whole_curriculum, whole_book, specific_topics")
        
        # Convert request to dict for the service method
        request_dict = {
            'curriculum_id': request.curriculum_id,
            'title': request.title,
            'scope': request.scope,
            'specific_books': request.specific_books,
            'specific_topics': request.specific_topics,
            'detail_level': request.detail_level,
            'difficulty': request.difficulty,
            'duration': request.duration
        }
        
        logger.info(f"Processing curriculum script generation with: {request_dict}")
        
        script_content = await script_service.generate_curriculum_script(request_dict)
        
        return {
            "script_content": script_content,
            "title": request.title,
            "scope": request.scope,
            "curriculum_id": request.curriculum_id,
            "generated_at": datetime.now().isoformat()
        }
        
    except ValueError as e:
        logger.error(f"Validation error generating curriculum script: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating curriculum script: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )