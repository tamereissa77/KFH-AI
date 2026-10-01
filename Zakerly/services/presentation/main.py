from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import logging
import os
from datetime import datetime

from presentation_service import PresentationService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Presentation Service",
    description="Generate comprehensive curriculum presentations",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize service
presentation_service = None

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    global presentation_service
    try:
        presentation_service = PresentationService()
        logger.info("✅ Presentation Service initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Presentation Service: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    if presentation_service:
        await presentation_service.cleanup()
    logger.info("Presentation Service shutdown complete")

# Request Models
class PresentationGenerateRequest(BaseModel):
    curriculum_id: Optional[int] = None
    book_id: Optional[int] = None
    title: str = Field(..., description="Presentation title")
    scope: str = Field(..., description="Scope: whole_curriculum, whole_book, specific_topics")
    specific_topics: Optional[str] = Field(None, description="Comma-separated topics")
    detail_level: str = Field(default="detailed", description="Level: overview, detailed, comprehensive")
    difficulty: str = Field(default="intermediate", description="Difficulty: beginner, intermediate, advanced")
    slides_count: int = Field(default=15, ge=5, le=50, description="Number of slides")
    slide_style: str = Field(default="professional", description="Style: professional, creative, minimal")
    include_diagrams: bool = Field(default=True, description="Include diagram suggestions")
    include_code_examples: bool = Field(default=False, description="Include code examples")

class PresentationCreateRequest(BaseModel):
    book_id: Optional[int] = None
    title: str
    scope: str
    specific_topics: Optional[str] = None
    detail_level: str
    difficulty: str
    slides_count: int
    slide_style: str
    include_diagrams: bool
    include_code_examples: bool
    content: Dict[str, Any]

class PresentationUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[Dict[str, Any]] = None

# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "presentation-service",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/test-presentation")
async def test_presentation_fix():
    """Test the presentation fix"""
    try:
        # Test the fixed LLM call
        result = await presentation_service._generate_presentation_with_llm(
            title="Test Presentation",
            context_type="book",
            context_name="Test Book",
            topics=["Topic 1", "Topic 2"],
            content_chunks=[{"content": "Test content"}],
            books=["Test Book"],
            detail_level="detailed",
            difficulty="intermediate",
            slides_count=3,
            slide_style="professional",
            include_diagrams=True,
            include_code_examples=False
        )
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}

# Generate presentation
@app.post("/curriculum-presentations/generate")
async def generate_presentation(
    request: PresentationGenerateRequest,
    user_id: str = Query(..., description="User ID")
):
    """
    Generate a presentation based on curriculum, book, or specific topics
    
    - **CASE 1**: whole_curriculum - Generate comprehensive curriculum presentation
    - **CASE 2**: whole_book - Generate book-focused presentation
    - **CASE 3**: specific_topics - Generate topic-focused presentation
    """
    try:
        logger.info(f"Generating presentation for user {user_id}, scope: {request.scope}")
        
        result = await presentation_service.generate_curriculum_presentation(
            user_id=user_id,
            curriculum_id=request.curriculum_id,
            book_id=request.book_id,
            title=request.title,
            scope=request.scope,
            specific_topics=request.specific_topics,
            detail_level=request.detail_level,
            difficulty=request.difficulty,
            slides_count=request.slides_count,
            slide_style=request.slide_style,
            include_diagrams=request.include_diagrams,
            include_code_examples=request.include_code_examples
        )
        
        logger.info(f"✅ Presentation generated successfully with {result.get('total_slides', 0)} slides")
        return result
        
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating presentation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate presentation: {str(e)}")

# Create presentation (save to database)
@app.post("/presentations")
async def create_presentation(
    request: PresentationCreateRequest,
    user_id: str = Query(..., description="User ID")
):
    """Save a generated presentation to the database"""
    try:
        logger.info(f"Creating presentation for user {user_id}")
        
        result = await presentation_service.create_presentation(
            user_id=user_id,
            book_id=request.book_id,
            title=request.title,
            scope=request.scope,
            specific_topics=request.specific_topics,
            detail_level=request.detail_level,
            difficulty=request.difficulty,
            slides_count=request.slides_count,
            slide_style=request.slide_style,
            include_diagrams=request.include_diagrams,
            include_code_examples=request.include_code_examples,
            content=request.content
        )
        
        logger.info(f"✅ Presentation created with ID: {result.get('id')}")
        return result
        
    except ValueError as ve:
        # Handle user validation errors with clear message
        error_msg = str(ve)
        logger.error(f"⚠️ Validation error creating presentation: {error_msg}")
        if "User not found" in error_msg or "log in again" in error_msg:
            raise HTTPException(
                status_code=401, 
                detail="Your session has expired. Please log out and log back in to continue."
            )
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        logger.error(f"Error creating presentation: {e}")
        # Check if it's a foreign key constraint error (backup check)
        error_detail = str(e)
        if "foreign key constraint" in error_detail.lower() or "fk_presentation_user" in error_detail.lower():
            raise HTTPException(
                status_code=401,
                detail="Your session has expired. Please log out and log back in to continue."
            )
        raise HTTPException(status_code=500, detail=f"Failed to create presentation: {error_detail}")

# Get user presentations
@app.get("/users/{user_id}/presentations")
async def get_user_presentations(user_id: str):
    """Get all presentations for a specific user"""
    try:
        logger.info(f"Fetching presentations for user {user_id}")
        
        presentations = await presentation_service.get_user_presentations(user_id)
        
        logger.info(f"✅ Found {len(presentations)} presentations for user {user_id}")
        return {"presentations": presentations, "count": len(presentations)}
        
    except Exception as e:
        logger.error(f"Error fetching presentations: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch presentations: {str(e)}")

# Get presentation by ID
@app.get("/presentations/{presentation_id}")
async def get_presentation(
    presentation_id: str,
    user_id: str = Query(..., description="User ID")
):
    """Get a specific presentation by ID"""
    try:
        logger.info(f"Fetching presentation {presentation_id} for user {user_id}")
        
        presentation = await presentation_service.get_presentation(presentation_id, user_id)
        
        if not presentation:
            raise HTTPException(status_code=404, detail="Presentation not found")
        
        logger.info(f"✅ Presentation {presentation_id} found")
        return presentation
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching presentation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch presentation: {str(e)}")

# Update presentation
@app.put("/presentations/{presentation_id}")
async def update_presentation(
    presentation_id: str,
    request: PresentationUpdateRequest,
    user_id: str = Query(..., description="User ID")
):
    """Update a presentation"""
    try:
        logger.info(f"Updating presentation {presentation_id} for user {user_id}")
        
        result = await presentation_service.update_presentation(
            presentation_id=presentation_id,
            user_id=user_id,
            title=request.title,
            content=request.content
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Presentation not found")
        
        logger.info(f"✅ Presentation {presentation_id} updated")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating presentation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update presentation: {str(e)}")

# Delete presentation
@app.delete("/presentations/{presentation_id}")
async def delete_presentation(
    presentation_id: str,
    user_id: str = Query(..., description="User ID")
):
    """Delete a presentation"""
    try:
        logger.info(f"Deleting presentation {presentation_id} for user {user_id}")
        
        success = await presentation_service.delete_presentation(presentation_id, user_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Presentation not found")
        
        logger.info(f"✅ Presentation {presentation_id} deleted")
        return {"message": "Presentation deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting presentation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete presentation: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
