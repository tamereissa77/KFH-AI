import logging
from typing import List, Optional, Dict, Any
import asyncio
from datetime import datetime
import json
import uuid
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.embeddings import OllamaEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.vectorstores.pgvector import PGVector
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

import sys
sys.path.append('/app/shared')

from models import BookModel, BookMetadata, CurriculumModel, CurriculumCreateRequest
from database import DatabaseManager
from utils import calculate_file_hash, sanitize_title_for_table, RedisManager, validate_file_type
import tempfile
import os
import io

logger = logging.getLogger(__name__)

class IngestionService:
    def __init__(self, db_manager: DatabaseManager, redis_manager: RedisManager):
        self.db = db_manager
        self.redis = redis_manager
        
        # Initialize LangChain components
        self.embeddings = OllamaEmbeddings(
            model=os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:latest"),
            base_url=os.getenv("OLLAMA_BASE_URL")
        )
        
        self.llm = ChatGoogleGenerativeAI(
            model=os.getenv("INGESTION_MODEL_NAME", "gemini-1.5-flash"),
            temperature=float(os.getenv("INGESTION_MODEL_TEMPERATURE", "0")),
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
        
        # Metadata extraction prompt
        self.metadata_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert document analysis and metadata extraction AI. Your sole function is to analyze the provided text and metadata to create a complete, structured JSON record.

Your response MUST be a single, clean JSON object with the following keys: `title`, `author`, `publication_year`, `file_hash`, `file_name`.

**INSTRUCTIONS:**

1. **Analyze Text Content:**
   - **Extract** the `title`, `author`, and `publication_year`. If any cannot be found, their value MUST be `null`.
   - Focus ONLY on metadata extraction, NOT subject classification.

2. **Format the `title` for Database Use:**
   - Convert the entire title to UPPERCASE.
   - Replace all spaces with a single underscore (`_`).
   - Remove any characters that are NOT uppercase letters (A-Z), numbers (0-9), or underscores (`_`).

3. **Copy from Provided Metadata:**
   - Copy the `file_hash` and `file_name` values directly.

Respond with ONLY the JSON object, no additional text."""),
            ("human", "Text Content: {text}\n\nFile Hash: {file_hash}\nFile Name: {file_name}\nCurriculum ID: {curriculum_id}\nCurriculum Name: {curriculum_name}")
        ])

    async def process_book(self, content: bytes, filename: str, mime_type: str, curriculum_id: int = None, curriculum_name: str = None) -> BookModel:
        """Process uploaded book file"""
        try:
            # Validate curriculum requirement
            if not curriculum_id and not curriculum_name:
                raise ValueError("Either curriculum_id or curriculum_name must be provided")
            
            # Handle curriculum creation/validation
            if curriculum_name and not curriculum_id:
                # Create new curriculum or get existing one
                existing_curriculum = await self.db.get_curriculum_by_name(curriculum_name)
                if existing_curriculum:
                    curriculum_id = existing_curriculum['id']
                else:
                    curriculum_id = await self.db.create_curriculum(curriculum_name, f"Custom curriculum: {curriculum_name}")
            elif curriculum_id:
                # Validate existing curriculum
                curriculum = await self.db.get_curriculum_by_id(curriculum_id)
                if not curriculum:
                    raise ValueError(f"Curriculum with ID {curriculum_id} does not exist")
                curriculum_name = curriculum['name']
            
            # Validate file type
            if not validate_file_type(mime_type):
                raise ValueError(f"Unsupported file type: {mime_type}")
            
            # Calculate file hash
            file_hash = calculate_file_hash(content)
            
            # Check if book already exists
            if await self.db.check_book_exists(file_hash):
                raise ValueError("Book already exists in the system")
            
            # Extract text from file
            text_content = await self._extract_text(content, filename, mime_type)
            
            # Extract metadata using LLM (no more auto-categorization)
            metadata = await self._extract_metadata(text_content, file_hash, filename, curriculum_id, curriculum_name)
            
            # Insert book into database first - this is the critical operation
            book_id = await self.db.insert_book({
                'curriculum_id': metadata.curriculum_id,
                'title': metadata.title,
                'author': metadata.author,
                'publication_year': metadata.publication_year,
                'file_hash': metadata.file_hash,
                'file_name': metadata.file_name
            })
            
            # Create book model - book is successfully saved at this point
            book = BookModel(
                id=book_id,
                curriculum_id=metadata.curriculum_id,
                title=metadata.title,
                author=metadata.author,
                publication_year=metadata.publication_year,
                file_hash=metadata.file_hash,
                file_name=metadata.file_name,
                created_at=datetime.utcnow()
            )
            
            # Try to create curriculum-based vector store - if this fails, we still return success
            try:
                await self._create_curriculum_vector_store(text_content, curriculum_name, curriculum_id, book_id)
                logger.info(f"Successfully created curriculum vector store for: {metadata.title} in curriculum: {curriculum_name}")
            except Exception as vector_error:
                logger.error(f"Failed to create curriculum vector store for {metadata.title}: {vector_error}")
                logger.warning(f"Book {metadata.title} was saved to database but curriculum vector store creation failed")
                # Don't raise the error - the book is still successfully added
            
            # Try to cache the book data - if this fails, we still return success
            try:
                await self._cache_book(book)
            except Exception as cache_error:
                logger.warning(f"Failed to cache book data for {metadata.title}: {cache_error}")
            
            logger.info(f"Successfully processed book: {metadata.title}")
            return book
            
        except Exception as e:
            logger.error(f"Error processing book: {e}")
            raise

    async def _extract_text(self, content: bytes, filename: str, mime_type: str) -> str:
        """Extract text from file content"""
        try:
            if mime_type == "application/pdf":
                # Create temporary file for PDF processing
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                    temp_file.write(content)
                    temp_file.flush()
                    
                    # Use PyPDFLoader
                    loader = PyPDFLoader(temp_file.name)
                    documents = loader.load()
                    
                    # Clean up temp file
                    os.unlink(temp_file.name)
                    
                    # Combine all pages
                    text = "\n".join([doc.page_content for doc in documents])
                    
            elif mime_type == "text/plain":
                text = content.decode('utf-8', errors='replace')
                
            else:
                # For other formats, try to decode as text
                text = content.decode('utf-8', errors='replace')
            
            # Clean the text to remove null bytes and other problematic characters
            text = self._clean_text_for_database(text)
            
            # Return full text for processing, but log length
            logger.info(f"Extracted text length: {len(text)} characters")
            return text
            
        except Exception as e:
            logger.error(f"Error extracting text from {filename}: {e}")
            raise ValueError(f"Failed to extract text from file: {e}")

    def _clean_text_for_database(self, text: str) -> str:
        """Clean text to remove characters that cause database encoding issues"""
        # Remove null bytes and other control characters that cause UTF-8 issues
        text = text.replace('\x00', '')  # Remove null bytes
        text = text.replace('\ufffd', '')  # Remove replacement characters
        
        # Remove other problematic control characters (except common ones like \n, \t, \r)
        import re
        # Keep only printable characters, newlines, tabs, and carriage returns
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text

    async def _extract_metadata(self, text: str, file_hash: str, filename: str, curriculum_id: int, curriculum_name: str) -> BookMetadata:
        """Extract metadata using LLM"""
        result = ""
        try:
            # Create chain
            chain = self.metadata_prompt | self.llm | StrOutputParser()
            
            # Run extraction with limited text for LLM
            text_for_llm = text[:8000] if len(text) > 8000 else text
            result = await chain.ainvoke({
                "text": text_for_llm,
                "file_hash": file_hash,
                "file_name": filename,
                "curriculum_id": curriculum_id,
                "curriculum_name": curriculum_name
            })
            
            # Clean and validate the result
            result = result.strip()
            if not result:
                logger.warning("Empty response from LLM, using fallback metadata")
                raise ValueError("Empty response from LLM")
            
            # Try to extract JSON from the response if it contains extra text
            if result.startswith('```json'):
                result = result.replace('```json', '').replace('```', '').strip()
            elif result.startswith('```'):
                result = result.replace('```', '').strip()
            
            # Find JSON object in the response
            start_idx = result.find('{')
            end_idx = result.rfind('}')
            if start_idx != -1 and end_idx != -1:
                result = result[start_idx:end_idx+1]
            else:
                logger.warning("No valid JSON found in LLM response, using fallback metadata")
                raise ValueError("No valid JSON found in response")
            
            # Parse JSON response
            try:
                metadata_dict = json.loads(result)
            except json.JSONDecodeError as json_error:
                logger.warning(f"JSON decode error: {json_error}, using fallback metadata")
                raise ValueError(f"Invalid JSON: {json_error}")
            
            # Validate required fields (no longer require subject or category_id)
            required_fields = ['title', 'file_hash', 'file_name']
            for field in required_fields:
                if field not in metadata_dict:
                    logger.warning(f"Missing required field: {field}, using fallback metadata")
                    raise ValueError(f"Missing required field: {field}")
            
            # Clean up "NULL" strings and convert to None
            def clean_null_value(value):
                """Clean null-like values from LLM responses"""
                if value is None:
                    return None
                if isinstance(value, str):
                    # Handle common null-like strings from LLM
                    cleaned = value.strip().upper()
                    if cleaned in ['NULL', 'NONE', '', 'N/A', 'NOT PROVIDED', 'UNKNOWN']:
                        return None
                return value
            
            # Extract and clean values
            title = clean_null_value(metadata_dict.get('title'))
            author = clean_null_value(metadata_dict.get('author'))
            publication_year = clean_null_value(metadata_dict.get('publication_year'))
            
            # Convert publication_year to int if it's a valid string
            if publication_year is not None:
                try:
                    # Handle string numbers or direct integers
                    if isinstance(publication_year, str):
                        publication_year = publication_year.strip()
                        if not publication_year:
                            publication_year = None
                        else:
                            publication_year = int(publication_year)
                    elif not isinstance(publication_year, int):
                        publication_year = int(publication_year)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid publication_year value: {publication_year} (type: {type(publication_year)}), error: {e}, setting to None")
                    publication_year = None
            
            # Use filename as title if title is null/empty
            if not title or title.upper() in ['NULL', 'NONE']:
                title = sanitize_title_for_table(filename.split('.')[0])
            
            # Create BookMetadata object with curriculum information
            metadata = BookMetadata(
                curriculum_id=curriculum_id,
                curriculum_name=curriculum_name,
                title=title,
                author=author,
                publication_year=publication_year,
                file_hash=metadata_dict['file_hash'],
                file_name=metadata_dict['file_name']
            )
            
            logger.info(f"Successfully extracted metadata for: {metadata.title}")
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting metadata: {e}")
            logger.error(f"LLM response was: {result if result else 'No response'}")
            
            # Fallback to basic metadata
            fallback_metadata = BookMetadata(
                curriculum_id=curriculum_id,
                curriculum_name=curriculum_name,
                title=sanitize_title_for_table(filename.split('.')[0]),
                author=None,
                publication_year=None,
                file_hash=file_hash,
                file_name=filename
            )
            
            logger.info(f"Using fallback metadata: {fallback_metadata.title}")
            return fallback_metadata

    async def _create_curriculum_vector_store(self, text: str, curriculum_name: str, curriculum_id: int, book_id: int):
        """Create curriculum-based vector store for the book"""
        try:
            # Split text into chunks
            documents = self.text_splitter.create_documents([text])
            
            # Create embeddings for all documents
            texts = [doc.page_content for doc in documents]
            embeddings_list = await self.embeddings.aembed_documents(texts)
            
            if not embeddings_list:
                raise ValueError("No embeddings generated")
            
            logger.info(f"Generated {len(embeddings_list)} embeddings for curriculum: {curriculum_name}")
            
            # Insert embeddings into curriculum-specific table
            for i, (doc, embedding) in enumerate(zip(documents, embeddings_list)):
                try:
                    # Clean the document content before inserting
                    clean_content = self._clean_text_for_database(doc.page_content)
                    
                    # Insert into curriculum embedding table
                    await self.db.insert_curriculum_embedding(
                        curriculum_name=curriculum_name,
                        curriculum_id=curriculum_id,
                        book_id=book_id,
                        content=clean_content,
                        embedding=embedding,
                        metadata=doc.metadata
                    )
                    
                except Exception as insert_error:
                    logger.error(f"Error inserting embedding chunk {i} for curriculum {curriculum_name}: {insert_error}")
                    raise
            
            logger.info(f"Successfully created curriculum vector store for {curriculum_name} with {len(documents)} chunks")
            
        except Exception as e:
            logger.error(f"Error creating curriculum vector store for {curriculum_name}: {e}")
            raise

    async def _cache_book(self, book: BookModel):
        """Cache book data in Redis"""
        try:
            cache_key = f"book:{book.id}"
            book_data = book.dict()
            book_data['created_at'] = book_data['created_at'].isoformat() if book_data['created_at'] else None
            
            self.redis.set_cache(cache_key, book_data, expire_seconds=3600)
            
        except Exception as e:
            logger.warning(f"Failed to cache book data: {e}")

    async def list_books(self, curriculum_id: int = None) -> List[BookModel]:
        """List books, optionally filtered by curriculum"""
        try:
            if curriculum_id:
                books_data = await self.db.get_books_by_curriculum(curriculum_id)
            else:
                books_data = await self.db.get_all_books()
            
            books = []
            for book_data in books_data:
                book = BookModel(**book_data)
                books.append(book)
            
            return books
            
        except Exception as e:
            logger.error(f"Error listing books: {e}")
            raise
    
    async def list_curriculums(self) -> List[CurriculumModel]:
        """List all curriculums"""
        try:
            curriculums_data = await self.db.get_curriculums()
            curriculums = [CurriculumModel(**curr_data) for curr_data in curriculums_data]
            return curriculums
            
        except Exception as e:
            logger.error(f"Error listing curriculums: {e}")
            raise
    
    async def create_curriculum(self, curriculum_request) -> CurriculumModel:
        """Create new curriculum"""
        logger.info(f"🔧 DEBUG: create_curriculum called with created_by: '{curriculum_request.created_by}'")
        try:
            # Validate and fix the created_by field FIRST, before any database operations
            user_id = self._validate_and_fix_user_id(curriculum_request.created_by)
            logger.info(f"Creating curriculum with user_id: {user_id}")
            
            curriculum_id = await self.db.create_curriculum(
                curriculum_request.name, 
                curriculum_request.description, 
                user_id  # Use the validated UUID
            )
            curriculum_data = await self.db.get_curriculum_by_id(curriculum_id)
            return CurriculumModel(**curriculum_data)
            
        except Exception as e:
            logger.error(f"Error creating curriculum: {e}")
            raise
    
    def _validate_and_fix_user_id(self, user_id: str) -> str:
        """Validate and fix user_id to ensure it's a valid UUID"""
        logger.info(f"Validating user_id: '{user_id}' (type: {type(user_id)})")
        try:
            # Check if it's already a valid UUID
            uuid.UUID(user_id)
            logger.info(f"✅ Valid UUID: {user_id}")
            return user_id
        except ValueError as e:
            # If not a valid UUID, generate a new one
            new_uuid = str(uuid.uuid4())
            logger.warning(f"⚠️ Invalid UUID '{user_id}' (error: {e}), generated new UUID: {new_uuid}")
            return new_uuid
    
    async def get_curriculum_by_id(self, curriculum_id: int) -> Optional[CurriculumModel]:
        """Get curriculum by ID"""
        try:
            curriculum_data = await self.db.get_curriculum_by_id(curriculum_id)
            if curriculum_data:
                return CurriculumModel(**curriculum_data)
            return None
            
        except Exception as e:
            logger.error(f"Error getting curriculum: {e}")
            raise

    async def get_book_by_id(self, book_id: int) -> Optional[BookModel]:
        """Get book by ID"""
        try:
            # Try cache first
            cache_key = f"book:{book_id}"
            cached_data = self.redis.get_cache(cache_key)
            
            if cached_data:
                if cached_data.get('created_at'):
                    cached_data['created_at'] = datetime.fromisoformat(cached_data['created_at'])
                return BookModel(**cached_data)
            
            # Get from database
            book_data = await self.db.fetch_one(
                "SELECT * FROM books WHERE id = $1", book_id
            )
            
            if book_data:
                book = BookModel(**book_data)
                await self._cache_book(book)
                return book
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting book {book_id}: {e}")
            raise

    async def get_book_by_hash(self, file_hash: str) -> Optional[BookModel]:
        """Fetch book by file hash if already exists"""
        book_data = await self.db.fetch_one("SELECT * FROM books WHERE file_hash = $1", file_hash)
        if book_data:
            return BookModel(**book_data)
        return None

    async def delete_book(self, book_id: int) -> bool:
        """Delete book and its vector store"""
        try:
            # Get book info first
            book = await self.get_book_by_id(book_id)
            if not book:
                return False
            
            # Delete from vector store (drop table)
            try:
                # Drop the table with the book title name
                await self.db.execute_command(f"DROP TABLE IF EXISTS {book.title}")
            except Exception as e:
                logger.warning(f"Failed to drop vector table for {book.title}: {e}")
            
            # Delete from books table
            result = await self.db.execute_command(
                "DELETE FROM books WHERE id = $1", book_id
            )
            
            # Remove from cache
            cache_key = f"book:{book_id}"
            self.redis.delete_cache(cache_key)
            
            return "DELETE 1" in result
            
        except Exception as e:
            logger.error(f"Error deleting book {book_id}: {e}")
            raise

    async def update_curriculum(self, curriculum_id: int, curriculum_request) -> Optional[CurriculumModel]:
        """Update curriculum by ID"""
        try:
            success = await self.db.update_curriculum(
                curriculum_id,
                curriculum_request.name,
                curriculum_request.description,
                curriculum_request.created_by
            )
            if success:
                curriculum_data = await self.db.get_curriculum_by_id(curriculum_id)
                return CurriculumModel(**curriculum_data)
            return None
            
        except Exception as e:
            logger.error(f"Error updating curriculum {curriculum_id}: {e}")
            raise

    async def delete_curriculum(self, curriculum_id: int) -> bool:
        """Delete curriculum by ID"""
        try:
            # Get curriculum info first
            curriculum = await self.get_curriculum_by_id(curriculum_id)
            if not curriculum:
                return False
            
            # Delete curriculum embedding table
            embedding_table = f"curriculum_embeddings_{curriculum.name.lower().replace(' ', '_')}"
            try:
                await self.db.execute_command(f"DROP TABLE IF EXISTS {embedding_table}")
            except Exception as e:
                logger.warning(f"Failed to drop curriculum embedding table {embedding_table}: {e}")
            
            # Delete from curriculum table (this will cascade to books)
            result = await self.db.execute_command(
                "DELETE FROM curriculum WHERE id = $1", curriculum_id
            )
            
            return "DELETE 1" in result
            
        except Exception as e:
            logger.error(f"Error deleting curriculum {curriculum_id}: {e}")
            raise

    async def list_books_by_curriculum(self, curriculum_id: int) -> List[BookModel]:
        """List books in a specific curriculum"""
        try:
            books_data = await self.db.fetch_all(
                "SELECT * FROM books WHERE curriculum_id = $1 ORDER BY created_at DESC",
                curriculum_id
            )
            return [BookModel(**book) for book in books_data]
            
        except Exception as e:
            logger.error(f"Error listing books for curriculum {curriculum_id}: {e}")
            raise