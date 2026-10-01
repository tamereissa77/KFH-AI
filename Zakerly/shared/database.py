import asyncpg
import asyncio
import os
import uuid
from typing import Optional, List, Dict, Any
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool: Optional[asyncpg.Pool] = None

    async def initialize(self):
        """Initialize database connection pool with improved settings"""
        try:
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=10,  # Increased minimum connections
                max_size=30,  # Increased maximum connections
                max_queries=50000,  # Maximum queries per connection
                max_inactive_connection_lifetime=300.0,  # 5 minutes
                command_timeout=60,
                timeout=10.0,  # Connection timeout
                init=self._init_connection  # Initialize each connection
            )
            logger.info("Database connection pool initialized with improved settings")
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise

    async def _init_connection(self, connection):
        """Initialize connection with proper settings"""
        await connection.execute('SET statement_timeout = 30000')  # 30 seconds
        await connection.execute('SET idle_in_transaction_session_timeout = 60000')  # 1 minute

    async def close(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")

    @asynccontextmanager  
    async def get_connection(self):
        """Get database connection from pool"""
        if not self.pool:
            await self.initialize()
        
        connection = await self.pool.acquire()
        try:
            yield connection
        finally:
            await self.pool.release(connection)

    async def execute_query(self, query: str, *args) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results"""
        async with self.get_connection() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    async def execute_command(self, command: str, *args) -> str:
        """Execute an INSERT/UPDATE/DELETE command"""
        async with self.get_connection() as conn:
            result = await conn.execute(command, *args)
            return result

    async def fetch_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """Fetch single row"""
        async with self.get_connection() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def fetch_val(self, query: str, *args) -> Any:
        """Fetch single value"""
        async with self.get_connection() as conn:
            return await conn.fetchval(query, *args)

    # Book-related methods
    async def get_curriculums(self) -> List[Dict[str, Any]]:
        """Get all curriculums"""
        query = "SELECT id, name, description, created_by, created_at, updated_at FROM curriculum ORDER BY name"
        return await self.execute_query(query)


    
    async def get_books_by_curriculum(self, curriculum_id: int) -> List[Dict[str, Any]]:
        """Get books by curriculum"""
        query = """
            SELECT 
                b.id,
                b.curriculum_id,
                b.title,
                b.author,
                b.publication_year,
                b.file_hash,
                b.file_name,
                b.created_at,
                cur.name as curriculum_name
            FROM books b
            JOIN curriculum cur ON b.curriculum_id = cur.id
            WHERE b.curriculum_id = $1
            ORDER BY b.title
        """
        return await self.execute_query(query, curriculum_id)
    
    async def get_all_books(self) -> List[Dict[str, Any]]:
        """Get all books with curriculum information"""
        query = """
            SELECT 
                b.id,
                b.curriculum_id,
                b.title,
                b.author,
                b.publication_year,
                b.file_hash,
                b.file_name,
                b.created_at,
                cur.name as curriculum_name
            FROM books b
            JOIN curriculum cur ON b.curriculum_id = cur.id
            ORDER BY b.created_at DESC
        """
        return await self.execute_query(query)

    async def get_book_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        """Get book by title with improved error handling"""
        max_retries = 3
        retry_delay = 1  # seconds
        
        query = """
            SELECT b.*, 
                   cur.name as curriculum_name
            FROM books b
            JOIN curriculum cur ON b.curriculum_id = cur.id
            WHERE b.title = $1
        """
        
        for attempt in range(max_retries):
            try:
                return await self.fetch_one(query, title)
            except asyncpg.exceptions.ConnectionDoesNotExistError:
                if attempt < max_retries - 1:
                    logger.warning(f"Connection lost while getting book info, retrying ({attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                    continue
                raise
            except Exception as e:
                logger.error(f"Error getting book by title '{title}': {e}")
                raise

    async def get_book_by_id(self, book_id: int) -> Optional[Dict[str, Any]]:
        """Get book by ID with curriculum information"""
        max_retries = 3
        retry_delay = 1  # seconds
        
        query = """
            SELECT b.*, 
                   cur.name as curriculum_name
            FROM books b
            JOIN curriculum cur ON b.curriculum_id = cur.id
            WHERE b.id = $1
        """
        
        for attempt in range(max_retries):
            try:
                return await self.fetch_one(query, book_id)
            except asyncpg.exceptions.ConnectionDoesNotExistError:
                if attempt < max_retries - 1:
                    logger.warning(f"Connection lost while getting book by ID, retrying ({attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                    continue
                raise
            except Exception as e:
                logger.error(f"Error getting book by ID '{book_id}': {e}")
                raise

    async def check_book_exists(self, file_hash: str) -> bool:
        """Check if book exists by file hash"""
        query = "SELECT COUNT(*) FROM books WHERE file_hash = $1"
        count = await self.fetch_val(query, file_hash)
        return count > 0

    async def insert_book(self, book_data: Dict[str, Any]) -> int:
        """Insert new book and return ID"""
        if 'curriculum_id' not in book_data or not book_data['curriculum_id']:
            raise ValueError("curriculum_id is required for new book uploads")
            
        query = """
            INSERT INTO books (curriculum_id, title, author, publication_year, file_hash, file_name)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """
        return await self.fetch_val(
            query,
            book_data['curriculum_id'],
            book_data['title'],
            book_data.get('author'),
            book_data.get('publication_year'),
            book_data['file_hash'],
            book_data['file_name']
        )

    # Chat session methods
    async def create_chat_session(self, user_id: str, book_id: int, session_name: str = None) -> str:
        """Create new chat session"""
        query = """
            INSERT INTO chat_sessions (user_id, book_id, session_name)
            VALUES ($1, $2, $3)
            RETURNING id
        """
        return await self.fetch_val(query, user_id, book_id, session_name)

    async def get_chat_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get chat session by ID"""
        query = """
            SELECT cs.*, b.title as book_title, cur.name as curriculum_name
            FROM chat_sessions cs
            JOIN books b ON cs.book_id = b.id
            JOIN curriculum cur ON b.curriculum_id = cur.id
            WHERE cs.id = $1
        """
        return await self.fetch_one(query, session_id)

    async def get_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all sessions for a user"""
        query = """
            SELECT cs.*, b.title as book_title, cur.name as curriculum_name
            FROM chat_sessions cs
            JOIN books b ON cs.book_id = b.id
            JOIN curriculum cur ON b.curriculum_id = cur.id
            WHERE cs.user_id = $1
            ORDER BY cs.updated_at DESC
        """
        return await self.execute_query(query, user_id)

    async def add_chat_message(self, session_id: str, message_type: str, content: str, metadata: Dict = None) -> int:
        """Add message to chat session"""
        query = """
            INSERT INTO chat_messages (session_id, message_type, content, metadata)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """
        return await self.fetch_val(query, session_id, message_type, content, metadata)

    async def get_chat_history(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get chat history for session"""
        query = """
            SELECT message_type, content, metadata, created_at
            FROM chat_messages
            WHERE session_id = $1
            ORDER BY created_at ASC
            LIMIT $2
        """
        return await self.execute_query(query, session_id, limit)

    async def update_session_timestamp(self, session_id: str):
        """Update session's last activity timestamp"""
        query = "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = $1"
        await self.execute_command(query, session_id)
    
    # Curriculum-related methods
    async def get_curriculum_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get curriculum by name"""
        query = "SELECT id, name, description, created_by, created_at, updated_at FROM curriculum WHERE name = $1"
        return await self.fetch_one(query, name)
    
    async def get_curriculum_by_id(self, curriculum_id: int) -> Optional[Dict[str, Any]]:
        """Get curriculum by ID"""
        query = "SELECT id, name, description, created_by, created_at, updated_at FROM curriculum WHERE id = $1"
        return await self.fetch_one(query, curriculum_id)
    
    async def create_curriculum(self, name: str, description: str = None, created_by: str = 'user') -> int:
        """Create new curriculum and return ID"""
        # Validate and fix created_by to ensure it's a valid UUID
        try:
            # Check if it's already a valid UUID
            uuid.UUID(created_by)
            logger.info(f"✅ Valid UUID: {created_by}")
        except ValueError as e:
            # If not a valid UUID, generate a new one
            created_by = str(uuid.uuid4())
            logger.warning(f"⚠️ Invalid UUID '{created_by}' converted to new UUID: {created_by}")
        
        query = """
            INSERT INTO curriculum (name, description, created_by)
            VALUES ($1, $2, $3)
            RETURNING id
        """
        curriculum_id = await self.fetch_val(query, name, description, created_by)
        
        # Create corresponding embedding table with correct dimension for nomic-embed-text
        await self.create_curriculum_embedding_table(name, embedding_dimension=768)
        
        return curriculum_id
    
    async def update_curriculum(self, curriculum_id: int, name: str = None, description: str = None) -> bool:
        """Update curriculum"""
        if name and description:
            query = """
                UPDATE curriculum 
                SET name = $1, description = $2, updated_at = CURRENT_TIMESTAMP
                WHERE id = $3
            """
            result = await self.execute_command(query, name, description, curriculum_id)
        elif name:
            query = """
                UPDATE curriculum 
                SET name = $1, updated_at = CURRENT_TIMESTAMP
                WHERE id = $2
            """
            result = await self.execute_command(query, name, curriculum_id)
        elif description:
            query = """
                UPDATE curriculum 
                SET description = $1, updated_at = CURRENT_TIMESTAMP
                WHERE id = $2
            """
            result = await self.execute_command(query, description, curriculum_id)
        else:
            return False
            
        return "UPDATE 1" in result
    
    async def delete_curriculum(self, curriculum_id: int) -> bool:
        """Delete curriculum and its embedding table"""
        # First get curriculum name to delete embedding table
        curriculum = await self.get_curriculum_by_id(curriculum_id)
        if not curriculum:
            return False
        
        # Delete embedding table
        await self.drop_curriculum_embedding_table(curriculum['name'])
        
        # Delete curriculum
        query = "DELETE FROM curriculum WHERE id = $1"
        result = await self.execute_command(query, curriculum_id)
        return "DELETE 1" in result
    
    async def create_curriculum_embedding_table(self, curriculum_name: str, embedding_dimension: int = 768):
        """Create embedding table for curriculum"""
        async with self.get_connection() as conn:
            table_name = await conn.fetchval(
                "SELECT create_curriculum_embedding_table($1, $2)",
                curriculum_name, embedding_dimension
            )
            return table_name
    
    async def drop_curriculum_embedding_table(self, curriculum_name: str):
        """Drop embedding table for curriculum"""
        async with self.get_connection() as conn:
            table_name = await conn.fetchval(
                "SELECT get_curriculum_embedding_table_name($1)",
                curriculum_name
            )
            await conn.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')
    
    async def get_curriculum_embedding_table_name(self, curriculum_name: str) -> str:
        """Get embedding table name for curriculum"""
        async with self.get_connection() as conn:
            return await conn.fetchval(
                "SELECT get_curriculum_embedding_table_name($1)",
                curriculum_name
            )
    
    async def insert_curriculum_embedding(self, curriculum_name: str, curriculum_id: int, book_id: int, content: str, embedding: List[float], metadata: dict = None):
        """Insert embedding into curriculum-specific table"""
        import json
        
        table_name = await self.get_curriculum_embedding_table_name(curriculum_name)
        
        # Convert embedding to PostgreSQL vector format
        embedding_str = '[' + ','.join(map(str, embedding)) + ']'
        
        # Convert metadata to JSON string
        metadata_json = json.dumps(metadata) if metadata else None
        
        async with self.get_connection() as conn:
            await conn.execute(f"""
                INSERT INTO "{table_name}" (curriculum_id, book_id, content, metadata, embedding)
                VALUES ($1, $2, $3, $4, $5::vector)
            """, curriculum_id, book_id, content, metadata_json, embedding_str)
    
    async def search_curriculum_embeddings(self, curriculum_name: str, query_embedding: List[float], limit: int = 6) -> List[Dict[str, Any]]:
        """Search embeddings in curriculum-specific table"""
        table_name = await self.get_curriculum_embedding_table_name(curriculum_name)
        
        # Convert embedding to PostgreSQL vector format
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        async with self.get_connection() as conn:
            # Check if table exists
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = $1
                )
            """, table_name)
            
            if not table_exists:
                logger.warning(f"Curriculum embedding table '{table_name}' does not exist")
                return []
            
            rows = await conn.fetch(f"""
                SELECT content, metadata, embedding <-> $1::vector as distance
                FROM "{table_name}"
                ORDER BY embedding <-> $1::vector
                LIMIT $2
            """, embedding_str, limit)
            
            return [{'content': row['content'], 'metadata': row['metadata'], 'distance': row['distance']} for row in rows]

    async def search_book_specific_embeddings(self, curriculum_name: str, book_id: int, query_embedding: List[float], limit: int = 6) -> List[Dict[str, Any]]:
        """Search embeddings for a specific book within curriculum"""
        table_name = await self.get_curriculum_embedding_table_name(curriculum_name)
        
        # Convert embedding to PostgreSQL vector format
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        async with self.get_connection() as conn:
            # Check if table exists
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = $1
                )
            """, table_name)
            
            if not table_exists:
                logger.warning(f"Curriculum embedding table '{table_name}' does not exist")
                return []
            
            # Search embeddings filtered by book_id
            rows = await conn.fetch(f"""
                SELECT content, metadata, embedding <-> $1::vector as distance
                FROM "{table_name}"
                WHERE book_id = $3
                ORDER BY embedding <-> $1::vector
                LIMIT $2
            """, embedding_str, limit, book_id)
            
            logger.info(f"Found {len(rows)} embeddings for book_id {book_id} in {table_name}")
            return [{'content': row['content'], 'metadata': row['metadata'], 'distance': row['distance']} for row in rows]



# Global database instance
db_manager: Optional[DatabaseManager] = None

def get_database() -> DatabaseManager:
    """Get database manager instance"""
    global db_manager
    if not db_manager:
        database_url = os.getenv("DATABASE_URL", "postgresql://zakerly_user:zakerly_password@localhost:5433/zakerly_db")
        db_manager = DatabaseManager(database_url)
    return db_manager