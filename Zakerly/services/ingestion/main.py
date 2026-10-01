from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import sys
from datetime import datetime
import logging
from contextlib import asynccontextmanager

# Add shared modules to path
sys.path.append('/app/shared')

from models import BookModel, BookMetadata, HealthCheck, CurriculumModel, CurriculumCreateRequest
from database import get_database, DatabaseManager
from utils import setup_logging, get_redis
from ingestion_service import IngestionService

# Setup logging
setup_logging("ingestion-service")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting Ingestion Service...")
    
    # Initialize database
    db = get_database()
    await db.initialize()
    
    # Initialize Redis
    redis_manager = get_redis()
    
    # Initialize ingestion service
    app.state.ingestion_service = IngestionService(db, redis_manager)
    
    logger.info("Ingestion Service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Ingestion Service...")
    await db.close()
    redis_manager.disconnect()

app = FastAPI(
    title="Zakerly Ingestion Service",
    description="Document ingestion and processing service for Zakerly platform",
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

def get_ingestion_service() -> IngestionService:
    """Dependency to get ingestion service"""
    return app.state.ingestion_service

@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint"""
    return HealthCheck(
        status="healthy",
        timestamp=datetime.utcnow(),
        service="ingestion-service",
        version="1.0.0"
    )

@app.post("/upload", response_model=BookModel)
async def upload_book(
    curriculum_id: int,
    file: UploadFile = File(...),
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Upload and process a book file for a specific curriculum"""
    logger.info(f"Received file upload: {file.filename} for curriculum {curriculum_id}")
    
    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    # Read file content
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    
    try:
        # Process the book with curriculum
        book = await ingestion_service.process_book(
            content=content,
            filename=file.filename,
            mime_type=file.content_type or "application/octet-stream",
            curriculum_id=curriculum_id
        )
        logger.info(f"Successfully processed book: {book.title} for curriculum {curriculum_id}")
        return book

    except ValueError as e:
        error_msg = str(e)
        logger.info(f"Caught ValueError: {error_msg}")  # Debug log

        if "already exists" in error_msg.lower():
            logger.warning(f"Duplicate book upload attempt: {file.filename}")
            # Try to fetch and return the existing book instead of raising error
            from utils import calculate_file_hash
            file.file.seek(0)
            content_for_hash = await file.read()
            file_hash = calculate_file_hash(content_for_hash)
            existing_book = await ingestion_service.get_book_by_hash(file_hash)
            if existing_book:
                logger.info(f"Returning existing book for duplicate upload: {existing_book.title}")
                return existing_book
            raise HTTPException(
                status_code=409, 
                detail="This book already exists in the system. Please check your library before uploading."
            )
        elif "unsupported file type" in error_msg.lower():
            logger.warning(f"Unsupported file type for: {file.filename}")
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Please upload PDF, TXT, DOC, or DOCX files."
            )
        else:
            logger.error(f"ValueError processing book upload: {e}")
            # Try to fetch and return the book if it exists in DB
            from utils import calculate_file_hash
            file.file.seek(0)
            content_for_hash = await file.read()
            file_hash = calculate_file_hash(content_for_hash)
            existing_book = await ingestion_service.get_book_by_hash(file_hash)
            if existing_book:
                logger.info(f"Returning existing book after error: {existing_book.title}")
                return existing_book
            raise HTTPException(status_code=400, detail=error_msg)

    except Exception as e:
        logger.error(f"Unexpected error processing book upload (type: {type(e).__name__}): {e}")
        # Try to fetch and return the book if it exists in DB
        from utils import calculate_file_hash
        file.file.seek(0)
        content_for_hash = await file.read()
        file_hash = calculate_file_hash(content_for_hash)
        existing_book = await ingestion_service.get_book_by_hash(file_hash)
        if existing_book:
            logger.info(f"Returning existing book after unexpected error: {existing_book.title}")
            return existing_book
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Curriculum endpoints
@app.post("/curriculums", response_model=CurriculumModel)
async def create_curriculum(
    curriculum: CurriculumCreateRequest,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Create a new curriculum"""
    try:
        new_curriculum = await ingestion_service.create_curriculum(curriculum)
        logger.info(f"Successfully created curriculum: {new_curriculum.name}")
        return new_curriculum
    except ValueError as e:
        logger.warning(f"Invalid curriculum data: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating curriculum: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/curriculums", response_model=list[CurriculumModel])
async def list_curriculums(
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """List all curriculums"""
    try:
        curriculums = await ingestion_service.list_curriculums()
        return curriculums
    except Exception as e:
        logger.error(f"Error listing curriculums: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/curriculums/{curriculum_id}", response_model=CurriculumModel)
async def get_curriculum(
    curriculum_id: int,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Get curriculum by ID"""
    try:
        curriculum = await ingestion_service.get_curriculum_by_id(curriculum_id)
        if not curriculum:
            raise HTTPException(status_code=404, detail="Curriculum not found")
        return curriculum
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting curriculum {curriculum_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.put("/curriculums/{curriculum_id}", response_model=CurriculumModel)
async def update_curriculum(
    curriculum_id: int,
    curriculum: CurriculumCreateRequest,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Update curriculum by ID"""
    try:
        updated_curriculum = await ingestion_service.update_curriculum(curriculum_id, curriculum)
        if not updated_curriculum:
            raise HTTPException(status_code=404, detail="Curriculum not found")
        logger.info(f"Successfully updated curriculum: {updated_curriculum.name}")
        return updated_curriculum
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Invalid curriculum update data: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating curriculum {curriculum_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.delete("/curriculums/{curriculum_id}")
async def delete_curriculum(
    curriculum_id: int,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Delete curriculum by ID"""
    try:
        success = await ingestion_service.delete_curriculum(curriculum_id)
        if not success:
            raise HTTPException(status_code=404, detail="Curriculum not found")
        return {"message": "Curriculum deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting curriculum {curriculum_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/curriculums/{curriculum_id}/books", response_model=list[BookModel])
async def list_curriculum_books(
    curriculum_id: int,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """List all books in a curriculum"""
    try:
        books = await ingestion_service.list_books_by_curriculum(curriculum_id)
        return books
    except Exception as e:
        logger.error(f"Error listing books for curriculum {curriculum_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/books", response_model=list[BookModel])
async def list_books(
    curriculum_id: int = None,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """List all books or books by curriculum"""
    try:
        if curriculum_id:
            books = await ingestion_service.list_books_by_curriculum(curriculum_id)
        else:
            books = await ingestion_service.list_books()
        return books
    except Exception as e:
        logger.error(f"Error listing books: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/books/{book_id}", response_model=BookModel)
async def get_book(
    book_id: int,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Get book by ID"""
    try:
        book = await ingestion_service.get_book_by_id(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        return book
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting book {book_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.delete("/books/{book_id}")
async def delete_book(
    book_id: int,
    ingestion_service: IngestionService = Depends(get_ingestion_service)
):
    """Delete book by ID"""
    try:
        success = await ingestion_service.delete_book(book_id)
        if not success:
            raise HTTPException(status_code=404, detail="Book not found")
        return {"message": "Book deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting book {book_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )