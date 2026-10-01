import logging
from typing import List, Optional, Dict, Any
import json
import os
import asyncio
import asyncpg
from datetime import datetime
from contextlib import asynccontextmanager

from langchain_google_genai import ChatGoogleGenerativeAI
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
        
        # Primary LLM (Google Gemini) with proper configuration for agents
        gemini_model = os.getenv("CHAT_MODEL_NAME", "gemini-pro")
        try:
            self.llm = ChatGoogleGenerativeAI(
                model=gemini_model,
                temperature=float(os.getenv("CHAT_MODEL_TEMPERATURE", "0.7")),
                google_api_key=os.getenv("GOOGLE_API_KEY"),
                top_k=40,
                top_p=0.8,
                max_tokens=2048,
                convert_system_message_to_human=True
            )
        except Exception as llm_init_error:
            logger.warning(f"⚠️ Primary LLM initialization failed: {llm_init_error}")
            # Initialize with basic configuration as fallback
            self.llm = ChatGoogleGenerativeAI(
                model=gemini_model,
                temperature=0.7,
                google_api_key=os.getenv("GOOGLE_API_KEY"),
                convert_system_message_to_human=True
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
        
        # Strict RAG-based response prompt - ONLY use provided curriculum content
        self.simple_chat_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert educational AI assistant with STRICT knowledge boundaries.

**CRITICAL RULES - YOU MUST FOLLOW THESE:**

1. **ONLY USE PROVIDED CONTENT**: You may ONLY answer questions using information explicitly provided in the curriculum knowledge base content given to you.

2. **NO EXTERNAL KNOWLEDGE**: Do NOT use any general knowledge, internet information, or training data. If information is not in the provided content, you MUST say so.

3. **MANDATORY CITATION**: You MUST end EVERY response with: (Source: Internal Knowledge Base)

4. **HONEST LIMITATIONS**: If the provided content doesn't contain enough information to fully answer the question, clearly state:
   - What information you CAN provide from the content
   - What information is NOT available in the provided content
   - Suggest the user ask a more specific question about topics in the curriculum

5. **PROFESSIONAL STRUCTURE**: Organize answers with clear sections:
   - 🎯 **Direct Answer**: Start with the main point
   - 📚 **Detailed Explanation**: Expand using ONLY provided content
   - 🔑 **Key Concepts**: Highlight important terms from the content
   - 💡 **Examples**: Use ONLY examples from the provided content

6. **IF NO RELEVANT CONTENT**: If you receive a question but the provided content is not relevant, you MUST respond:
"I apologize, but the curriculum content provided does not contain information about this topic. Please ask about topics covered in the available curriculum materials. (Source: Internal Knowledge Base)"

Remember: Your credibility depends on being honest about your knowledge boundaries. It's better to say "The provided content doesn't cover this" than to provide information from outside sources."""),
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
            
            # Determine curriculum context
            curriculum_context = session.curriculum_name or session.book_title or "General Education"
            
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
            if intent == 'generate_questions':
                response_text = "I understand you want to generate questions. For question generation, please use the dedicated exam generation feature available in the application interface. I'm here to help with educational conversations and explanations about the curriculum content."
                
            elif intent == 'generate_lecture':
                response_text = "I understand you want to create lecture content. For lecture generation, please use the dedicated script generation feature available in the application interface. I'm here to help with educational conversations and explanations about the curriculum content."
                
            else:
                # Handle as regular chat conversation
                response_text = await self._handle_educational_chat(
                    user_message, request.session_id, curriculum_context, book_title
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
                metadata={"curriculum_context": curriculum_context}
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

    async def _handle_educational_chat(self, user_message: str, session_id: str, curriculum_context: str, book_title: str = None) -> str:
        """Handle educational chat with STRICT RAG + MEMORY - using LangChain message format like backup"""
        try:
            logger.info(f"📚 STRICT RAG MODE with MEMORY: Searching curriculum '{curriculum_context}'")
            
            # STEP 1: RETRIEVE CONVERSATION MEMORY (from DB) - Like backup file
            # Get chat history as LangChain message objects
            chat_history = await self._get_session_chat_history(session_id, limit=10)
            
            logger.info(f"💭 Retrieved {len(chat_history)} messages from conversation history")
            
            # STEP 2: INTELLIGENT QUERY REWRITING (if there's conversation history)
            # Use LLM to understand what the user is actually asking about based on context
            search_query = user_message
            if chat_history:
                # Build conversation context for query rewriting
                history_for_rewrite = []
                for msg in chat_history[-4:]:  # Last 4 messages for context
                    role = "Student" if isinstance(msg, HumanMessage) else "Tutor"
                    history_for_rewrite.append(f"{role}: {msg.content[:200]}")  # Limit length
                
                history_text = "\n".join(history_for_rewrite)
                
                # Use LLM to rewrite query if it contains references (it, that, this, etc.)
                rewrite_prompt = f"""Given this conversation history:

{history_text}

Current user question: "{user_message}"

If the user's question contains pronouns or references (like "it", "that", "this", "explain again", "more details", etc.), rewrite it as a standalone search query that captures the actual topic being discussed.

If the question is already clear and standalone, return it as-is.

Return ONLY the rewritten query, nothing else."""

                try:
                    rewrite_chain = self.simple_chat_prompt | self.llm | StrOutputParser()
                    search_query = await rewrite_chain.ainvoke({"user_message": rewrite_prompt})
                    search_query = search_query.strip()
                    logger.info(f"🔄 Rewrote query: '{user_message[:50]}...' → '{search_query[:50]}...'")
                except Exception as e:
                    logger.warning(f"⚠️ Query rewrite failed, using original: {e}")
                    search_query = user_message
            
            # STEP 3: Search vector database with the intelligent query
            retrieved_chunks = await self._search_curriculum_embeddings(
                curriculum_name=curriculum_context,
                query=search_query,  # Use rewritten query for better retrieval
                k=6  # Retrieve top 6 most relevant chunks
            )
            
            # STEP 4: Check if we found relevant content
            if not retrieved_chunks:
                logger.warning(f"❌ No relevant content found in vector database for query: {user_message[:100]}")
                return "I apologize, but I couldn't find any relevant information about your question in the available curriculum materials. Please try rephrasing your question or ask about topics covered in the curriculum content.\n\n(Source: Internal Knowledge Base)"
            
            logger.info(f"✅ Found {len(retrieved_chunks)} relevant chunks from vector database")
            
            # STEP 5: Build context from retrieved chunks
            context_parts = []
            for i, chunk in enumerate(retrieved_chunks, 1):
                try:
                    content = chunk.get('content', '') if isinstance(chunk, dict) else str(chunk)
                    metadata = chunk.get('metadata') if isinstance(chunk, dict) else None
                    
                    # Handle metadata - it might be None, dict, or JSON string
                    if metadata is None:
                        book = 'Unknown Book'
                    elif isinstance(metadata, dict):
                        book = metadata.get('book_title', 'Unknown Book')
                    else:
                        # Try to parse as JSON if it's a string
                        try:
                            import json
                            metadata_dict = json.loads(metadata) if isinstance(metadata, str) else {}
                            book = metadata_dict.get('book_title', 'Unknown Book')
                        except:
                            book = 'Unknown Book'
                    
                    if content:
                        context_parts.append(f"[Source {i} - {book}]:\n{content}")
                except Exception as e:
                    logger.error(f"Error processing chunk {i}: {e}")
                    continue
            
            if not context_parts:
                logger.warning(f"❌ Chunks found but no valid content extracted")
                return "I apologize, but I couldn't extract valid information from the curriculum materials. Please try rephrasing your question.\n\n(Source: Internal Knowledge Base)"
            
            combined_context = "\n\n".join(context_parts)
            
            # STEP 6: Build conversation history context from LangChain messages
            history_context = ""
            if chat_history:
                history_lines = []
                for msg in chat_history:
                    role = "Student" if isinstance(msg, HumanMessage) else "Tutor"
                    history_lines.append(f"{role}: {msg.content}")
                history_context = "\n".join(history_lines)
                logger.info(f"💬 Including {len(chat_history)} messages as conversation context")
            
            # STEP 7: Create enhanced prompt WITH conversation history and STRICT instructions
            if history_context:
                # Include conversation history for context-aware responses
                enhanced_message = f"""**CONVERSATION HISTORY:**
{history_context}

**CURRICULUM KNOWLEDGE BASE CONTENT:**
{combined_context}

**CURRENT USER QUESTION:** {user_message}

**CRITICAL INSTRUCTIONS:**
- You MUST answer ONLY based on the curriculum content provided above
- Use the conversation history to understand context and references (e.g., "it", "that concept", "explain more", "what about...")
- If the user refers to something from the previous conversation, acknowledge it
- If the provided content doesn't fully answer the question, clearly state what information is missing
- Do NOT use any external knowledge or general information
- Structure your response professionally with clear sections
- ALWAYS end your response with: (Source: Internal Knowledge Base)

Please provide a comprehensive answer using ONLY the information from the curriculum content above, while considering the conversation context."""
            else:
                # First message in conversation - no history
                enhanced_message = f"""**CURRICULUM KNOWLEDGE BASE CONTENT:**

{combined_context}

**USER QUESTION:** {user_message}

**CRITICAL INSTRUCTIONS:**
- You MUST answer ONLY based on the curriculum content provided above
- Do NOT use any external knowledge or general information
- If the provided content doesn't fully answer the question, clearly state what information is missing
- Structure your response professionally with clear sections
- ALWAYS end your response with: (Source: Internal Knowledge Base)

Please provide a comprehensive answer using ONLY the information from the curriculum content above."""
            
            # STEP 8: Generate response using ONLY the retrieved content with conversation awareness
            chain = self.simple_chat_prompt | self.llm | StrOutputParser()
            result = await chain.ainvoke({"user_message": enhanced_message})
            
            # STEP 9: Verify the response includes the citation
            if "(Source: Internal Knowledge Base)" not in result:
                result += "\n\n(Source: Internal Knowledge Base)"
            
            logger.info(f"✅ Strict RAG response with memory context generated successfully")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error in educational chat: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return "I apologize, but I encountered an error while processing your question. Please try again.\n\n(Source: Internal Knowledge Base)"

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

    def _create_web_search_tool(self) -> Tool:
        """Create web search tool for additional information"""
        async def web_search(query: str) -> str:
            """Search the web for additional information"""
            try:
                # Check if Tavily API is available
                tavily_api_key = os.getenv("TAVILY_API_KEY")
                if not tavily_api_key:
                    return "Web search is not available at the moment."
                
                # Use Tavily API for web search
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://api.tavily.com/search",
                        headers={
                            "Authorization": f"Bearer {tavily_api_key}",
                            "Content-Type": "application/json"
                        },
                        json={"query": query}
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        results = data.get('results', [])
                        
                        # Format results
                        formatted_results = []
                        for result in results[:3]:  # Top 3 results
                            formatted_results.append(f"Title: {result.get('title', 'N/A')}\nContent: {result.get('content', 'N/A')}")
                        
                        return "\n\n".join(formatted_results) if formatted_results else "No web search results found."
                    else:
                        return "Web search failed - API error."
                        
            except Exception as e:
                logger.error(f"Error in web search: {e}")
                return "Web search encountered an error."
        
        return Tool(
            name="web_search",
            description="Search the web for information when the internal knowledge base doesn't have the answer.",
            func=web_search
        )

    # Session Management Methods
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