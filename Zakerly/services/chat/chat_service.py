import logging
from typing import List, Optional, Dict, Any, Tuple
import json
import os
import re
import asyncio
import asyncpg
from datetime import datetime
from contextlib import asynccontextmanager

from langchain_openai import ChatOpenAI
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores.pgvector import PGVector
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.tools import Tool, StructuredTool
from pydantic import BaseModel, Field
import httpx

# Import LangChain memory like in chat.py
from langchain.memory import ConversationBufferMemory
from langchain.schema.messages import HumanMessage, AIMessage

import sys
sys.path.append('/app/shared')

from models import (
    ChatRequest, ChatResponse, ChatSessionModel, ChatMessageModel, MessageType
)
from database import DatabaseManager
from utils import RedisManager
from memory import SimpleMemoryManager

logger = logging.getLogger(__name__)


def format_title(title: str) -> str:
    """Readable document title: stored titles are identifier-style (e.g. ACCOUNT_OPENING_PROCEDURE)"""
    text = title.replace('_', ' ').strip()
    return text.title() if text.isupper() else text

class SearchInput(BaseModel):
    """Input schema for knowledge base search tool"""
    query: str = Field(description="Search query to find relevant information in the knowledge base")

class ChatService:
    def __init__(self, db_manager: DatabaseManager, redis_manager: RedisManager):
        self.db = db_manager
        self.redis = redis_manager
        
        # Initialize LangChain components
        self.embeddings = OllamaEmbeddings(
            model=os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:latest"),
            base_url=os.getenv("OLLAMA_BASE_URL")
        )
        
        # Primary LLM (local vLLM, OpenAI-compatible) with proper configuration for agents
        llm_model = os.getenv("LLM_MODEL_NAME", "/models/gemma-4-26B-A4B-it")
        try:
            self.llm = ChatOpenAI(
                model=llm_model,
                base_url=os.getenv("LLM_BASE_URL", "http://host.docker.internal:8000/v1"),
                api_key=os.getenv("LLM_API_KEY", "EMPTY"),
                temperature=float(os.getenv("CHAT_MODEL_TEMPERATURE", "0.7")),
                top_p=0.8,
                max_tokens=2048
            )
        except Exception as llm_init_error:
            logger.warning(f"⚠️ Primary LLM initialization failed: {llm_init_error}")
            # Initialize with basic configuration as fallback
            self.llm = ChatOpenAI(
                model=llm_model,
                base_url=os.getenv("LLM_BASE_URL", "http://host.docker.internal:8000/v1"),
                api_key=os.getenv("LLM_API_KEY", "EMPTY"),
                temperature=0.7
            )
        
        self.connection_string = os.getenv("DATABASE_URL")
        
        # Initialize memory manager (keep for compatibility)
        from shared.memory import SimpleMemoryManager
        from shared.database import DatabaseManager
        db_manager = DatabaseManager(self.connection_string)
        self.memory_manager = SimpleMemoryManager(db_manager)
        
        # Initialize session-based memory storage like in chat.py
        self.chat_histories = {}
        
        # Initialize prompts
        self._setup_prompts()
    
    def get_current_llm(self):
        """Get the current LLM (Gemini only)"""
        return self.llm

    def _setup_prompts(self):
        """Setup all prompt templates"""
        
        # Router prompt for intent classification
        self.router_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a highly precise AI request parser. Your sole function is to analyze a user's message to determine their primary intent and then package the provided information into a structured JSON object.

Your response MUST be a single, clean JSON object with the following three keys: `intent`, `book_title`, and `user_message`.

**INTENT CLASSIFICATION:**
- `chat`: For normal conversational interactions, questions about content, explanations, discussions
- `generate_questions`: For explicit requests to create exam questions, quizzes, assessments, or tests
- `generate_lecture`: For explicit requests to create lecture content, presentations, or structured educational material

**IMPORTANT PARSING RULES:**
1. Only output valid JSON - no extra text, explanations, or formatting
2. Extract `book_title` from the context if mentioned, otherwise use null
3. Preserve the original `user_message` exactly as provided
4. Default to `chat` intent unless the user explicitly asks for question or lecture generation

**EXAMPLES:**
User: "Can you explain machine learning concepts?"
Response: {"intent": "chat", "book_title": null, "user_message": "Can you explain machine learning concepts?"}

User: "Generate 10 multiple choice questions about Python programming"
Response: {"intent": "generate_questions", "book_title": null, "user_message": "Generate 10 multiple choice questions about Python programming"}

User: "Create a lecture about data structures from the algorithms book"
Response: {"intent": "generate_lecture", "book_title": "algorithms book", "user_message": "Create a lecture about data structures from the algorithms book"}"""),
            ("human", "{user_message}")
        ])
        
        # Chat-focused prompt for curriculum-based conversations
        self.chat_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert AI tutor and educational assistant specializing in {curriculum_context}. Your primary role is to provide comprehensive, educational support through engaging conversations.

**YOUR CORE CAPABILITIES:**
🎓 **Educational Expertise**: Deep knowledge across all subjects in the curriculum
🔍 **Content Search**: Access to detailed curriculum materials and books through knowledge search tools
💬 **Interactive Learning**: Engaging in educational conversations, answering questions, and providing explanations
🧠 **Adaptive Teaching**: Adjusting explanations to match the student's level and learning style

**CONVERSATION GUIDELINES:**
1. **Use Knowledge Tools**: Always search for relevant information using available knowledge search tools before responding
2. **Educational Focus**: Provide comprehensive, well-structured educational responses
3. **Interactive Learning**: Encourage questions and deeper exploration of topics
4. **Cite Sources**: Reference specific curriculum materials or books when applicable
5. **Clear Explanations**: Break down complex concepts into understandable parts

**RESPONSE STRUCTURE:**
- Start with relevant knowledge search if needed
- Provide clear, educational responses
- Include examples and practical applications
- Encourage further questions or exploration

**KNOWLEDGE SEARCH INSTRUCTIONS:**
- Use knowledge search tools to find relevant content from curriculum books
- Search for specific topics, concepts, or chapters mentioned by the user
- Combine information from multiple sources when helpful

Remember: You're here to facilitate learning through conversation. Make education engaging, accessible, and comprehensive!"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{user_message}")
        ])
        
        # Strict RAG prompt for KFH staff: answer ONLY from retrieved internal documents
        self.simple_chat_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are the KFH internal knowledge assistant. Bank employees ask you about internal documents: policies, procedures, product terms, circulars and regulations.

RULES:
1. Answer ONLY from the numbered document excerpts you are given. Never use outside knowledge, assumptions or general banking knowledge.
2. Cite every factual statement with the excerpt number in square brackets, e.g. [1] or [2][3].
3. If the excerpts do not answer the question, say clearly that the documents provided do not cover it, and state what they do cover if relevant. Never guess.
4. Be precise and concise: lead with the direct answer, then the supporting details. Quote exact figures, limits, conditions and deadlines as written in the documents.
5. Use short bullet points for lists of conditions, steps or requirements.
6. Reply in the same language as the employee's question (Arabic or English)."""),
            ("human", "{user_message}")
        ])

    async def handle_chat(self, request: ChatRequest) -> ChatResponse:
        """Main chat handler for curriculum-based conversations"""
        try:
            logger.info(f"🎯 HANDLING CHAT REQUEST")
            logger.info(f"Session: {request.session_id}, Message: {request.user_message[:100]}...")
            
            # Get session information
            session = await self.get_chat_session(request.session_id)
            if not session:
                raise ValueError(f"Session {request.session_id} not found")
            
            # Save user message to history
            await self._save_message_to_history(
                request.session_id, 
                MessageType.USER, 
                request.user_message
            )
            
            # Determine knowledge base context
            curriculum_context = session.curriculum_name or session.book_title or "General"
            
            # Parse user intent using router
            try:
                logger.info("🔍 Parsing user intent...")
                router_chain = self.router_prompt | self.llm
                router_result = await router_chain.ainvoke({
                    "user_message": request.user_message
                })
                
                router_response = router_result.content if hasattr(router_result, 'content') else str(router_result)
                logger.debug(f"Router raw response: {router_response[:200]}")
                
                # Parse JSON response
                try:
                    intent_data = json.loads(router_response)
                    intent = intent_data.get('intent', 'chat')
                    book_title = intent_data.get('book_title')
                    user_message = intent_data.get('user_message', request.user_message)
                except json.JSONDecodeError as json_error:
                    logger.debug(f"Router JSON parse error: {json_error}, defaulting to chat")
                    intent = 'chat'
                    book_title = None
                    user_message = request.user_message
                
                logger.info(f"📋 Intent: {intent}, Book: {book_title}")
                
            except Exception as router_error:
                logger.debug(f"Router error: {str(router_error)[:200]}, defaulting to chat")
                intent = 'chat'
                book_title = None
                user_message = request.user_message
            
            # Route based on intent
            sources = []
            if intent == 'generate_questions':
                response_text = "To create a quiz, please use the Policy Quizzes section. Here I can answer questions about the documents in this knowledge base."
                
            elif intent == 'generate_lecture':
                response_text = "I can answer questions about the documents in this knowledge base. Please ask about a specific policy, procedure, product or topic."
                
            else:
                # Answer from the knowledge base documents
                response_text, sources = await self._handle_educational_chat(
                    user_message, request.session_id, curriculum_context,
                    book_id=request.book_id, topic=request.topic
                )
            
            # Save AI response to history
            await self._save_message_to_history(
                request.session_id,
                MessageType.ASSISTANT,
                response_text
            )
            
            logger.info("✅ Chat response generated successfully")
            
            return ChatResponse(
                response=response_text,
                session_id=request.session_id,
                intent=request.intent or "answer_question",
                metadata={"curriculum_context": curriculum_context, "sources": sources}
            )
            
        except Exception as e:
            logger.error(f"❌ Error in chat handling: {e}")
            
            # Return error response
            error_message = "I apologize, but I encountered an error processing your request. Please try again or rephrase your question."
            
            # Still try to save error response to history
            try:
                await self._save_message_to_history(
                    request.session_id,
                    MessageType.ASSISTANT,
                    error_message
                )
            except:
                pass
            
            return ChatResponse(
                response=error_message,
                session_id=request.session_id,
                intent=request.intent or "answer_question",
                metadata={"error": "Error occurred"}
            )

    # ============================================================================
    # RAG METHODS - Vector Database Search
    # ============================================================================
    
    async def _search_curriculum_embeddings(self, curriculum_name: str, query: str, k: int = 6) -> List[Dict[str, Any]]:
        """Search curriculum-based embeddings using vector similarity"""
        try:
            # Generate embedding for the query using Ollama
            query_embedding = await self.embeddings.aembed_query(query)
            
            # Search in curriculum embedding table
            results = await self.db.search_curriculum_embeddings(curriculum_name, query_embedding, limit=k)
            
            logger.info(f"✅ Retrieved {len(results)} chunks from curriculum '{curriculum_name}'")
            return results
            
        except Exception as e:
            logger.error(f"❌ Error in curriculum embedding search for '{curriculum_name}': {e}")
            return []
    
    async def _get_chunks_for_curriculum_topics(self, curriculum_name: str, topics: List[str]) -> List[Dict[str, Any]]:
        """Get content chunks for curriculum topics across all books"""
        try:
            logger.info(f"🔍 Getting chunks for {len(topics)} curriculum topics")
            
            all_chunks = []
            
            for i, topic in enumerate(topics[:10]):  # Limit to prevent overload
                logger.info(f"📄 Getting chunks for topic {i+1}: '{topic[:50]}...'")
                
                # Search for chunks related to this topic
                chunks = await self._search_curriculum_embeddings(curriculum_name, topic, k=3)
                if chunks:
                    all_chunks.extend(chunks)
                    logger.info(f"✅ Found {len(chunks)} chunks for '{topic[:50]}...'")
            
            # Remove duplicates based on content
            unique_chunks = []
            seen_content = set()
            
            for chunk in all_chunks:
                content_hash = hash(chunk['content'][:100])
                if content_hash not in seen_content:
                    unique_chunks.append(chunk)
                    seen_content.add(content_hash)
            
            logger.info(f"✅ Retrieved {len(unique_chunks)} unique chunks from curriculum")
            return unique_chunks
            
        except Exception as e:
            logger.error(f"❌ Error getting chunks for curriculum topics: {e}")
            return []

    async def _handle_educational_chat(self, user_message: str, session_id: str, curriculum_context: str,
                                       book_id: Optional[int] = None, topic: Optional[str] = None) -> Tuple[str, List[Dict[str, Any]]]:
        """Answer strictly from the knowledge base documents, optionally scoped to one document and/or a topic.

        Returns the answer text and the list of sources (numbered as cited in the answer).
        """
        not_found = ("The documents in this knowledge base do not contain information about this question. "
                     "Try rephrasing it, choosing a different document, or asking about a specific policy or topic.")
        try:
            logger.info(f"📚 Knowledge base '{curriculum_context}' | document={book_id} | topic={topic!r}")

            # STEP 1: Conversation memory
            chat_history = await self._get_session_chat_history(session_id, limit=10)

            # STEP 2: Rewrite follow-up questions ("what about that?") into standalone search queries
            search_query = user_message
            if chat_history:
                history_text = "\n".join(
                    f"{'Employee' if isinstance(msg, HumanMessage) else 'Assistant'}: {msg.content[:200]}"
                    for msg in chat_history[-4:]
                )
                rewrite_prompt = f"""Given this conversation history:

{history_text}

Current question: "{user_message}"

If the question contains references (like "it", "that", "this", "more details"), rewrite it as a standalone search query that captures the actual topic. If it is already standalone, return it as-is.

Return ONLY the query, nothing else."""
                try:
                    search_query = (await self.llm.ainvoke(rewrite_prompt)).content.strip() or user_message
                    logger.info(f"🔄 Rewrote query: '{user_message[:50]}' → '{search_query[:50]}'")
                except Exception as e:
                    logger.warning(f"⚠️ Query rewrite failed, using original: {e}")
            if topic:
                search_query = f"{topic}: {search_query}"

            # STEP 3: Vector search, across the knowledge base or within one document
            query_embedding = await self.embeddings.aembed_query(search_query)
            if book_id:
                retrieved_chunks = await self.db.search_book_specific_embeddings(
                    curriculum_context, book_id, query_embedding, limit=6
                )
            else:
                retrieved_chunks = await self.db.search_curriculum_embeddings(
                    curriculum_context, query_embedding, limit=6
                )
            if not retrieved_chunks:
                logger.warning(f"❌ No content found for: {user_message[:100]}")
                return not_found, []

            # STEP 4: Number the excerpts and collect their sources
            context_parts, sources = [], []
            for i, chunk in enumerate(retrieved_chunks, 1):
                content = chunk.get('content', '') if isinstance(chunk, dict) else str(chunk)
                if not content:
                    continue
                metadata = chunk.get('metadata') if isinstance(chunk, dict) else None
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except json.JSONDecodeError:
                        metadata = None
                metadata = metadata or {}
                document = format_title(metadata.get('book_title') or metadata.get('file_name') or 'Document')
                page = metadata.get('page')
                label = f"{document}, p. {page}" if page else document
                n = len(sources) + 1
                context_parts.append(f"[{n}] ({label})\n{content}")
                sources.append({"n": n, "document": document, "page": page, "excerpt": content[:300]})

            if not context_parts:
                return not_found, []

            history_block = ""
            if chat_history:
                history_block = "CONVERSATION SO FAR:\n" + "\n".join(
                    f"{'Employee' if isinstance(msg, HumanMessage) else 'Assistant'}: {msg.content}"
                    for msg in chat_history
                ) + "\n\n"
            focus_block = f"FOCUS TOPIC: {topic}\n\n" if topic else ""

            prompt = f"""{history_block}DOCUMENT EXCERPTS:
{chr(10).join(context_parts)}

{focus_block}EMPLOYEE QUESTION: {user_message}

Answer using ONLY the excerpts above and cite them as [n]. If they do not answer the question, say so."""

            # STEP 5: Generate the grounded answer
            chain = self.simple_chat_prompt | self.llm | StrOutputParser()
            result = await chain.ainvoke({"user_message": prompt})
            logger.info("✅ Grounded answer generated")

            # Only list the excerpts the answer actually cites
            cited = {int(n) for n in re.findall(r"\[(\d+)\]", result)}
            return result.strip(), [src for src in sources if src["n"] in cited]

        except Exception as e:
            logger.error(f"❌ Error answering from knowledge base: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return "Sorry, something went wrong while searching the documents. Please try again.", []

    async def _get_session_chat_history(self, session_id: str, limit: int = 10) -> List[Any]:
        """Get recent chat history for context"""
        try:
            history_messages = await self.get_chat_history(session_id, limit)
            
            formatted_history = []
            for msg in history_messages[-limit:]:  # Get recent messages
                if msg.message_type == MessageType.USER:
                    formatted_history.append(HumanMessage(content=msg.content))
                elif msg.message_type == MessageType.ASSISTANT:
                    formatted_history.append(AIMessage(content=msg.content))
            
            return formatted_history
            
        except Exception as e:
            logger.error(f"Error getting chat history: {e}")
            return []

    def _create_curriculum_knowledge_tool(self, curriculum_name: str) -> Tool:
        """Create knowledge search tool for curriculum content"""
        async def search_curriculum(query: str) -> str:
            """Search for curriculum-related content"""
            try:
                # Search across all books in the curriculum
                books = await self._get_curriculum_books(curriculum_name)
                
                all_results = []
                for book in books[:3]:  # Limit to top 3 books
                    book_results = await self._search_book_content(book['title'], query, k=2)
                    if book_results:
                        all_results.extend([f"From {book['title']}: {result}" for result in book_results])
                
                if all_results:
                    return f"Found curriculum content:\n\n" + "\n\n".join(all_results[:5])
                else:
                    return f"No specific curriculum content found for: {query}"
                    
            except Exception as e:
                logger.error(f"Error in curriculum search: {e}")
                return f"Error searching curriculum content: {str(e)}"
        
        return Tool(
            name="curriculum_knowledge_search",
            description=f"Search for educational content and information from {curriculum_name} curriculum materials.",
            func=search_curriculum
        )

    def _create_book_knowledge_tool(self, book_title: str) -> Tool:
        """Create knowledge search tool for specific book content"""
        async def search_book(query: str) -> str:
            """Search for book-specific content"""
            try:
                results = await self._search_book_content(book_title, query, k=4)
                
                if results:
                    return f"Found content from {book_title}:\n\n" + "\n\n".join(results)
                else:
                    return f"No specific content found in {book_title} for: {query}"
                    
            except Exception as e:
                logger.error(f"Error in book search: {e}")
                return f"Error searching book content: {str(e)}"
        
        return Tool(
            name="book_knowledge_search",
            description=f"Search for specific content and information from the book: {book_title}.",
            func=search_book
        )

    async def create_chat_session(self, user_id: str, curriculum_name: str = None, book_title: str = None, session_name: str = None) -> ChatSessionModel:
        """Create a new chat session for curriculum or book-based conversations"""
        try:
            # Validate input - either curriculum_name or book_title should be provided
            if not curriculum_name and not book_title:
                raise ValueError("Either curriculum_name or book_title must be provided")
            
            # CRITICAL: Validate that user exists in the database before creating session
            user_check_query = "SELECT id FROM users WHERE id = $1"
            user_result = await self.db.execute_query(user_check_query, user_id)
            
            if not user_result or len(user_result) == 0:
                logger.error(f"❌ User with ID {user_id} not found in database. User needs to log in again.")
                raise ValueError(f"User not found. Please log out and log in again to refresh your session.")
            
            logger.info(f"✅ User {user_id} validated successfully")
            
            # Generate session name if not provided
            if not session_name:
                if curriculum_name:
                    session_name = f"Chat about {curriculum_name}"
                else:
                    session_name = f"Chat about {book_title}"
            
            # Determine session type and related content
            session_type = "curriculum" if curriculum_name else "book"
            
            # Create session in database
            session_query = """
                INSERT INTO chat_sessions (user_id, session_name, session_type, curriculum_name, book_title, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, user_id, session_name, session_type, curriculum_name, book_title, created_at, updated_at
            """
            
            now = datetime.utcnow()
            
            result = await self.db.execute_query(
                session_query,
                user_id, session_name, session_type, curriculum_name, book_title, now, now
            )
            
            if result:
                session_data = result[0]
                
                # Initialize empty conversation memory for this session
                self.chat_histories[str(session_data['id'])] = []
                
                return ChatSessionModel(
                    id=str(session_data['id']),
                    user_id=str(session_data['user_id']),
                    session_name=session_data['session_name'],
                    session_type=session_data['session_type'],
                    curriculum_name=session_data['curriculum_name'],
                    book_title=session_data['book_title'],
                    created_at=session_data['created_at'],
                    updated_at=session_data['updated_at']
                )
            
            raise Exception("Failed to create session")
            
        except Exception as e:
            logger.error(f"Error creating chat session: {e}")
            raise e

    async def get_chat_session(self, session_id: str) -> Optional[ChatSessionModel]:
        """Get chat session by ID"""
        try:
            query = """
                SELECT id, user_id, session_name, session_type, curriculum_name, book_title, created_at, updated_at
                FROM chat_sessions
                WHERE id = $1
            """
            
            result = await self.db.execute_query(query, session_id)
            
            if result:
                session_data = result[0]
                return ChatSessionModel(
                    id=str(session_data['id']),
                    user_id=str(session_data['user_id']),
                    session_name=session_data['session_name'],
                    session_type=session_data['session_type'],
                    curriculum_name=session_data['curriculum_name'],
                    book_title=session_data['book_title'],
                    created_at=session_data['created_at'],
                    updated_at=session_data['updated_at']
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting chat session {session_id}: {e}")
            return None

    async def get_user_sessions(self, user_id: str) -> List[ChatSessionModel]:
        """Get all chat sessions for a user"""
        try:
            query = """
                SELECT id, user_id, session_name, session_type, curriculum_name, book_title, created_at, updated_at
                FROM chat_sessions
                WHERE user_id = $1
                ORDER BY updated_at DESC
            """
            
            result = await self.db.execute_query(query, user_id)
            
            sessions = []
            if result:
                for session_data in result:
                    sessions.append(ChatSessionModel(
                        id=str(session_data['id']),
                        user_id=str(session_data['user_id']),
                        session_name=session_data['session_name'],
                        session_type=session_data['session_type'],
                        curriculum_name=session_data['curriculum_name'],
                        book_title=session_data['book_title'],
                        created_at=session_data['created_at'],
                        updated_at=session_data['updated_at']
                    ))
            
            return sessions
            
        except Exception as e:
            logger.error(f"Error getting user sessions: {e}")
            return []

    async def delete_chat_session(self, session_id: str) -> bool:
        """Delete a chat session and its history"""
        try:
            # Delete chat history first
            await self.db.execute_query(
                "DELETE FROM chat_history WHERE session_id = $1", 
                session_id
            )
            
            # Delete session
            result = await self.db.execute_query(
                "DELETE FROM chat_sessions WHERE id = $1", 
                session_id
            )
            
            # Clean up memory
            if session_id in self.chat_histories:
                del self.chat_histories[session_id]
            
            return result is not None
            
        except Exception as e:
            logger.error(f"Error deleting chat session {session_id}: {e}")
            return False

    async def get_chat_history(self, session_id: str, limit: int = 50) -> List[ChatMessageModel]:
        """Get chat history for a session"""
        try:
            query = """
                SELECT id, session_id, message_type, message, created_at
                FROM chat_history
                WHERE session_id = $1
                ORDER BY created_at ASC
                LIMIT $2
            """
            
            result = await self.db.execute_query(query, session_id, limit)
            
            history = []
            if result:
                for msg_data in result:
                    history.append(ChatMessageModel(
                        id=str(msg_data['id']),
                        session_id=str(msg_data['session_id']),
                        message_type=MessageType(msg_data['message_type']),
                        content=msg_data['message'],
                        created_at=msg_data['created_at']
                    ))
            
            return history
            
        except Exception as e:
            logger.error(f"Error getting chat history for session {session_id}: {e}")
            return []

    async def _save_message_to_history(self, session_id: str, message_type: MessageType, content: str) -> Optional[ChatMessageModel]:
        """Save a message to chat history"""
        try:
            query = """
                INSERT INTO chat_history (session_id, message_type, message, created_at)
                VALUES ($1, $2, $3, $4)
                RETURNING id, session_id, message_type, message, created_at
            """
            
            result = await self.db.execute_query(
                query,
                session_id, message_type.value, content, datetime.utcnow()
            )
            
            if result:
                msg_data = result[0]
                return ChatMessageModel(
                    id=str(msg_data['id']),
                    session_id=str(msg_data['session_id']),
                    message_type=MessageType(msg_data['message_type']),
                    content=msg_data['message'],
                    created_at=msg_data['created_at']
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error saving message to history: {e}")
            return None

    # Helper methods for knowledge search
    async def _get_curriculum_books(self, curriculum_name: str) -> List[Dict[str, Any]]:
        """Get all books in a curriculum"""
        try:
            query = """
                SELECT b.id, b.title, b.author, b.description
                FROM curriculum c
                JOIN curriculum_books cb ON c.id = cb.curriculum_id
                JOIN books b ON cb.book_id = b.id
                WHERE c.name = $1
                ORDER BY b.title
            """
            
            result = await self.db.execute_query(query, curriculum_name)
            return [{"id": row["id"], "title": row["title"], "author": row["author"], "description": row["description"]} for row in result] if result else []
            
        except Exception as e:
            logger.error(f"Error getting curriculum books: {e}")
            return []

    async def _search_book_content(self, book_title: str, query: str, k: int = 5) -> List[str]:
        """Search for content within a specific book"""
        try:
            # Clean book title for table name
            table_name = book_title.lower().replace(' ', '_').replace('-', '_')
            
            # First check if table exists
            check_query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = $1
                );
            """
            
            table_exists = await self.db.execute_query(check_query, table_name)
            
            if not table_exists or not table_exists[0]['exists']:
                logger.warning(f"Table {table_name} does not exist")
                return []
            
            # Search for content using text similarity
            search_query = f"""
                SELECT content
                FROM {table_name}
                WHERE content ILIKE $1
                LIMIT $2;
            """
            
            results = await self.db.execute_query(search_query, f"%{query}%", k)
            
            if results:
                return [row['content'] for row in results]
            else:
                return []
                
        except Exception as e:
            logger.error(f"Error searching book content: {e}")
            return []