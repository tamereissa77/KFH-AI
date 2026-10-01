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
                max_tokens=2048
            )
        except Exception as llm_init_error:
            logger.warning(f"⚠️ Primary LLM initialization failed: {llm_init_error}")
            # Initialize with basic configuration as fallback
            self.llm = ChatGoogleGenerativeAI(
                model=gemini_model,
                temperature=0.7,
                google_api_key=os.getenv("GOOGLE_API_KEY")
            )
        
        # Using only Gemini - no fallback LLM
        
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

**Determine the `intent`:** Analyze the `user_message` text and classify the user's primary goal:
- **`generate_questions`**: Use this intent if the user explicitly asks to **create, generate, or make questions, a quiz, or an exam.**
- **`generate_lecture`**: Use this intent ONLY if the user explicitly uses the word **"lecture" or "presentation"**.
- **`answer_question`**: Use this intent for **ALL OTHER requests**. This includes direct questions, requests for explanation, requests for summaries, and any general conversation. This is your default category.

Copy the `book_title` and `user_message` exactly as provided.

Respond with ONLY the JSON object, no additional text."""),
            ("human", "book_title: {book_title}\nuser_message: {user_message}")
        ])
        
        # Answering agent prompt
        self.answering_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert educational assistant and research specialist with deep knowledge across academic subjects. Your mission is to provide comprehensive, well-structured, and educational responses that help users truly understand the topics they're asking about.

You have access to two powerful tools:
1. `search_internal_knowledge_base`: A specialized database of textbooks and academic materials
2. `web_search`: A general-purpose internet search engine for additional information

**YOUR CORE METHODOLOGY:**

**STEP 1: INTERNAL SEARCH**
Always begin by using the `search_internal_knowledge_base` tool with a well-crafted query based on the user's question.

**STEP 2: CRITICAL EVALUATION**
Evaluate the retrieved information: "Does this content provide sufficient information to answer the user's question comprehensively?"

**STEP 3: INFORMATION GATHERING**
- If internal knowledge is sufficient: Proceed with that information
- If insufficient: Use `web_search` to supplement with additional reliable information

**STEP 4: COMPREHENSIVE RESPONSE STRUCTURE**
Provide your answer using this enhanced structure:

🎯 **DIRECT ANSWER**
Start with a clear, direct answer to the user's specific question.

📚 **DETAILED EXPLANATION**
Provide a thorough explanation that includes:
- Core concepts and principles
- How things work or why they happen
- Context and background information
- Step-by-step processes when applicable

🔑 **KEY TERMS & DEFINITIONS**
Define important terms, concepts, or terminology mentioned in your response. Format as:
- **Term**: Clear, concise definition
- **Another Term**: Definition with context

⚖️ **COMPARISONS & CONTRASTS** (when relevant)
Compare different approaches, methods, theories, or concepts:
- Similarities and differences
- Advantages and disadvantages
- When to use each approach

💡 **PRACTICAL APPLICATIONS & EXAMPLES**
Provide real-world examples, use cases, or applications that illustrate the concepts.

🔗 **CONNECTIONS & RELATIONSHIPS**
Explain how this topic relates to other concepts, subjects, or areas of study.

⚠️ **IMPORTANT CONSIDERATIONS**
Highlight any:
- Common misconceptions
- Limitations or exceptions
- Critical points to remember
- Potential pitfalls or challenges

**RESPONSE GUIDELINES:**
- Use clear, accessible language while maintaining academic rigor
- Include specific examples and analogies when helpful
- Structure information logically with smooth transitions
- Adapt complexity to the user's apparent level of understanding
- Be thorough but concise - avoid unnecessary verbosity
- Use formatting (bullet points, numbered lists) to enhance readability
- Always maintain accuracy and cite your sources

**CITATION REQUIREMENT:**
End your response with: `(Source: Internal Knowledge Base)` or `(Source: Web Search)`. Use only one source - do not mix both."""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "book_title: {book_title}\nmessage: {user_message}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
        
        # Question generation prompts
        self.analysis_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a highly specialized AI that parses user requests for generating educational quizzes. Your sole function is to analyze the provided user message and extract specific parameters into a structured JSON object.

Your response MUST be a single, clean JSON object with the following keys: `topics`, `parameters`.

- **`topics`**: MUST be an array of strings. Extract the specific chapters or significant conceptual nouns the user wants questions about. Ignore generic words like "components", "parts", or "sections". If no valid topics are mentioned, return an empty array.

- **`parameters`**: MUST be a JSON object containing: `count`, `difficulty`, and `question_types`.
  - `count`: An integer representing the total number of questions requested (default: 5).
  - `difficulty`: An array of strings containing any specified difficulty levels (e.g., ["easy", "medium", "hard"]).
  - `question_types`: An array of strings containing any specified question types.

If the user does not specify a value, you MUST return a default value for that key.

Respond with ONLY the JSON object, no additional text."""),
            ("human", "{user_message}")
        ])
        
        # Lecture generation prompt
        self.lecture_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are Professor A.I., an elite educational content creator specializing in transforming academic material into sophisticated, engaging lecture scripts. Your expertise lies in creating professional-grade educational content that rivals the best university lectures.

**Your Mission:** Transform raw knowledge from the embedded book into a polished, comprehensive lecture script that demonstrates mastery of pedagogical principles and subject matter expertise.

**CRITICAL: Tool Usage Instructions**
You have access to a tool called "knowledge_retriever_tool" that searches the book's content. You MUST use this tool to gather information before creating the lecture. When using the tool:
- Call it with relevant search queries related to your lecture topic
- Make multiple calls with different queries to gather comprehensive content
- Base your entire lecture script on the retrieved information

**IMPORTANT: OUTPUT FORMAT**
- Your final response must ONLY contain the formatted lecture script
- Do NOT include any Python code, tool calls, or debugging information
- Do NOT show any print statements or function calls
- Do NOT include ```python code blocks in your response
- Focus solely on delivering a clean, professional lecture script

**Core Workflow:**

1. **Request Analysis:** Thoroughly analyze all parameters (category, title, scope, topics, detail level)

2. **Strategic Knowledge Retrieval:** Use the knowledge_retriever_tool with targeted queries to gather comprehensive, relevant content based on scope and requirements

3. **Content Architecture:** Design a lecture structure that flows logically and builds understanding progressively

4. **Script Development:** Create a sophisticated lecture script with academic rigor appropriate to the detail level

**Lecture Script Structure (Professional Format):**

```
# LECTURE SCRIPT: [Title]
**Category:** [Category] | **Duration:** [Estimated time] | **Level:** [Detail Level]

## LECTURE OVERVIEW
- **Learning Objectives:** What students will achieve
- **Key Concepts:** Main topics to be covered
- **Prerequisites:** Assumed knowledge

## OPENING (5-7 minutes)
**Hook & Context:**
[Engaging opening that connects to real world or current relevance]

**Lecture Roadmap:**
[Clear preview of what will be covered]

## MAIN CONTENT SECTIONS

### Section 1: [Topic Title]
**Teaching Point:** [Core concept]
**Content:** [Detailed explanation with examples]
**Interactive Elements:** [Questions, demonstrations, or exercises]
**Transition:** [Bridge to next section]

[Continue for all sections based on detail level]

## SYNTHESIS & CONCLUSION (5-8 minutes)
**Key Takeaways:** [Essential points students must remember]
**Connections:** [How this relates to broader field/course]
**Next Steps:** [What comes next in learning journey]

## ADDITIONAL RESOURCES
[Suggested readings, exercises, or exploration topics]
```

**Detail Level Specifications:**

**Overview (20-30 minutes):**
- 2-3 main sections
- Broad concepts with essential examples
- Clear, accessible explanations
- Focus on fundamental understanding

**Detailed (45-60 minutes):**
- 4-6 comprehensive sections
- Rich examples and case studies
- Multiple perspectives and applications
- Deeper theoretical foundation

**In-depth (75-90 minutes):**
- 6-8 extensive sections
- Advanced theoretical frameworks
- Critical analysis and evaluation
- Research connections and implications
- Complex problem-solving applications

**Category-Specific Excellence:**

- **Science/Technology:** Include methodology, experimental evidence, real-world applications, current research
- **Mathematics:** Provide intuitive explanations, multiple solution approaches, practical applications
- **Literature/Humanities:** Analyze themes, historical context, critical perspectives, cultural significance
- **History:** Chronological narrative, cause-effect analysis, multiple viewpoints, contemporary relevance
- **Professional Studies:** Case studies, practical frameworks, industry analysis, strategic implications
- **Psychology:** Research foundations, practical applications, ethical considerations, human behavior patterns

**Quality Standards:**
- University-level academic rigor
- Clear, engaging prose suitable for oral delivery
- Logical flow with smooth transitions
- Interactive elements to maintain engagement
- Practical examples that illustrate abstract concepts
- Professional formatting for easy delivery

**Strict Requirements:**
- Base ALL content on knowledge_retriever_tool results
- Maintain academic integrity - no fabricated information
- Adapt complexity precisely to specified detail level
- Honor scope limitations (whole book vs specific topics)
- Create content suitable for live lecture delivery"""),
            ("human", """Create a sophisticated lecture script with these specifications:

**Book:** {book_title}
**Category:** {category}
**Lecture Title:** {title}
**Scope:** {scope}
**Specific Topics:** {specific_topics}
**Detail Level:** {detail_level}
**User Requirements:** {user_message}

Please generate a complete, professional lecture script following the specified format and quality standards."""),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

        # Agent-based question generation prompts
        self.curriculum_question_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a professional exam author and AI education specialist. Your task is to generate high-quality exam questions using the curriculum_question_generator tool to retrieve content from the entire curriculum.

**YOUR MISSION:**
Generate comprehensive exam questions that test knowledge across the entire curriculum, covering multiple books and subject areas within the curriculum.

**CRITICAL PARAMETER ADHERENCE:**
1. Generate EXACTLY the requested number of questions (no more, no less)
2. Use EXACTLY the requested difficulty levels (if user wants "hard", ALL questions must be hard)
3. Use EXACTLY the requested question types (only use the types specified)
4. If multiple values given for a parameter, distribute evenly across them
5. STRICTLY follow the user's exam specifications

**MANDATORY PROCESS:**
1. FIRST: Use the curriculum_question_generator tool with relevant topic queries to retrieve content
2. THEN: Generate questions based on the retrieved curriculum content
3. FINALLY: Return questions in the exact JSON format specified

**EXAM SPECIFICATIONS:**
- Generate questions covering diverse topics from across the curriculum
- Ensure questions represent multiple books/materials in the curriculum  
- Create questions appropriate for comprehensive curriculum assessment
- Follow ALL difficulty and question type requirements EXACTLY
- Ensure broad coverage rather than narrow focus

**QUESTION FORMATTING RULES:**
❌ NEVER include book names, guide titles, or document references in questions
❌ WRONG: "According to the Dell Data Lakehouse Guide, explain..."
❌ WRONG: "As described in the Network Security Handbook..."
❌ WRONG: "Referencing the Cloud Computing Manual..."

✅ ALWAYS keep questions general and concept-focused
✅ CORRECT: "Explain the trade-offs between cloud storage and on-premises storage."
✅ CORRECT: "What are the key principles of network security?"
✅ CORRECT: "Describe the benefits of containerization in modern applications."

**RESPONSE FORMAT:**
Your response MUST be a JSON array of question objects. Each question must have:
- "difficulty": one of "easy", "medium", or "hard" (MUST match user request)
- "type": one of "multiple_choice_single_answer", "true_false", or "open_ended_question" (MUST match user request)
- "question_text": The complete question text WITHOUT any book/guide references
- "options": Array of 4 choices for multiple choice, empty array for others
- "answer": The correct answer as a STRING

**QUALITY REQUIREMENTS:**
- University-level professional questions
- Clear, unambiguous wording without source references
- Technically accurate content
- NO references to specific books, guides, manuals, or documents
- Comprehensive curriculum coverage
- EXACT adherence to user parameters"""),
            ("human", "You must use the curriculum_question_generator tool first with a relevant topic query to retrieve curriculum content, then generate the requested exam questions. Do not ask for additional information - proceed immediately with the tool."),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

        self.book_question_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a professional exam author and AI education specialist. Your task is to generate high-quality exam questions using the book_question_generator tool to retrieve content from a specific book within a curriculum.

**YOUR MISSION:**
Generate focused exam questions that test knowledge from a specific book within the curriculum context.

**CRITICAL PARAMETER ADHERENCE:**
1. Generate EXACTLY the requested number of questions (no more, no less)
2. Use EXACTLY the requested difficulty levels (if user wants "hard", ALL questions must be hard)
3. Use EXACTLY the requested question types (only use the types specified)
4. If multiple values given for a parameter, distribute evenly across them
5. STRICTLY follow the user's exam specifications

**MANDATORY PROCESS:**
1. IMMEDIATELY: Use the book_question_generator tool with a relevant topic query (e.g., "architecture", "configuration", "data processing") to retrieve content from the specific book
2. THEN: Generate questions based on the retrieved book content
3. FINALLY: Return questions in the exact JSON format specified
4. DO NOT ASK FOR MORE INFORMATION - proceed automatically with the tool

**EXAM SPECIFICATIONS:**
- Focus specifically on the selected book's content
- Create questions appropriate for book-level assessment
- Follow ALL difficulty and question type requirements EXACTLY
- Ensure comprehensive coverage of the book's main topics

**QUESTION FORMATTING RULES:**
❌ NEVER include book names, guide titles, or document references in questions
❌ WRONG: "According to the Dell Data Lakehouse Guide, explain..."
❌ WRONG: "As described in this book..."
❌ WRONG: "Referencing the manual..."

✅ ALWAYS keep questions general and concept-focused
✅ CORRECT: "Explain the trade-offs between cloud storage and on-premises storage."
✅ CORRECT: "What are the key principles of network security?"
✅ CORRECT: "Describe the benefits of containerization in modern applications."

**RESPONSE FORMAT:**
Your response MUST be a JSON array of question objects. Each question must have:
- "difficulty": one of "easy", "medium", or "hard" (MUST match user request)
- "type": one of "multiple_choice_single_answer", "true_false", or "open_ended_question" (MUST match user request)
- "question_text": The complete question text WITHOUT any book/guide references
- "options": Array of 4 choices for multiple choice, empty array for others
- "answer": The correct answer as a STRING

**QUALITY REQUIREMENTS:**
- University-level professional questions
- Clear, unambiguous wording without source references
- Technically accurate content
- NO references to specific books, guides, manuals, or documents
- Focused book coverage
- EXACT adherence to user parameters"""),
            ("human", "You must use the book_question_generator tool first with a relevant topic query to retrieve book content, then generate the requested exam questions. Do not ask for additional information - proceed immediately with the tool."),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

        self.topic_question_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a professional exam author and AI education specialist. Your task is to generate high-quality exam questions using the topic_question_generator tool to retrieve content on specific topics from a book.

**YOUR MISSION:**
Generate targeted exam questions that test knowledge on specific topics within a book, ensuring deep coverage of the specified subject areas.

**CRITICAL PARAMETER ADHERENCE:**
1. Generate EXACTLY the requested number of questions (no more, no less)
2. Use EXACTLY the requested difficulty levels (if user wants "hard", ALL questions must be hard)
3. Use EXACTLY the requested question types (only use the types specified)
4. If multiple values given for a parameter, distribute evenly across them
5. STRICTLY follow the user's exam specifications

**MANDATORY PROCESS:**
1. FIRST: Use the topic_question_generator tool with queries related to the specific topics
2. THEN: Generate questions based on the retrieved topic-specific content
3. FINALLY: Return questions in the exact JSON format specified

**EXAM SPECIFICATIONS:**
- Focus exclusively on the specified topics
- Create questions that test deep understanding of the topic areas
- Follow ALL difficulty and question type requirements EXACTLY
- Ensure comprehensive coverage of the specified topics only

**QUESTION FORMATTING RULES:**
❌ NEVER include book names, guide titles, or document references in questions
❌ WRONG: "According to the Dell Data Lakehouse Guide, explain..."
❌ WRONG: "As described in this manual..."
❌ WRONG: "Referencing the documentation..."

✅ ALWAYS keep questions general and concept-focused
✅ CORRECT: "Explain the trade-offs between cloud storage and on-premises storage."
✅ CORRECT: "What are the key principles of network security?"
✅ CORRECT: "Describe the benefits of containerization in modern applications."

**RESPONSE FORMAT:**
Your response MUST be a JSON array of question objects. Each question must have:
- "difficulty": one of "easy", "medium", or "hard" (MUST match user request)
- "type": one of "multiple_choice_single_answer", "true_false", or "open_ended_question" (MUST match user request)
- "question_text": The complete question text WITHOUT any book/guide references
- "options": Array of 4 choices for multiple choice, empty array for others
- "answer": The correct answer as a STRING

**QUALITY REQUIREMENTS:**
- University-level professional questions
- Clear, unambiguous wording without source references
- Technically accurate content
- NO references to specific books, guides, manuals, or documents
- Targeted topic coverage only
- EXACT adherence to user parameters"""),
            ("human", "You must use the topic_question_generator tool first with the specified topics to retrieve relevant content, then generate the requested exam questions. Do not ask for additional information - proceed immediately with the tool."),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def handle_chat(self, request: ChatRequest) -> ChatResponse:
        """Handle chat request with curriculum-based routing"""
        try:
            # For now, let's handle simple Q&A with curriculum
            intent = request.intent or "answer_question"
            
            # Get or create session for curriculum
            session = await self._get_or_create_curriculum_session(request.session_id, request.curriculum)
            
            # Handle Q&A with curriculum context
            response_text = await self._handle_curriculum_question_answering(request, session)
            
            # Save messages to database
            await self.db.add_chat_message(
                session['id'], MessageType.USER.value, request.user_message
            )
            await self.db.add_chat_message(
                session['id'], MessageType.ASSISTANT.value, response_text
            )
            
            # Update session timestamp
            await self.db.update_session_timestamp(session['id'])
            
            return ChatResponse(
                response=response_text,
                session_id=str(session['id']),
                intent=intent,
                metadata={"curriculum": request.curriculum}
            )
            
        except Exception as e:
            logger.error(f"Error handling chat request: {e}")
            raise

    async def _classify_intent(self, book_title: str, user_message: str) -> Dict[str, Any]:
        """Classify user intent"""
        try:
            chain = self.router_prompt | self.llm | StrOutputParser()
            result = await chain.ainvoke({
                "book_title": book_title,
                "user_message": user_message
            })
            
            # Clean and parse JSON
            cleaned_result = result.replace('```json\n', '').replace('\n```', '').strip()
            return json.loads(cleaned_result)
            
        except Exception as e:
            logger.error(f"Error classifying intent: {e}")
            return {"intent": "answer_question", "book_title": book_title, "user_message": user_message}

    async def _handle_question_answering(self, request: ChatRequest, session: Dict[str, Any]) -> str:
        """Handle question answering with ConversationBufferMemory like in chat.py"""
        try:
            # Get or create chat history for the session (like in chat.py)
            session_id = str(session['id'])
            if session_id not in self.chat_histories:
                self.chat_histories[session_id] = ConversationBufferMemory(
                    memory_key="chat_history", 
                    return_messages=True
                )
            memory = self.chat_histories[session_id]
            
            # Load existing messages from database into memory if memory is empty
            if len(memory.chat_memory.messages) == 0:
                await self.memory_manager.load_chat_history_to_memory(session_id, memory, limit=50)
            
            # Create tools
            tools = [
                self._create_knowledge_search_tool(request.book_title),
                self._create_web_search_tool()
            ]
            
            # Create a custom prompt that includes the book_title and user_message
            # This is needed because AgentExecutor with memory has limitations on input variables
            custom_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are an expert educational assistant and research specialist with deep knowledge across academic subjects. Your mission is to provide comprehensive, well-structured, and educational responses that help users truly understand the topics they're asking about.

You are currently working with the book: "{request.book_title}"

You have access to two powerful tools:
1. `search_internal_knowledge_base`: A specialized database of textbooks and academic materials
2. `web_search`: A general-purpose internet search engine for additional information

**YOUR CORE METHODOLOGY:**

**STEP 1: INTERNAL SEARCH**
Always begin by using the `search_internal_knowledge_base` tool with a well-crafted query based on the user's question.

**STEP 2: CRITICAL EVALUATION**
Evaluate the retrieved information: "Does this content provide sufficient information to answer the user's question comprehensively?"

**STEP 3: INFORMATION GATHERING**
- If internal knowledge is sufficient: Proceed with that information
- If insufficient: Use `web_search` to supplement with additional reliable information

**STEP 4: COMPREHENSIVE RESPONSE STRUCTURE**
Provide your answer using this enhanced structure:

🎯 **DIRECT ANSWER**
Start with a clear, direct answer to the user's specific question.

📚 **DETAILED EXPLANATION**
Provide a thorough explanation that includes:
- Core concepts and principles
- How things work or why they happen
- Context and background information
- Step-by-step processes when applicable

🔑 **KEY TERMS & DEFINITIONS**
Define important terms, concepts, or terminology mentioned in your response. Format as:
- **Term**: Clear, concise definition
- **Another Term**: Definition with context

⚖️ **COMPARISONS & CONTRASTS** (when relevant)
Compare different approaches, methods, theories, or concepts:
- Similarities and differences
- Advantages and disadvantages
- When to use each approach

💡 **PRACTICAL APPLICATIONS & EXAMPLES**
Provide real-world examples, use cases, or applications that illustrate the concepts.

🔗 **CONNECTIONS & RELATIONSHIPS**
Explain how this topic relates to other concepts, subjects, or areas of study.

⚠️ **IMPORTANT CONSIDERATIONS**
Highlight any:
- Common misconceptions
- Limitations or exceptions
- Critical points to remember
- Potential pitfalls or challenges

**RESPONSE GUIDELINES:**
- Use clear, accessible language while maintaining academic rigor
- Include specific examples and analogies when helpful
- Structure information logically with smooth transitions
- Adapt complexity to the user's apparent level of understanding
- Be thorough but concise - avoid unnecessary verbosity
- Use formatting (bullet points, numbered lists) to enhance readability
- Always maintain accuracy and cite your sources

**CITATION REQUIREMENT:**
End your response with: `(Source: Internal Knowledge Base)` or `(Source: Web Search)`. Use only one source - do not mix both."""),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad")
            ])
            
            # Use the custom prompt with embedded book title
            agent = create_tool_calling_agent(self.llm, tools, custom_prompt)
            agent_executor = AgentExecutor(
                agent=agent, 
                tools=tools, 
                memory=memory,  # Pass memory to agent executor like in chat.py
                verbose=True
            )
            
            # Execute with memory - only pass input as required by AgentExecutor
            result = await agent_executor.ainvoke({
                "input": request.user_message
            })
            
            # Extract the agent's response
            agent_response = result['output']
            
            # IMPROVED FIX: Use the standard memory.save_context() method (best practice)
            # This ensures immediate context retention for the next turn
            memory.save_context(
                inputs={"input": request.user_message},
                outputs={"output": agent_response}
            )
            
            logger.info(f"Saved conversation turn to memory using save_context(). Total messages in memory: {len(memory.chat_memory.messages)}")
            
            return agent_response
            
        except Exception as e:
            logger.error(f"Error in question answering: {e}")
            return f"I apologize, but I encountered an error while processing your question: {str(e)}"

    def _create_knowledge_search_tool(self, book_title: str) -> Tool:
        """Create curriculum-based knowledge search tool"""
        
        def search_knowledge(query: str) -> str:
            try:
                # Get book information to find its curriculum
                import asyncio
                
                # Run async operation to get book info
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, self._get_book_curriculum_info(book_title))
                            book_info = future.result()
                    else:
                        book_info = loop.run_until_complete(self._get_book_curriculum_info(book_title))
                except RuntimeError:
                    book_info = asyncio.run(self._get_book_curriculum_info(book_title))
                
                if not book_info:
                    return f"Book '{book_title}' not found in the system. Please ensure the book has been uploaded and processed."
                
                curriculum_name = book_info.get('curriculum_name')
                if not curriculum_name:
                    return f"No curriculum information found for book '{book_title}'. The book may not have been properly processed with the new curriculum system."
                
                logger.info(f"Searching in curriculum '{curriculum_name}' for book '{book_title}' with query '{query[:50]}...'")
                
                # Search curriculum embeddings
                try:
                    if loop.is_running():
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, self._search_curriculum_embeddings(curriculum_name, query, k=6))
                            results = future.result()
                    else:
                        results = loop.run_until_complete(self._search_curriculum_embeddings(curriculum_name, query, k=6))
                except RuntimeError:
                    results = asyncio.run(self._search_curriculum_embeddings(curriculum_name, query, k=6))
                
                if results:
                    combined_results = "\n\n".join([r['content'] for r in results])
                    logger.info(f"Found {len(results)} relevant chunks in curriculum '{curriculum_name}' for query: {query[:50]}...")
                    return combined_results
                else:
                    logger.warning(f"No relevant information found in curriculum '{curriculum_name}' for query: {query[:50]}...")
                    return f"No relevant information found in curriculum '{curriculum_name}' for the query. The curriculum may not have sufficient content or the embeddings may not be properly indexed."
                
            except Exception as e:
                logger.error(f"Error searching curriculum knowledge base for '{book_title}': {e}")
                return f"Error accessing curriculum knowledge base for '{book_title}': {str(e)}. This may indicate a database connectivity issue or the curriculum system needs attention."
        
        return Tool(
            name="search_internal_knowledge_base",
            description=f"Search in the curriculum-based knowledge base for the book '{book_title}' to find relevant information. Input should be a search query string only.",
            func=search_knowledge
        )

    def _create_curriculum_knowledge_search_tool(self, curriculum_name: str) -> Tool:
        """Create curriculum-based knowledge search tool that searches across all books in the curriculum"""
        
        def search_curriculum_knowledge(query: str) -> str:
            try:
                import asyncio
                
                logger.info(f"🔍 TOOL CALLED: search_curriculum_knowledge_base for curriculum '{curriculum_name}' with query '{query[:50]}...'")
                
                # Search curriculum embeddings directly
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, self._search_curriculum_embeddings(curriculum_name, query, k=8))
                            results = future.result()
                    else:
                        results = loop.run_until_complete(self._search_curriculum_embeddings(curriculum_name, query, k=8))
                except RuntimeError:
                    results = asyncio.run(self._search_curriculum_embeddings(curriculum_name, query, k=8))
                
                if results:
                    combined_results = "\n\n".join([r['content'] for r in results])
                    logger.info(f"✅ VECTOR SEARCH SUCCESS: Found {len(results)} relevant chunks in curriculum '{curriculum_name}' for query: {query[:50]}...")
                    return combined_results
                else:
                    logger.warning(f"❌ VECTOR SEARCH EMPTY: No relevant information found in curriculum '{curriculum_name}' for query: {query[:50]}...")
                    return f"No relevant information found in curriculum '{curriculum_name}' for the query. The curriculum may not have sufficient content or the embeddings may not be properly indexed."
                
            except Exception as e:
                logger.error(f"Error searching curriculum knowledge base for '{curriculum_name}': {e}")
                return f"Error accessing curriculum knowledge base for '{curriculum_name}': {str(e)}. This may indicate a database connectivity issue or the curriculum system needs attention."
        
        return Tool(
            name="search_curriculum_knowledge_base",
            description=f"MANDATORY TOOL: Search the '{curriculum_name}' curriculum database for relevant information. This tool contains all the books and materials for the {curriculum_name} curriculum. You MUST use this tool first before answering any question. Input: a search query string related to the user's question.",
            func=search_curriculum_knowledge
        )

    async def _get_book_curriculum_info(self, book_title: str) -> Optional[Dict[str, Any]]:
        """Get book information including curriculum with retries"""
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                book_info = await self.db.get_book_by_title(book_title)
                if book_info:
                    logger.info(f"Successfully retrieved info for book '{book_title}' in curriculum '{book_info.get('curriculum_name')}'")
                    return book_info
                else:
                    logger.warning(f"Book '{book_title}' not found in database")
                    return None
            except asyncpg.exceptions.ConnectionDoesNotExistError:
                if attempt < max_retries - 1:
                    logger.warning(f"Connection lost, retrying in {retry_delay} seconds (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Failed to connect to database after {max_retries} attempts")
                    raise
            except Exception as e:
                logger.error(f"Error getting book curriculum info for '{book_title}': {e}")
                return None
    
    async def _search_curriculum_embeddings(self, curriculum_name: str, query: str, k: int = 6) -> List[Dict[str, Any]]:
        """Search curriculum-based embeddings"""
        try:
            # Generate embedding for the query
            query_embedding = await self.embeddings.aembed_query(query)
            
            # Search in curriculum embedding table
            results = await self.db.search_curriculum_embeddings(curriculum_name, query_embedding, limit=k)
            
            logger.info(f"Retrieved {len(results)} chunks from curriculum '{curriculum_name}'")
            return results
            
        except Exception as e:
            logger.error(f"Error in curriculum embedding search for '{curriculum_name}': {e}")
            return []

    async def _extract_book_topics(self, curriculum_name: str, book_title: str) -> List[str]:
        """
        STEP 1: Extract topics from Table of Contents
        This replaces the previous random chunk topic extraction with systematic TOC analysis
        """
        try:
            logger.info(f"� STEP 1: Extracting topics from Table of Contents for '{book_title}'")
            
            # First get book info with proper error handling
            book_info = await self._get_book_curriculum_info(book_title)
            if not book_info:
                logger.warning(f"Book '{book_title}' not found for TOC extraction")
                return await self._extract_keywords_from_random_chunks(curriculum_name)
            
            book_id = book_info['id']
            actual_curriculum = book_info.get('curriculum_name', curriculum_name)
            logger.info(f"� Book found: ID={book_id}, curriculum='{actual_curriculum}'")
            
            # Method 1: Search for TOC-specific content
            logger.info(f"🔍 METHOD 1: Searching for Table of Contents content")
            toc_chunks = await self._search_for_toc_content(book_title, actual_curriculum, book_id)
            
            # Method 2: Get chunks from beginning of book (where TOC usually is)
            logger.info(f"🔍 METHOD 2: Getting chunks from book beginning")
            beginning_chunks = await self._get_beginning_chunks(book_title, actual_curriculum, book_id)
            
            # Combine all potential TOC chunks
            all_toc_chunks = toc_chunks + beginning_chunks
            logger.info(f"📊 FOUND {len(all_toc_chunks)} potential TOC chunks")
            
            if not all_toc_chunks:
                logger.warning("⚠️ No TOC content found, falling back to content-based topic extraction")
                return await self._extract_topics_from_content_fallback(book_title, actual_curriculum, book_id)
            
            # Extract topics from TOC content
            topics = await self._parse_toc_topics(all_toc_chunks, book_title, actual_curriculum)
            
            if topics:
                logger.info(f"✅ STEP 1 SUCCESS: Extracted {len(topics)} topics from TOC: {topics}")
                return topics
            else:
                logger.warning("⚠️ TOC parsing failed, using fallback method")
                return await self._extract_topics_from_content_fallback(book_title, actual_curriculum, book_id)
                
        except Exception as e:
            logger.error(f"❌ Error extracting topics from TOC: {e}")
            return await self._extract_keywords_from_random_chunks(curriculum_name)

    async def _search_for_toc_content(self, book_title: str, curriculum_name: str, book_id: int) -> List[Dict[str, Any]]:
        """Search for chunks containing table of contents using multiple TOC-related queries"""
        toc_queries = [
            "table of contents",
            "contents", 
            "chapter",
            "section",
            "overview",
            "outline",
            "index"
        ]
        
        toc_chunks = []
        for query in toc_queries:
            try:
                logger.info(f"🔍 Searching for TOC with query: '{query}'")
                chunks = await self._search_book_embeddings_safe(book_title, curriculum_name, query, k=2)
                if chunks:
                    logger.info(f"✅ Found {len(chunks)} chunks for TOC query '{query}'")
                    toc_chunks.extend(chunks)
            except Exception as e:
                logger.warning(f"⚠️ Error searching for TOC with query '{query}': {e}")
                continue
        
        # Remove duplicates based on content
        unique_chunks = []
        seen_content = set()
        for chunk in toc_chunks:
            if isinstance(chunk, dict) and 'content' in chunk:
                content_hash = hash(chunk['content'][:100])
                if content_hash not in seen_content:
                    unique_chunks.append(chunk)
                    seen_content.add(content_hash)
        
        logger.info(f"📚 TOC SEARCH: Found {len(unique_chunks)} unique TOC chunks")
        return unique_chunks

    async def _get_beginning_chunks(self, book_title: str, curriculum_name: str, book_id: int, chunk_count: int = 8) -> List[Dict[str, Any]]:
        """Get chunks from the beginning of the book where TOC typically appears"""
        try:
            async with self.get_db_connection() as conn:
                table_name = f"curriculum_embeddings_{curriculum_name.lower().replace(' ', '_')}"
                
                # Check if table exists first
                table_exists_query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = $1
                )
                """
                table_exists = await conn.fetchval(table_exists_query, table_name)
                
                if not table_exists:
                    logger.warning(f"⚠️ Table {table_name} does not exist")
                    return []
                
                # Get first chunks (assuming they're ordered by position in document)
                query = f"""
                SELECT content, metadata 
                FROM {table_name} 
                WHERE book_id = $1 
                ORDER BY id 
                LIMIT $2
                """
                
                results = await conn.fetch(query, book_id, chunk_count)
                
                chunks = []
                for row in results:
                    chunks.append({
                        'content': row['content'],
                        'metadata': row['metadata'] if row['metadata'] else {}
                    })
                
                logger.info(f"📖 BEGINNING CHUNKS: Retrieved {len(chunks)} chunks from book start")
                return chunks
                
        except Exception as e:
            logger.error(f"❌ Error getting beginning chunks: {e}")
            return []

    async def _parse_toc_topics(self, toc_chunks: List[Dict[str, Any]], book_title: str, curriculum_name: str) -> List[str]:
        """Parse Table of Contents content to extract searchable keywords and terms using LLM"""
        try:
            # Combine all TOC content
            toc_content = "\n\n".join([chunk.get('content', '') for chunk in toc_chunks if chunk.get('content')])
            logger.info(f"📝 TOC CONTENT: {len(toc_content)} characters to parse for keywords")
            
            if not toc_content.strip():
                logger.warning("⚠️ No valid TOC content to parse")
                return []
            
            # Use enhanced keyword extraction for TOC content
            toc_keyword_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are an expert at analyzing table of contents and extracting searchable keywords and terms from academic and technical books.

Extract specific, searchable keywords and terms from the Table of Contents content. Focus on:

KEYWORD TYPES TO EXTRACT:
- **Chapter topics**: Specific subject areas mentioned in chapter titles
- **Technical terms**: Specialized vocabulary and concepts
- **Methods/Processes**: Specific approaches, procedures, or methodologies
- **Tools/Technologies**: Specific tools, systems, or technologies mentioned
- **Concepts**: Important ideas and principles
- **Standards/Protocols**: Specific standards, frameworks, or protocols

EXTRACTION CRITERIA:
- Extract terms that would be useful as search queries
- Include both single words and short phrases (2-4 words max)
- Focus on domain-specific terminology for {curriculum_name}
- Prioritize concrete, searchable terms over abstract concepts

BOOK CONTEXT: {book_title}
CURRICULUM: {curriculum_name}

Return ONLY a JSON array of searchable keyword strings:
["keyword1", "keyword2", "keyword3", ...]

Maximum 12 keywords. Focus on the most important and searchable terms."""),
                ("human", "Extract searchable keywords and terms from this Table of Contents content:\n\n{content}")
            ])
            
            chain = toc_keyword_prompt | self.get_current_llm() | StrOutputParser()
            response = await chain.ainvoke({
                "content": toc_content[:4000],  # Limit content size
                "book_title": book_title,
                "curriculum_name": curriculum_name
            })
            
            # Parse the response
            keywords = self._parse_keywords_from_llm_response(response)
            
            if keywords:
                logger.info(f"✅ TOC PARSING SUCCESS: Extracted {len(keywords)} searchable keywords")
                return keywords
            else:
                logger.warning("⚠️ TOC parsing returned no keywords")
                return []
                
        except Exception as e:
            logger.error(f"❌ Error parsing TOC keywords: {e}")
            return []

    def _parse_topics_from_llm_response(self, response_content: str) -> List[str]:
        """Parse topics from LLM response, handling various response formats"""
        try:
            import json
            import re
            
            logger.info(f"🔍 Parsing LLM response: {response_content[:200]}...")
            
            # Method 1: Try to find JSON array in response
            json_match = re.search(r'\[.*?\]', response_content, re.DOTALL)
            if json_match:
                try:
                    json_str = json_match.group()
                    topics = json.loads(json_str)
                    
                    if isinstance(topics, list):
                        # Clean and filter topics
                        clean_topics = []
                        for topic in topics:
                            if isinstance(topic, str) and len(topic.strip()) > 2:
                                # Remove quotes and clean up
                                clean_topic = topic.strip().strip('"\'')
                                if clean_topic.lower() not in ['introduction', 'conclusion', 'references', 'index', 'appendix']:
                                    clean_topics.append(clean_topic)
                        
                        logger.info(f"📋 PARSED TOPICS (JSON): {clean_topics}")
                        return clean_topics[:10]  # Limit to 10 topics
                except json.JSONDecodeError:
                    logger.warning("⚠️ Failed to parse JSON from response")
            
            # Method 2: Try to extract topics from numbered/bulleted lists
            lines = response_content.split('\n')
            topics = []
            for line in lines:
                line = line.strip()
                # Look for patterns like "1. Topic", "- Topic", "• Topic"
                topic_match = re.match(r'^[\d\-\•\*\+]\s*\.?\s*(.+)$', line)
                if topic_match:
                    topic = topic_match.group(1).strip().strip('"\'')
                    if len(topic) > 2 and topic.lower() not in ['introduction', 'conclusion', 'references', 'index', 'appendix']:
                        topics.append(topic)
            
            if topics:
                logger.info(f"📋 PARSED TOPICS (List): {topics}")
                return topics[:10]
            
            # Method 3: Split by common separators if no structure found
            if ',' in response_content:
                topics = [t.strip().strip('"\'') for t in response_content.split(',')]
                clean_topics = [t for t in topics if len(t) > 2 and t.lower() not in ['introduction', 'conclusion', 'references', 'index', 'appendix']]
                if clean_topics:
                    logger.info(f"📋 PARSED TOPICS (Comma-separated): {clean_topics}")
                    return clean_topics[:10]
            
            logger.warning("⚠️ Could not parse topics from LLM response")
            return []
            
        except Exception as e:
            logger.error(f"❌ Error parsing topics from response: {e}")
            return []

    async def _extract_topics_from_content_fallback(self, book_title: str, curriculum_name: str, book_id: int) -> List[str]:
        """Fallback method to extract topics when TOC approach fails"""
        try:
            logger.info(f"🔄 FALLBACK: Extracting topics from general content for '{book_title}'")
            
            # Get general content samples for topic extraction
            initial_query = "main topics key concepts principles overview"
            query_embedding = await self.embeddings.aembed_query(initial_query)
            
            initial_results = await self.db.search_book_specific_embeddings(
                curriculum_name, book_id, query_embedding, limit=5
            )
            
            if not initial_results:
                logger.warning(f"⚠️ No content found for fallback topic extraction")
                # UPDATED: Use dynamic extraction instead of fixed topics
                return await self._extract_keywords_from_random_chunks(curriculum_name, book_title)
            
            logger.info(f"📊 FALLBACK: Found {len(initial_results)} content chunks")
            
            # Extract topics using LLM with curriculum-specific prompting
            content = "\n\n".join(r['content'] for r in initial_results)
            topic_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are an expert {curriculum_name} curriculum analyzer. Extract the main topics covered in this {curriculum_name} text.
                Return ONLY a comma-separated list of 5-8 specific topics that are relevant to {curriculum_name} studies.
                Focus on major themes and subject areas in {curriculum_name}.
                Do not include generic terms like 'introduction' or 'conclusion'."""),
                ("human", "Content: {content}\nExtract the main topics from this content.")
            ])
            
            chain = topic_prompt | self.get_current_llm() | StrOutputParser()
            topics_result = await chain.ainvoke({"content": content})
            
            # Parse and validate topics
            topics = [t.strip() for t in topics_result.split(',') if t.strip() and len(t.strip()) > 3]
            
            if not topics:
                logger.warning("⚠️ FALLBACK: No valid topics extracted, using dynamic random chunks")
                return await self._extract_keywords_from_random_chunks(curriculum_name, book_title)
            
            logger.info(f"✅ FALLBACK SUCCESS: Extracted {len(topics)} topics: {topics}")
            return topics
            
        except Exception as e:
            logger.error(f"❌ FALLBACK ERROR: {e}")
            return await self._extract_keywords_from_random_chunks(curriculum_name, book_title)


    
    def _generate_default_questions(self, exam_parameters: Dict[str, Any], topics: List[str]) -> List[Question]:
        """Generate very basic default questions when all else fails"""
        try:
            if not exam_parameters:
                logger.error("❌ No exam parameters provided for default questions")
                exam_parameters = {
                    'count': 5,
                    'difficulty': ['medium'],
                    'question_types': ['multiple_choice_single_answer']
                }
            
            # Ensure we have required parameters with defaults
            count = exam_parameters.get('count', 5)
            difficulties = exam_parameters.get('difficulty', ['medium'])
            question_types = exam_parameters.get('question_types', ['multiple_choice_single_answer'])
            
            # Ensure topics is a list and not empty
            topics = topics or ["general knowledge", "core concepts", "basic principles"]
            if not isinstance(topics, list):
                topics = [str(topics)]
            
            questions = []
            for i in range(count):
                try:
                    # Rotate through topics
                    topic = topics[i % len(topics)]
                    
                    # Rotate through difficulties if multiple provided
                    difficulty = difficulties[i % len(difficulties)]
                    
                    # Rotate through question types if multiple provided
                    question_type = question_types[i % len(question_types)]
                    
                    # Generate appropriate question based on type
                    if question_type == 'multiple_choice_single_answer':
                        question = Question(
                            difficulty=difficulty,
                            type=question_type,
                            question_text=f"What are the key principles of {topic}?",
                            options=[
                                f"Key concepts and fundamentals of {topic}",
                                f"Basic elements of {topic}",
                                f"Advanced aspects of {topic}",
                                f"Theoretical foundations of {topic}"
                            ],
                            answer=f"Key concepts and fundamentals of {topic}"
                        )
                    elif question_type == 'true_false':
                        question = Question(
                            difficulty=difficulty,
                            type=question_type,
                            question_text=f"{topic} is a fundamental concept in this subject.",
                            options=[],
                            answer="True"
                        )
                    else:  # open_ended_question
                        question = Question(
                            difficulty=difficulty,
                            type='open_ended_question',
                            question_text=f"Explain the key principles and concepts of {topic} in detail.",
                            options=[],
                            answer=f"A comprehensive explanation of {topic} should include its key principles, concepts, and practical applications."
                        )
                    
                    questions.append(question)
                    
                except Exception as q_error:
                    logger.error(f"❌ Error generating default question {i}: {q_error}")
                    continue
            
            logger.info(f"✅ Generated {len(questions)} default questions")
            return questions
            
        except Exception as e:
            logger.error(f"❌ Error in default question generation: {e}")
            # Ultimate fallback - return a single generic question
            return [Question(
                difficulty='medium',
                type='open_ended_question',
                question_text="Explain the key concepts covered in this material.",
                options=[],
                answer="A comprehensive explanation of the key concepts and principles."
            )]
    
    async def _extract_keywords_from_random_chunks(self, curriculum_name: str, book_title: str = None) -> List[str]:
        """
        Dynamic fallback: Get random chunks and extract searchable keywords/terms from them
        This replaces the fixed curriculum-specific topics with dynamic keyword extraction
        """
        try:
            logger.info(f"🎲 DYNAMIC FALLBACK: Extracting searchable keywords from random chunks")
            
            # Get random chunks from curriculum or specific book
            if book_title:
                # Get random chunks from specific book
                book_info = await self._get_book_curriculum_info(book_title)
                if book_info:
                    chunks = await self._get_random_book_chunks(curriculum_name, book_info['id'], count=8)
                else:
                    chunks = await self._get_random_curriculum_chunks(curriculum_name, count=8)
            else:
                # Get random chunks from entire curriculum
                chunks = await self._get_random_curriculum_chunks(curriculum_name, count=10)
            
            if not chunks:
                logger.warning(f"⚠️ No random chunks found for {curriculum_name}")
                return ["fundamental concepts", "key principles", "main topics"]
            
            # Combine chunk content
            combined_content = "\n\n".join([chunk['content'] for chunk in chunks])
            logger.info(f"📝 Analyzing {len(combined_content)} characters from {len(chunks)} random chunks")
            
            # Extract keywords/terms using enhanced LLM prompt
            extracted_keywords = await self._extract_keywords_from_content_llm(combined_content, curriculum_name)
            
            if extracted_keywords:
                logger.info(f"✅ DYNAMIC EXTRACTION SUCCESS: Found {len(extracted_keywords)} searchable keywords from random chunks")
                logger.info(f"🔍 Keywords: {extracted_keywords}")
                return extracted_keywords
            else:
                logger.warning(f"⚠️ Dynamic extraction failed, using generic keywords")
                return ["core concepts", "fundamental principles", "key methodologies"]
                
        except Exception as e:
            logger.error(f"❌ Error in dynamic keyword extraction: {e}")
            return ["general topics", "basic concepts", "main principles"]

    async def _get_random_curriculum_chunks(self, curriculum_name: str, count: int = 10) -> List[Dict[str, Any]]:
        """Get random chunks from curriculum for keyword extraction"""
        try:
            async with self.get_db_connection() as conn:
                table_name = f"curriculum_embeddings_{curriculum_name.lower().replace(' ', '_')}"
                
                # Check if table exists
                table_exists_query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = $1
                )
                """
                table_exists = await conn.fetchval(table_exists_query, table_name)
                
                if not table_exists:
                    logger.warning(f"⚠️ Table {table_name} does not exist")
                    return []
                
                # Get random chunks using ORDER BY RANDOM()
                query = f"""
                SELECT content, metadata 
                FROM {table_name} 
                WHERE char_length(content) > 100 
                ORDER BY RANDOM() 
                LIMIT $1
                """
                
                results = await conn.fetch(query, count)
                
                chunks = []
                for row in results:
                    chunks.append({
                        'content': row['content'],
                        'metadata': row['metadata'] if row['metadata'] else {}
                    })
                
                logger.info(f"🎲 Retrieved {len(chunks)} random chunks from curriculum")
                return chunks
                
        except Exception as e:
            logger.error(f"❌ Error getting random curriculum chunks: {e}")
            return []

    async def _get_random_book_chunks(self, curriculum_name: str, book_id: int, count: int = 8) -> List[Dict[str, Any]]:
        """Get random chunks from specific book for keyword extraction"""
        try:
            async with self.get_db_connection() as conn:
                table_name = f"curriculum_embeddings_{curriculum_name.lower().replace(' ', '_')}"
                
                # Check if table exists
                table_exists_query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = $1
                )
                """
                table_exists = await conn.fetchval(table_exists_query, table_name)
                
                if not table_exists:
                    logger.warning(f"⚠️ Table {table_name} does not exist")
                    return []
                
                # Get random chunks from specific book
                query = f"""
                SELECT content, metadata 
                FROM {table_name} 
                WHERE book_id = $1 AND char_length(content) > 100 
                ORDER BY RANDOM() 
                LIMIT $2
                """
                
                results = await conn.fetch(query, book_id, count)
                
                chunks = []
                for row in results:
                    chunks.append({
                        'content': row['content'],
                        'metadata': row['metadata'] if row['metadata'] else {}
                    })
                
                logger.info(f"🎲 Retrieved {len(chunks)} random chunks from book {book_id}")
                return chunks
                
        except Exception as e:
            logger.error(f"❌ Error getting random book chunks: {e}")
            return []

    async def _extract_keywords_from_content_llm(self, content: str, curriculum_name: str) -> List[str]:
        """Extract searchable keywords and terms from content using LLM analysis"""
        try:
            logger.info(f"🤖 Using LLM to extract searchable keywords from content")
            
            # ENHANCED KEYWORD EXTRACTION PROMPT
            keyword_extraction_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are an expert keyword extraction specialist. Your task is to extract specific, searchable keywords and terms from the provided content that can be used as search queries to find related material.

CRITICAL REQUIREMENTS:
- Extract 10-15 specific keywords/terms that appear in the content
- Focus on technical terms, concepts, tools, methods, and specific topics
- Extract terms that would be useful as search queries to find similar content
- Include both single words and short phrases (2-4 words max)
- Prioritize domain-specific terminology for {curriculum_name}
- Include proper nouns, technical concepts, and important terms

KEYWORD TYPES TO EXTRACT:
1. **Technical Terms**: Specific technical vocabulary and jargon
2. **Concepts**: Important ideas and principles mentioned
3. **Tools/Methods**: Specific tools, methodologies, or approaches
4. **Processes**: Names of procedures, workflows, or systems
5. **Standards**: Protocols, standards, or frameworks mentioned
6. **Entities**: Important names, organizations, or products

EXAMPLES OF GOOD KEYWORDS:
✅ "data pipeline"
✅ "Apache Kafka" 
✅ "machine learning"
✅ "REST API"
✅ "database schema"
✅ "encryption"
✅ "load balancing"
✅ "microservices"

EXAMPLES OF POOR KEYWORDS (AVOID):
❌ "important concepts"
❌ "main ideas"
❌ "key principles"
❌ "various methods"
❌ "different approaches"

EXTRACTION STRATEGY:
- Look for repeated terms and concepts in the content
- Extract terms that seem central to the subject matter
- Include acronyms and technical abbreviations
- Focus on searchable, concrete terms rather than abstract concepts

CURRICULUM CONTEXT: {curriculum_name}

Return ONLY a JSON array of keyword strings:
["keyword1", "keyword2", "keyword3", ...]

No explanations, no formatting, just the JSON array."""),
                ("human", "Extract searchable keywords and terms from this content that can be used to find related material:\n\n{content}")
            ])
            
            chain = keyword_extraction_prompt | self.get_current_llm() | StrOutputParser()
            result = await chain.ainvoke({
                "content": content[:4000],  # Limit content to prevent token overflow
                "curriculum_name": curriculum_name
            })
            
            # Parse the JSON response
            keywords = self._parse_keywords_from_llm_response(result)
            
            if keywords and len(keywords) >= 3:
                logger.info(f"✅ Extracted {len(keywords)} searchable keywords from content")
                return keywords[:15]  # Limit to 15 keywords
            else:
                logger.warning(f"⚠️ LLM extraction returned insufficient keywords")
                return []
                
        except Exception as e:
            logger.error(f"❌ Error extracting keywords from content using LLM: {e}")
            return []

    def _parse_keywords_from_llm_response(self, llm_response: str) -> List[str]:
        """Parse keywords from LLM response with enhanced validation"""
        try:
            import json
            import re
            
            logger.info(f"🔍 Parsing keywords from LLM response: {llm_response[:200]}...")
            
            # Clean the response
            cleaned_response = llm_response.strip()
            
            # Remove markdown formatting
            if cleaned_response.startswith('```json'):
                cleaned_response = cleaned_response.replace('```json\n', '').replace('```json', '').replace('\n```', '').replace('```', '')
            elif cleaned_response.startswith('```'):
                cleaned_response = cleaned_response.replace('```\n', '').replace('```', '')
            
            # Find JSON array
            start_idx = cleaned_response.find('[')
            end_idx = cleaned_response.rfind(']')
            
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = cleaned_response[start_idx:end_idx+1]
                keywords = json.loads(json_str)
                
                # Enhanced keyword validation and cleaning
                clean_keywords = []
                for keyword in keywords:
                    if isinstance(keyword, str):
                        # Clean and validate the keyword
                        clean_keyword = keyword.strip().strip('"\'')
                        
                        # Validation criteria
                        if (len(clean_keyword) >= 2 and  # Minimum length
                            len(clean_keyword) <= 50 and  # Maximum length
                            not clean_keyword.lower() in ['the', 'and', 'or', 'but', 'a', 'an'] and  # Not stop words
                            not clean_keyword.lower().startswith('important') and  # Not generic terms
                            not clean_keyword.lower().startswith('main') and
                            not clean_keyword.lower().startswith('key') and
                            not clean_keyword.lower().startswith('various') and
                            clean_keyword.replace(' ', '').replace('-', '').replace('_', '').isalnum()):  # Alphanumeric + spaces/hyphens/underscores
                            
                            clean_keywords.append(clean_keyword)
                
                logger.info(f"📋 PARSED KEYWORDS: {clean_keywords}")
                return clean_keywords
            
            # Fallback: try to extract from plain text
            lines = cleaned_response.split('\n')
            keywords = []
            for line in lines:
                line = line.strip()
                # Look for patterns like "- keyword" or "1. keyword"
                keyword_match = re.match(r'^[\d\-\•\*\+]\s*\.?\s*(.+)$', line)
                if keyword_match:
                    keyword = keyword_match.group(1).strip().strip('"\'')
                    if len(keyword) > 2 and len(keyword) <= 50:
                        keywords.append(keyword)
            
            if keywords:
                logger.info(f"📋 FALLBACK PARSED KEYWORDS: {keywords}")
                return keywords[:15]
            
            logger.warning("⚠️ Could not parse keywords from LLM response")
            return []
            
        except Exception as e:
            logger.error(f"❌ Error parsing keywords from response: {e}")
            return []
        
    async def _search_book_embeddings(self, curriculum_name: str, book_title: str, query: str, k: int = 8) -> List[Dict[str, Any]]:
        """Search embeddings for a specific book within curriculum with smart topic extraction"""
        max_retries = 3
        retry_delay = 1  # seconds
        
        # Initialize search_query
        search_query = query
        
        # For comprehensive searches, enhance with extracted topics
        if "comprehensive book content" in query.lower() or "whole book" in query.lower():
            topics = await self._extract_book_topics(curriculum_name, book_title)
            # Create a focused search query from the extracted topics
            search_query = f"{query} {' '.join(topics)}"
            logger.info(f"🎯 Using enhanced search query with topics: {search_query}")
        
        for attempt in range(max_retries):
            try:
                logger.info(f"🔍 Searching book '{book_title}' in curriculum '{curriculum_name}' using search query: {search_query}")
                
                # First get the book_id from the book title
                book_info = await self._get_book_curriculum_info(book_title)
                if not book_info:
                    logger.warning(f"Book '{book_title}' not found, falling back to general search")
                    return await self._search_curriculum_embeddings(curriculum_name, query, k)
                
                logger.info(f"🔍 Book info retrieved: {book_info}")
                book_id = book_info.get('id')
                if not book_id:
                    logger.warning(f"Book ID not found for '{book_title}' in book_info: {book_info}, falling back to general search")
                    return await self._search_curriculum_embeddings(curriculum_name, query, k)
                
                # Generate embedding for the query
                query_embedding = None
                try:
                    query_embedding = await self.embeddings.aembed_query(query)
                except Exception as embed_err:
                    logger.error(f"❌ Error generating embedding for query: {embed_err}")
                    if attempt < max_retries - 1:
                        logger.info(f"🔄 Retrying embedding generation in {retry_delay} seconds")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        raise
                
                # Search specifically in this book's embeddings
                try:
                    results = await self.db.search_book_specific_embeddings(curriculum_name, book_id, query_embedding, limit=k)
                except asyncpg.exceptions.ConnectionDoesNotExistError:
                    if attempt < max_retries - 1:
                        logger.warning(f"Database connection lost, retrying in {retry_delay} seconds")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"Failed to connect to database after {max_retries} attempts")
                        return await self._search_curriculum_embeddings(curriculum_name, query, k)
                except asyncpg.exceptions.InFailedSQLTransactionError:
                    if attempt < max_retries - 1:
                        logger.warning(f"SQL transaction failed, retrying in {retry_delay} seconds")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        return await self._search_curriculum_embeddings(curriculum_name, query, k)
                
                if not results:
                    logger.warning(f"⚠️ No embeddings found for book '{book_title}' in curriculum '{curriculum_name}'")
                    # Try searching in curriculum-wide embeddings as fallback
                    logger.info(f"🔄 Attempting fallback to curriculum-wide search for '{book_title}'")
                    return await self._search_curriculum_embeddings(curriculum_name, query, k)
                
                logger.info(f"✅ Retrieved {len(results)} chunks from book '{book_title}' (ID: {book_id})")
                return results
                
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.error(f"❌ Error in book embedding search (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"❌ All attempts failed for book embedding search: {e}")
                    # Final fallback to general curriculum search
                    return await self._search_curriculum_embeddings(curriculum_name, query, k)
        
        logger.error(f"❌ All retries failed when searching book embeddings for '{book_title}'")
        return await self._search_curriculum_embeddings(curriculum_name, query, k)

    async def _search_book_embeddings_safe(self, book_title: str, curriculum_name: str, query: str, k: int = 8) -> List[Dict[str, Any]]:
        """Safe wrapper around _search_book_embeddings with error handling for TOC searches"""
        try:
            # Note: parameter order is different in the actual method
            return await self._search_book_embeddings(curriculum_name, book_title, query, k)
        except Exception as e:
            logger.warning(f"⚠️ Error in safe book embeddings search: {e}")
            return []

    @asynccontextmanager
    async def get_db_connection(self):
        """Get database connection from the database manager"""
        async with self.db.get_connection() as conn:
            yield conn

    def _create_curriculum_question_tool(self, curriculum_name: str, exam_parameters: Dict[str, Any]) -> Tool:
        """Create agent tool for generating questions from entire curriculum"""
        
        def generate_curriculum_questions(topic_query: str) -> str:
            try:
                import asyncio
                
                logger.info(f"🎯 CURRICULUM QUESTION TOOL: Generating questions for curriculum '{curriculum_name}' on topic '{topic_query}'")
                logger.info(f"📋 Parameters: {exam_parameters}")
                
                # Search curriculum embeddings
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, self._search_curriculum_embeddings(curriculum_name, topic_query, k=12))
                            results = future.result()
                    else:
                        results = loop.run_until_complete(self._search_curriculum_embeddings(curriculum_name, topic_query, k=12))
                except RuntimeError:
                    results = asyncio.run(self._search_curriculum_embeddings(curriculum_name, topic_query, k=12))
                
                if results:
                    # Get content from multiple books in curriculum
                    content_chunks = [r['content'] for r in results]
                    combined_content = "\n\n".join(content_chunks[:10])  # Limit to prevent context overflow
                    
                    return f"""CURRICULUM CONTENT RETRIEVED:
                    
Topic: {topic_query}
Curriculum: {curriculum_name}
Exam Parameters: {exam_parameters}

Content from curriculum books:
{combined_content}

Please generate {exam_parameters.get('count', 10)} exam questions based on this curriculum content with:
- Difficulty levels: {', '.join(exam_parameters.get('difficulty', ['medium']))}
- Question types: {', '.join(exam_parameters.get('question_types', ['multiple_choice_single_answer']))}
- Time limit: {exam_parameters.get('time_limit', 30)} minutes total
- Scope: Comprehensive curriculum coverage across multiple books"""
                else:
                    return f"No content found in curriculum '{curriculum_name}' for topic '{topic_query}'. Please try a different search term."
                    
            except Exception as e:
                logger.error(f"Error in curriculum question tool: {e}")
                return f"Error retrieving curriculum content: {str(e)}"
        
        return Tool(
            name="curriculum_question_generator",
            description=f"Generate exam questions from the entire '{curriculum_name}' curriculum covering all books and materials. Input should be a topic or subject area to focus on.",
            func=generate_curriculum_questions
        )

    def _create_book_question_tool(self, book_title: str, curriculum_name: str, exam_parameters: Dict[str, Any]) -> Tool:
        """Create agent tool for generating questions from specific book within curriculum"""
        
        def generate_book_questions(topic_query: str) -> str:
            try:
                import asyncio
                
                logger.info(f"📚 BOOK QUESTION TOOL: Generating questions for book '{book_title}' in curriculum '{curriculum_name}' on topic '{topic_query}'")
                logger.info(f"📋 Parameters: {exam_parameters}")
                
                # First get topics from the book structure
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, self._extract_book_topics(curriculum_name, book_title))
                            topics = future.result()
                    else:
                        topics = loop.run_until_complete(self._extract_book_topics(curriculum_name, book_title))
                except RuntimeError:
                    topics = asyncio.run(self._extract_book_topics(curriculum_name, book_title))
                
                if topics:
                    logger.info(f"📑 Using extracted book topics: {topics}")
                    search_query = " ".join(topics[:3])  # Use top 3 topics
                else:
                    search_query = topic_query if topic_query and topic_query.strip() else "introduction main concepts key principles"
                
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, self._search_book_embeddings(curriculum_name, book_title, search_query, k=8))
                            results = future.result()
                    else:
                        results = loop.run_until_complete(self._search_book_embeddings(curriculum_name, book_title, search_query, k=8))
                except RuntimeError:
                    results = asyncio.run(self._search_book_embeddings(curriculum_name, book_title, search_query, k=8))
                
                if results:
                    # Results are already filtered by book_id, so use them directly
                    content_chunks = [r['content'] for r in results]
                    combined_content = "\n\n".join(content_chunks[:8])
                    
                    logger.info(f"✅ CHUNK RETRIEVAL: Found {len(results)} relevant content chunks from '{book_title}' using search query: '{search_query}'")
                    logger.info(f"📝 CHUNK PREVIEW: First chunk preview: {content_chunks[0][:200]}..." if content_chunks else "No content in chunks")
                else:
                    logger.warning(f"⚠️ No content found for book '{book_title}' on topic '{topic_query}'")
                    combined_content = f"No specific content found for topic '{topic_query}' in book '{book_title}'. Please generate general questions about the topic."
                    
                return f"""BOOK CONTENT RETRIEVED:
                    
Book: {book_title}
Curriculum: {curriculum_name}
Topic: {topic_query}
Exam Parameters: {exam_parameters}

Content from "{book_title}":
{combined_content}

Please generate {exam_parameters.get('count', 10)} exam questions based specifically on this book content with:
- Difficulty levels: {', '.join(exam_parameters.get('difficulty', ['medium']))}
- Question types: {', '.join(exam_parameters.get('question_types', ['multiple_choice_single_answer']))}
- Time limit: {exam_parameters.get('time_limit', 30)} minutes total
- Scope: Focus specifically on "{book_title}" content"""
                    
            except Exception as e:
                logger.error(f"Error in book question tool: {e}")
                return f"Error retrieving book content: {str(e)}"
        
        return Tool(
            name="book_question_generator",
            description=f"Generate exam questions specifically from the book '{book_title}' within the '{curriculum_name}' curriculum. Input should be a topic or concept to focus on within this book.",
            func=generate_book_questions
        )

    def _create_topic_question_tool(self, book_title: str, curriculum_name: str, specific_topics: str, exam_parameters: Dict[str, Any]) -> Tool:
        """Create agent tool for generating questions on specific topics from a book"""
        
        def generate_topic_questions(search_query: str) -> str:
            try:
                import asyncio
                
                logger.info(f"🎯 TOPIC QUESTION TOOL: Generating questions for specific topics '{specific_topics}' in book '{book_title}'")
                logger.info(f"📋 Parameters: {exam_parameters}")
                
                # Use book-specific search with topic keywords
                search_query_enhanced = f"{specific_topics} {search_query}"
                
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, self._search_book_embeddings(curriculum_name, book_title, search_query_enhanced, k=8))
                            results = future.result()
                    else:
                        results = loop.run_until_complete(self._search_book_embeddings(curriculum_name, book_title, search_query_enhanced, k=8))
                except RuntimeError:
                    results = asyncio.run(self._search_book_embeddings(curriculum_name, book_title, search_query_enhanced, k=8))
                
                if results:
                    # Filter and prioritize results that match the specific topics
                    topic_keywords = [t.strip().lower() for t in specific_topics.split(',')]
                    scored_results = []
                    
                    for r in results:
                        content_lower = r.get('content', '').lower()
                        score = sum(1 for keyword in topic_keywords if keyword in content_lower)
                        scored_results.append((score, r))
                    
                    # Sort by relevance to topics
                    scored_results.sort(key=lambda x: x[0], reverse=True)
                    relevant_results = [r[1] for r in scored_results[:6]]
                    
                    content_chunks = [r['content'] for r in relevant_results]
                    combined_content = "\n\n".join(content_chunks)
                    
                    return f"""TOPIC-SPECIFIC CONTENT RETRIEVED:
                    
Book: {book_title}
Curriculum: {curriculum_name}
Specific Topics: {specific_topics}
Search Query: {search_query}
Exam Parameters: {exam_parameters}

Content related to specified topics:
{combined_content}

Please generate {exam_parameters.get('count', 10)} exam questions focused SPECIFICALLY on these topics: {specific_topics}
Requirements:
- Difficulty levels: {', '.join(exam_parameters.get('difficulty', ['medium']))}
- Question types: {', '.join(exam_parameters.get('question_types', ['multiple_choice_single_answer']))}
- Time limit: {exam_parameters.get('time_limit', 30)} minutes total
- Scope: Targeted assessment of the specified topics only"""
                else:
                    return f"No content found for topics '{specific_topics}' in book '{book_title}'. Please try broader search terms."
                    
            except Exception as e:
                logger.error(f"Error in topic question tool: {e}")
                return f"Error retrieving topic-specific content: {str(e)}"
        
        return Tool(
            name="topic_question_generator",
            description=f"Generate exam questions on specific topics '{specific_topics}' from the book '{book_title}'. Input should be related concepts or keywords to enhance topic coverage.",
            func=generate_topic_questions
        )



    def _create_web_search_tool(self) -> Tool:
        """Create web search tool using Tavily"""
        def web_search(query: str) -> str:
            try:
                tavily_api_key = os.getenv("TAVILY_API_KEY")
                if not tavily_api_key:
                    return "Web search is not available - API key not configured."
                
                # Use synchronous httpx client
                import httpx
                with httpx.Client() as client:
                    response = client.post(
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
                SELECT id, session_id, message_type, content, created_at
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
                        content=msg_data['content'],
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
                INSERT INTO chat_history (session_id, message_type, content, created_at)
                VALUES ($1, $2, $3, $4)
                RETURNING id, session_id, message_type, content, created_at
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
                    content=msg_data['content'],
                    created_at=msg_data['created_at']
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error saving message to history: {e}")
            return None
        """Generate questions using AI agents for curriculum, book, or topic-specific exams"""
        try:
            logger.info(f"🎯 AGENT-BASED QUESTION GENERATION STARTED")
            logger.info(f"Request: curriculum_id={request.curriculum_id}, book={request.book_title}, scope={request.scope_type}")
            logger.info(f"Parameters: count={request.count}, difficulty={request.difficulty}, types={request.question_types}")
            logger.info(f"Topics: {request.specific_topics}, Time: {request.time_limit}min")
            
            # Prepare exam parameters
            exam_parameters = {
                'count': request.count or 10,
                'difficulty': request.difficulty or ['medium'],
                'question_types': request.question_types or ['multiple_choice_single_answer'],
                'time_limit': request.time_limit or 30,
                'user_message': request.user_message or '',
                'specific_topics': request.specific_topics or ''
            }
            
            # Case 1: Whole Curriculum Exam
            if request.scope_type == 'whole_curriculum' and request.curriculum_id:
                logger.info("🌟 CASE 1: Generating questions for WHOLE CURRICULUM")
                
                # Get curriculum information
                curriculum_info = await self.db.get_curriculum_by_id(int(request.curriculum_id))
                if not curriculum_info:
                    raise ValueError(f"Curriculum with ID {request.curriculum_id} not found")
                
                curriculum_name = curriculum_info['name']
                
                # Call agent-based curriculum question generation
                all_questions = await self._generate_questions_with_curriculum_agent(
                    curriculum_name, exam_parameters
                )
                
                logger.info(f"✅ Generated {len(all_questions)} questions for curriculum {curriculum_name}")
                
                return QuestionResponse(
                    chapter=f"{curriculum_name} Curriculum - Comprehensive Exam",
                    questions_generated=all_questions
                )
            
            # Case 2: Single Book Exam
            elif request.scope_type == 'whole_book' and request.book_title:
                logger.info("📚 CASE 2: Generating questions for SINGLE BOOK")
                
                # Get curriculum context for the book
                book_info = await self._get_book_curriculum_info(request.book_title)
                curriculum_name = book_info.get('curriculum_name') if book_info else 'IT Curriculum'
                
                # Call agent-based book question generation
                all_questions = await self._generate_questions_with_book_agent(
                    request.book_title, curriculum_name, exam_parameters
                )
                
                logger.info(f"✅ Generated {len(all_questions)} questions for book {request.book_title}")
                
                return QuestionResponse(
                    chapter=f"{request.book_title} - Comprehensive Book Exam",
                    questions_generated=all_questions
                )
            
            # Case 3: Specific Topics Exam
            elif request.scope_type == 'specific_topics' and request.specific_topics:
                logger.info("🎯 CASE 3: Generating questions for SPECIFIC TOPICS")
                
                # Get curriculum context for the book
                book_title = request.book_title or 'General Book'
                book_info = await self._get_book_curriculum_info(book_title)
                curriculum_name = book_info.get('curriculum_name') if book_info else 'IT Curriculum'
                
                # Call agent-based topic question generation
                all_questions = await self._generate_questions_with_topic_agent(
                    book_title, curriculum_name, request.specific_topics, exam_parameters
                )
                
                logger.info(f"✅ Generated {len(all_questions)} questions for topics: {request.specific_topics}")
                
                return QuestionResponse(
                    chapter=f"{book_title} - {request.specific_topics}",
                    questions_generated=all_questions
                )
            
            else:
                # Fallback: Default to book-based generation
                logger.info("🔄 FALLBACK: Using book-based generation")
                book_title = request.book_title or 'General Content'
                book_info = await self._get_book_curriculum_info(book_title)
                curriculum_name = book_info.get('curriculum_name') if book_info else 'IT Curriculum'
                
                all_questions = await self._generate_questions_with_book_agent(
                    book_title, curriculum_name, exam_parameters
                )
                
                return QuestionResponse(
                    chapter=f"{book_title} - General Exam",
                    questions_generated=all_questions
                )
            
        except Exception as e:
            logger.error(f"❌ Error in agent-based question generation: {e}")
            raise



    async def _generate_questions_with_curriculum_agent(self, curriculum_name: str, exam_parameters: Dict[str, Any]) -> List[Question]:
        """
        ENHANCED Case 1: Systematic curriculum-wide question generation
        Following the proven 3-step methodology like Cases 2 & 3
        """
        try:
            logger.info(f"🌟 CASE 1 ENHANCED START: Comprehensive curriculum generation for '{curriculum_name}'")
            
            # STEP 1: Extract comprehensive topics from entire curriculum
            logger.info(f"🔍 STEP 1: Extracting comprehensive topics from entire curriculum")
            curriculum_topics = await self._extract_curriculum_wide_topics(curriculum_name)
            
            if not curriculum_topics:
                logger.warning(f"⚠️ No topics extracted, using dynamic random chunk extraction")
                curriculum_topics = await self._extract_keywords_from_random_chunks(curriculum_name)
            
            logger.info(f"✅ STEP 1 DONE: Found {len(curriculum_topics)} curriculum topics: {curriculum_topics}")
            
            # STEP 2: Get chunks for curriculum topics across all books
            logger.info(f"🔍 STEP 2: Getting content chunks for curriculum topics")
            all_chunks = await self._get_chunks_for_curriculum_topics(curriculum_name, curriculum_topics)
            
            if not all_chunks:
                logger.error(f"❌ STEP 2 FAILED: No chunks found for curriculum topics")
                return self._generate_default_questions(exam_parameters, curriculum_topics)
            
            logger.info(f"✅ STEP 2 DONE: Retrieved {len(all_chunks)} chunks from curriculum")
            
            # STEP 3: Generate comprehensive questions from curriculum content
            logger.info(f"📝 STEP 3: Generating comprehensive curriculum questions")
            questions = await self._generate_comprehensive_curriculum_questions(
                curriculum_name, all_chunks, curriculum_topics, exam_parameters
            )
            
            if questions and len(questions) >= exam_parameters.get('count', 5):
                logger.info(f"✅ STEP 3 DONE: Generated {len(questions)} comprehensive questions")
                return questions[:exam_parameters.get('count', 5)]
            else:
                logger.warning(f"⚠️ Insufficient questions generated, using fallback")
                return self._generate_default_questions(exam_parameters, curriculum_topics)
                
        except Exception as e:
            logger.error(f"❌ CASE 1 ENHANCED ERROR: {e}")
            return self._generate_default_questions(exam_parameters, [curriculum_name])

    async def _extract_curriculum_wide_topics(self, curriculum_name: str) -> List[str]:
        """
        CRITICAL: Extract comprehensive topics from entire curriculum
        Uses multiple strategies for maximum coverage
        """
        try:
            logger.info(f"🌟 STEP 1: Extracting comprehensive topics from entire curriculum '{curriculum_name}'")
            
            all_topics = []
            
            # METHOD 1: Extract topics from all books' TOCs
            curriculum_topics = await self._extract_topics_from_all_books_toc(curriculum_name)
            all_topics.extend(curriculum_topics)
            
            # METHOD 2: Search for curriculum overview/syllabus content
            overview_topics = await self._extract_topics_from_curriculum_overview(curriculum_name)
            all_topics.extend(overview_topics)
            
            # METHOD 3: Content-based keyword analysis across all books
            content_keywords = await self._extract_topics_from_curriculum_content(curriculum_name)
            all_topics.extend(content_keywords)
            
            # METHOD 4: Dynamic random chunk analysis (REPLACES domain-specific topics)
            random_chunk_keywords = await self._extract_keywords_from_random_chunks(curriculum_name)
            all_topics.extend(random_chunk_keywords)
            
            # Deduplicate, rank, and filter to get the best topics
            final_topics = await self._deduplicate_and_rank_curriculum_topics(all_topics, curriculum_name)
            
            logger.info(f"✅ CURRICULUM TOPICS EXTRACTED: {len(final_topics)} comprehensive topics")
            logger.info(f"📋 Topics: {final_topics}")
            
            return final_topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting curriculum-wide topics: {e}")
            # UPDATED FALLBACK: Use dynamic extraction instead of fixed topics
            return await self._extract_keywords_from_random_chunks(curriculum_name)

    async def _extract_topics_from_all_books_toc(self, curriculum_name: str) -> List[str]:
        """Extract topics from table of contents of ALL books in curriculum"""
        try:
            logger.info(f"📚 METHOD 1: Extracting topics from all books' TOCs in '{curriculum_name}'")
            
            # Get all books in curriculum
            curriculum_info = await self.db.get_curriculum_by_name(curriculum_name)
            if not curriculum_info:
                return []
            
            books = await self.db.get_books_by_curriculum(curriculum_info['id'])
            logger.info(f"📖 Found {len(books)} books in curriculum '{curriculum_name}'")
            
            all_book_topics = []
            
            for book in books:
                book_title = book['title']
                logger.info(f"📄 Extracting topics from book: {book_title}")
                
                # Use existing TOC extraction method for each book
                book_topics = await self._extract_book_topics(curriculum_name, book_title)
                if book_topics:
                    all_book_topics.extend(book_topics)
                    logger.info(f"✅ Extracted {len(book_topics)} topics from '{book_title}'")
            
            logger.info(f"📚 TOC METHOD: Total {len(all_book_topics)} topics from all books")
            return all_book_topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting topics from all books' TOCs: {e}")
            return []

    async def _extract_topics_from_curriculum_overview(self, curriculum_name: str) -> List[str]:
        """Search for and analyze curriculum overview, syllabus, or course outline"""
        try:
            logger.info(f"📋 METHOD 2: Searching for curriculum overview content")
            
            # Search for curriculum-level overview content
            overview_queries = [
                "curriculum overview syllabus course outline",
                "program structure learning objectives",
                "course description main topics areas",
                "curriculum framework key subjects",
                "study plan academic program overview"
            ]
            
            overview_chunks = []
            for query in overview_queries:
                chunks = await self._search_curriculum_embeddings(curriculum_name, query, k=5)
                if chunks:
                    overview_chunks.extend(chunks)
                    logger.info(f"✅ Found {len(chunks)} chunks for overview query: '{query}'")
            
            if not overview_chunks:
                logger.warning("⚠️ No curriculum overview content found")
                return []
            
            # Extract topics from overview content using LLM
            overview_content = "\n\n".join([chunk['content'] for chunk in overview_chunks[:10]])
            topics = await self._extract_topics_from_overview_content(overview_content, curriculum_name)
            
            logger.info(f"📋 OVERVIEW METHOD: Extracted {len(topics)} topics from curriculum overview")
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting topics from curriculum overview: {e}")
            return []

    async def _extract_topics_from_curriculum_content(self, curriculum_name: str) -> List[str]:
        """Analyze content across all books to extract searchable keywords and terms"""
        try:
            logger.info(f"📊 METHOD 3: Content analysis across entire curriculum for searchable keywords")
            
            # Get diverse content samples from across the curriculum
            content_queries = [
                "introduction fundamentals principles",
                "advanced topics concepts methods",
                "practical applications examples",
                "key theories important concepts",
                "main subjects core areas"
            ]
            
            all_content = []
            for query in content_queries:
                chunks = await self._search_curriculum_embeddings(curriculum_name, query, k=8)
                if chunks:
                    all_content.extend([chunk['content'] for chunk in chunks])
            
            if not all_content:
                logger.warning("⚠️ No content found for keyword analysis")
                return []
            
            # Use LLM to analyze content and extract searchable keywords
            combined_content = "\n\n".join(all_content[:15])  # Limit to prevent overflow
            keywords = await self._extract_keywords_from_content_llm(combined_content, curriculum_name)
            
            logger.info(f"📊 CONTENT METHOD: Extracted {len(keywords)} searchable keywords from content analysis")
            return keywords
            
        except Exception as e:
            logger.error(f"❌ Error extracting topics from curriculum content: {e}")
            return []

    async def _extract_topics_from_overview_content(self, overview_content: str, curriculum_name: str) -> List[str]:
        """Extract topics from curriculum overview content using LLM"""
        try:
            logger.info(f"🔍 Analyzing overview content for curriculum topics")
            
            topic_extraction_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are an expert curriculum analyzer. Extract comprehensive academic topics from the provided curriculum overview content.

REQUIREMENTS:
- Extract 10-15 major academic topics/subjects from the content
- Focus on specific subject areas, not general concepts
- Return topics that would appear in an academic curriculum
- Use clear, professional terminology
- Each topic should be 2-6 words

CURRICULUM TYPE: {curriculum_name}

Return ONLY a JSON array of topic strings, no explanations:
["Topic 1", "Topic 2", "Topic 3", ...]"""),
                ("human", "Extract major academic topics from this curriculum overview content:\n\n{content}")
            ])
            
            chain = topic_extraction_prompt | self.get_current_llm() | StrOutputParser()
            result = await chain.ainvoke({
                "content": overview_content[:4000],  # Limit content size
                "curriculum_name": curriculum_name
            })
            
            # Parse JSON response
            topics = self._parse_topics_from_llm_response(result)
            logger.info(f"✅ Extracted {len(topics)} topics from overview content")
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting topics from overview content: {e}")
            return []

    async def _analyze_content_for_topics(self, content: str, curriculum_name: str) -> List[str]:
        """Analyze curriculum content to extract major topics and themes"""
        try:
            logger.info(f"🔍 Analyzing curriculum content for major topics")
            
            topic_analysis_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are an expert content analyzer. Analyze the provided curriculum content and extract the main academic topics and subject areas.

REQUIREMENTS:
- Extract 8-12 major topics/themes from the content
- Focus on specific subject areas and key concepts
- Use professional academic terminology
- Each topic should be 2-6 words
- Prioritize topics that appear frequently or are emphasized

CURRICULUM TYPE: {curriculum_name}

Return ONLY a JSON array of topic strings:
["Topic 1", "Topic 2", "Topic 3", ...]"""),
                ("human", "Analyze this curriculum content and extract major academic topics:\n\n{content}")
            ])
            
            chain = topic_analysis_prompt | self.get_current_llm() | StrOutputParser()
            result = await chain.ainvoke({
                "content": content[:5000],  # Limit content size
                "curriculum_name": curriculum_name
            })
            
            # Parse JSON response
            topics = self._parse_topics_from_llm_response(result)
            logger.info(f"✅ Extracted {len(topics)} topics from content analysis")
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error analyzing content for topics: {e}")
            return []

    async def _deduplicate_and_rank_curriculum_topics(self, all_topics: List[str], curriculum_name: str) -> List[str]:
        """Smart deduplication and ranking of curriculum topics"""
        try:
            import re
            from collections import Counter
            
            logger.info(f"🔧 Deduplicating and ranking {len(all_topics)} topics")
            
            # Normalize topics for comparison
            normalized_topics = {}
            for topic in all_topics:
                if topic and len(topic.strip()) > 2:
                    # Normalize: lowercase, remove extra spaces, basic cleanup
                    normalized = re.sub(r'\s+', ' ', topic.lower().strip())
                    normalized = re.sub(r'[^\w\s-]', '', normalized)
                    
                    if len(normalized) > 3:  # Minimum topic length
                        normalized_topics[normalized] = topic
            
            # Count frequency of normalized topics
            topic_counts = Counter(normalized_topics.keys())
            
            # Get top topics by frequency
            top_topics = []
            for normalized_topic, count in topic_counts.most_common(20):
                if len(top_topics) < 15:  # Limit to 15 topics
                    original_topic = normalized_topics[normalized_topic]
                    top_topics.append(original_topic)
            
            # Ensure we have at least some topics
            if not top_topics:
                top_topics = (await self._extract_keywords_from_random_chunks(curriculum_name))[:10]
            
            logger.info(f"✅ Final topics after deduplication: {len(top_topics)}")
            return top_topics
            
        except Exception as e:
            logger.error(f"❌ Error deduplicating topics: {e}")
            return all_topics[:15] if all_topics else []

    async def _get_chunks_for_curriculum_topics(self, curriculum_name: str, topics: List[str]) -> List[Dict[str, Any]]:
        """Get content chunks for curriculum topics across all books"""
        try:
            logger.info(f"🔍 Getting chunks for {len(topics)} curriculum topics")
            
            all_chunks = []
            
            for i, topic in enumerate(topics[:10]):  # Limit to prevent overload
                logger.info(f"📄 STEP 2.{i+1}: Getting chunks for '{topic[:30]}...'")
                
                # Search for chunks related to this topic
                chunks = await self._search_curriculum_embeddings(curriculum_name, topic, k=3)
                if chunks:
                    all_chunks.extend(chunks)
                    logger.info(f"✅ Found {len(chunks)} chunks for '{topic[:30]}...'")
            
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

    async def _generate_comprehensive_curriculum_questions(self, curriculum_name: str, chunks: List[Dict[str, Any]], topics: List[str], exam_parameters: Dict[str, Any]) -> List[Question]:
        """Generate comprehensive questions from curriculum content"""
        try:
            logger.info(f"📝 Generating comprehensive questions from {len(chunks)} curriculum chunks")
            
            # Combine chunks into comprehensive content
            combined_content = "\n\n".join([chunk['content'] for chunk in chunks])
            topics_str = ", ".join(topics[:8])  # Use first 8 topics
            
            # Generate questions using existing method
            questions = await self._generate_questions_from_content(
                content=combined_content,
                topic=f"{curriculum_name} curriculum covering: {topics_str}",
                exam_parameters=exam_parameters
            )
            
            logger.info(f"✅ Generated {len(questions)} comprehensive curriculum questions")
            return questions
            
        except Exception as e:
            logger.error(f"❌ Error generating comprehensive curriculum questions: {e}")
            return []

    def _parse_topics_from_llm_response(self, llm_response: str) -> List[str]:
        """Parse topics from LLM response (JSON array format)"""
        try:
            import json
            import re
            
            # Clean the response
            cleaned_response = llm_response.strip()
            
            # Remove markdown formatting
            if cleaned_response.startswith('```json'):
                cleaned_response = cleaned_response.replace('```json\n', '').replace('```json', '').replace('\n```', '').replace('```', '')
            elif cleaned_response.startswith('```'):
                cleaned_response = cleaned_response.replace('```\n', '').replace('```', '')
            
            # Find JSON array
            start_idx = cleaned_response.find('[')
            end_idx = cleaned_response.rfind(']')
            
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = cleaned_response[start_idx:end_idx+1]
                topics = json.loads(json_str)
                
                # Filter and clean topics
                clean_topics = []
                for topic in topics:
                    if isinstance(topic, str) and len(topic.strip()) > 2:
                        clean_topic = topic.strip()
                        if len(clean_topic) <= 100:  # Reasonable length limit
                            clean_topics.append(clean_topic)
                
                logger.info(f"✅ Parsed {len(clean_topics)} topics from LLM response")
                return clean_topics
            
            # Fallback: try to extract topics from text
            lines = cleaned_response.split('\n')
            topics = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and len(line) > 2 and len(line) < 100:
                    # Remove quotes and clean up
                    clean_line = re.sub(r'^["\'\-\*\d\.\s]+', '', line)
                    clean_line = re.sub(r'["\'\,\s]+$', '', clean_line)
                    if clean_line:
                        topics.append(clean_line)
            
            return topics[:15]  # Limit to reasonable number
            
        except Exception as e:
            logger.error(f"❌ Error parsing topics from LLM response: {e}")
            return []

    async def _generate_questions_with_book_agent(self, book_title: str, curriculum_name: str, exam_parameters: Dict[str, Any]) -> List[Question]:
        """Case 2: Generate questions for whole book using simplified direct approach"""
        try:
            logger.info(f"📚 CASE 2 START: '{book_title}' in curriculum '{curriculum_name}'")
            
            # STEP 1: Extract topics from book content
            logger.info(f"🔍 STEP 1: Extracting topics from book")
            topics = await self._extract_book_topics(curriculum_name, book_title)
            
            if not topics:
                logger.warning(f"⚠️ No topics extracted, using dynamic random chunk extraction")
                topics = await self._extract_keywords_from_random_chunks(curriculum_name, book_title)
            
            logger.info(f"✅ STEP 1 DONE: Found topics: {', '.join(topics[:5])}...")
            
            # STEP 2: Get chunks for topics (with safe connection handling)
            logger.info(f"🔍 STEP 2: Getting content chunks for topics")
            all_chunks = []
            
            # Get book info once
            book_info = None
            try:
                book_info = await self._get_book_curriculum_info(book_title)
                if book_info:
                    actual_curriculum = book_info.get('curriculum_name', curriculum_name)
                    book_id = book_info.get('id')
                    logger.info(f"📚 Book found: ID={book_id}, curriculum='{actual_curriculum}'")
                else:
                    logger.warning(f"⚠️ Book '{book_title}' not found in database")
            except Exception as e:
                logger.warning(f"⚠️ Error getting book info: {e}")
            
            # Try to get chunks for each topic
            for i, topic in enumerate(topics[:6], 1):  # Limit to 6 topics
                try:
                    logger.info(f"📄 STEP 2.{i}: Getting chunks for '{topic[:30]}...'")
                    
                    if book_info:
                        # Try book-specific search first
                        chunks = await self._search_book_embeddings(actual_curriculum, book_title, topic, k=3)
                    else:
                        # Fallback to curriculum search
                        chunks = await self._search_curriculum_embeddings(curriculum_name, topic, k=3)
                    
                    if chunks:
                        logger.info(f"✅ Found {len(chunks)} chunks for '{topic[:30]}...'")
                        all_chunks.extend(chunks)
                    else:
                        logger.info(f"⚠️ No chunks for '{topic[:30]}...'")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Error getting chunks for '{topic}': {e}")
                    continue
            
            if not all_chunks:
                logger.error(f"❌ STEP 2 FAILED: No chunks found for any topics")
                return self._generate_default_questions(exam_parameters, topics)
            
            logger.info(f"✅ STEP 2 DONE: Retrieved {len(all_chunks)} total chunks")
            
            # STEP 3: Generate questions from real content (direct, no agent)
            logger.info(f"� STEP 3: Generating questions from real content")
            
            combined_content = "\n\n".join([chunk.get('content', '') for chunk in all_chunks])
            content_length = len(combined_content)
            
            if content_length < 100:
                logger.warning(f"⚠️ Very little content ({content_length} chars), falling back to defaults")
                return self._generate_default_questions(exam_parameters, topics)
            
            logger.info(f"📝 Using {content_length} characters of real content")
            
            # Generate questions directly from content
            questions = await self._generate_questions_from_content(
                content=combined_content[:8000],  # Limit to avoid token limits
                topic=f"{book_title} content covering: {', '.join(topics[:3])}",
                exam_parameters=exam_parameters
            )
            
            if questions and len(questions) >= exam_parameters.get('count', 5):
                logger.info(f"✅ STEP 3 DONE: Generated {len(questions)} questions from real content")
                return questions[:exam_parameters.get('count', 5)]
            else:
                logger.warning(f"⚠️ STEP 3 PARTIAL: Only got {len(questions) if questions else 0} questions")
                
                # If we have some questions but not enough, supplement with defaults
                if questions:
                    needed = exam_parameters.get('count', 5) - len(questions)
                    defaults = self._generate_default_questions({'count': needed, **exam_parameters}, topics)
                    return questions + defaults
                else:
                    return self._generate_default_questions(exam_parameters, topics)
            
        except Exception as e:
            logger.error(f"❌ CASE 2 ERROR: {e}")
            import traceback
            logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
            return self._generate_default_questions(exam_parameters, [curriculum_name])

    async def _generate_questions_with_topic_agent(self, book_title: str, curriculum_name: str, specific_topics: str, exam_parameters: Dict[str, Any]) -> List[Question]:
        """Generate questions by directly retrieving chunks for specific topics and creating questions"""
        logger.info(f"🎯 DIRECT TOPIC SEARCH: Generating questions for topics '{specific_topics}' in book '{book_title}'")
        
        try:
            # Step 1: Enhanced book information retrieval with fallback
            logger.info(f"🔍 STEP 1: Looking up book information for '{book_title}'")
            book_info = await self._get_book_curriculum_info(book_title)
            
            if not book_info:
                logger.warning(f"⚠️ Book '{book_title}' not found in database, trying curriculum-wide search")
                # Fallback: Search entire curriculum instead of specific book
                chunks = await self._search_curriculum_embeddings(curriculum_name, specific_topics, k=8)
                if chunks:
                    logger.info(f"✅ FALLBACK SUCCESS: Found {len(chunks)} chunks from curriculum '{curriculum_name}'")
                else:
                    logger.error(f"❌ No content found in curriculum '{curriculum_name}' for topics '{specific_topics}'")
                    return self._generate_default_questions(exam_parameters, [specific_topics])
            else:
                actual_curriculum = book_info.get('curriculum_name', curriculum_name)
                book_id = book_info.get('id')
                logger.info(f"✅ BOOK FOUND: ID={book_id}, curriculum='{actual_curriculum}'")
                
                # Step 2: Enhanced search with detailed logging
                logger.info(f"🔍 STEP 2: Searching for content on '{specific_topics}' in book '{book_title}'")
                
                # Create enhanced search query
                search_query = specific_topics.replace(',', ' ')
                logger.info(f"📝 Using search query: '{search_query}'")
                
                # Search specifically in this book for the topics
                chunks = await self._search_book_embeddings(actual_curriculum, book_title, search_query, k=8)
                
                if not chunks:
                    logger.warning(f"⚠️ No chunks from book '{book_title}', trying curriculum-wide search")
                    chunks = await self._search_curriculum_embeddings(actual_curriculum, search_query, k=8)
                    if chunks:
                        logger.info(f"✅ CURRICULUM FALLBACK: Found {len(chunks)} chunks from curriculum '{actual_curriculum}'")
            
            # Verify we have chunks
            if not chunks:
                logger.error(f"❌ NO CHUNKS FOUND: Could not retrieve any content for topics '{specific_topics}'")
                return self._generate_default_questions(exam_parameters, [specific_topics])
            
            # Step 3: Log chunk details for verification
            logger.info(f"✅ CHUNKS RETRIEVED: Found {len(chunks)} relevant chunks for topics '{specific_topics}'")
            for i, chunk in enumerate(chunks[:3]):  # Log first 3 chunks
                content_preview = chunk.get('content', '')[:150] + "..." if len(chunk.get('content', '')) > 150 else chunk.get('content', '')
                logger.info(f"📄 CHUNK {i+1}: {content_preview}")
            
            # Step 4: Combine content and generate questions
            combined_content = "\n\n".join([chunk['content'] for chunk in chunks])
            logger.info(f"📝 COMBINED CONTENT: {len(combined_content)} characters total")
            
            if len(combined_content) < 100:
                logger.warning(f"⚠️ Very short content ({len(combined_content)} chars), may not generate good questions")
            
            # Create questions using the content
            logger.info(f"🎯 STEP 3: Generating {exam_parameters['count']} questions from retrieved content")
            questions = await self._generate_questions_from_content(
                content=combined_content,
                topic=specific_topics,
                exam_parameters=exam_parameters
            )
            
            if questions and len(questions) >= exam_parameters['count']:
                logger.info(f"✅ SUCCESS: Generated {len(questions)} questions from actual content for '{specific_topics}'")
                return questions[:exam_parameters['count']]  # Return exact count requested
            else:
                logger.warning(f"⚠️ GENERATION FAILED: Expected {exam_parameters['count']}, got {len(questions) if questions else 0}")
                logger.warning(f"🔄 Falling back to default questions")
                return self._generate_default_questions(exam_parameters, [specific_topics])
            
        except Exception as e:
            logger.error(f"❌ ERROR in direct topic question generation: {e}")
            import traceback
            logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
            return self._generate_default_questions(exam_parameters, [specific_topics])

    async def _generate_questions_from_content(self, content: str, topic: str, exam_parameters: Dict[str, Any]) -> List[Question]:
        """Generate questions directly from content without using agents"""
        try:
            logger.info(f"📝 DIRECT GENERATION: Creating {exam_parameters['count']} questions about '{topic}' from {len(content)} chars of content")
            
            # Validate content is not empty
            if not content or len(content.strip()) < 50:
                logger.error(f"❌ Content too short ({len(content)} chars) or empty, cannot generate quality questions")
                return []
            
            # Log content preview for verification
            content_preview = content[:300] + "..." if len(content) > 300 else content
            logger.info(f"📄 CONTENT PREVIEW: {content_preview}")
            
            # Prepare parameters
            difficulty = exam_parameters.get('difficulty', ['medium'])[0]
            question_type = exam_parameters.get('question_types', ['multiple_choice_single_answer'])[0]
            count = exam_parameters.get('count', 10)
            
            logger.info(f"🎯 GENERATION PARAMS: {count} questions, difficulty={difficulty}, type={question_type}")
            
            # IMPROVED PROMPT - More explicit about forbidden phrases
            question_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are a professional exam creator. Generate EXACTLY {count} technical exam questions based ONLY on the provided content.

CRITICAL REQUIREMENTS:
- Generate EXACTLY {count} questions
- Difficulty: {difficulty}
- Question Type: {question_type}
- Base questions ONLY on the provided content

STRICTLY FORBIDDEN PHRASES - DO NOT USE:
❌ "According to the content"
❌ "According to the text" 
❌ "As described in Chapter X"
❌ "What does Chapter X cover"
❌ "Chapter X primarily covers"
❌ "As mentioned in the book"
❌ "The course book states"
❌ "Based on the provided content"
❌ "Referencing the material"
❌ "As stated in"
❌ "According to"
❌ "The text mentions"
❌ "The content describes"

REQUIRED QUESTION STYLE:
✅ Write direct technical questions about concepts
✅ Ask about processes, tools, and techniques directly
✅ Use straightforward professional language
✅ Make questions sound like certification exams

GOOD EXAMPLES:
✅ "What is the primary role of data engineers?"
✅ "Which Python library is best for data manipulation?"
✅ "What are the main stages of ETL processing?"
✅ "Which tool is used for big data processing?"

BAD EXAMPLES (DO NOT USE):
❌ "According to the content, what is the primary role of data engineers?"
❌ "What does Chapter 2 primarily cover?"
❌ "As described in the text, which library..."

JSON FORMAT:
Return a JSON array with {count} question objects:
- "difficulty": "{difficulty}"
- "type": "{question_type}"  
- "question_text": "Direct technical question (NO source references)"
- "options": ["Option A", "Option B", "Option C", "Option D"] (for multiple choice)
- "answer": "Correct answer from options"

Focus on technical concepts from the content but write questions like a professional certification exam."""),
                ("human", """Content to analyze:
{content}

Generate {count} {difficulty} {question_type} questions about data engineering concepts. 

REMEMBER: Write direct technical questions WITHOUT any references to "content", "text", "book", "chapter", etc. Make them sound professional and exam-appropriate.

Return ONLY the JSON array, no additional text or formatting.""")
            ])
            
            chain = question_prompt | self.get_current_llm() | StrOutputParser()
            
            logger.info(f"🚀 SENDING TO LLM: Generating {count} questions from content")
            result = await chain.ainvoke({
                "topic": topic,
                "content": content,
                "count": count,
                "difficulty": difficulty,
                "question_type": question_type
            })
            
            logger.info(f"🔍 LLM Response received: {len(result)} characters")
            logger.info(f"🔍 LLM Response preview: {result[:200]}...")
            
            # Parse the JSON response with enhanced error handling
            try:
                # Clean the response more thoroughly
                cleaned_result = result.strip()
                
                # Remove common markdown formatting
                if cleaned_result.startswith('```json'):
                    cleaned_result = cleaned_result.replace('```json\n', '').replace('```json', '').replace('\n```', '').replace('```', '')
                elif cleaned_result.startswith('```'):
                    cleaned_result = cleaned_result.replace('```\n', '').replace('```', '')
                
                # Remove any trailing text after the JSON
                if '```' in cleaned_result:
                    cleaned_result = cleaned_result.split('```')[0]
                
                # Try to find JSON array boundaries
                start_idx = cleaned_result.find('[')
                end_idx = cleaned_result.rfind(']')
                
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    cleaned_result = cleaned_result[start_idx:end_idx+1]
                
                logger.info(f"🧹 CLEANED JSON: {cleaned_result[:200]}...")
                
                questions_data = json.loads(cleaned_result)
                
                if not isinstance(questions_data, list):
                    logger.error("❌ Response is not a JSON array")
                    return []
                
                logger.info(f"✅ JSON PARSED: Found {len(questions_data)} question objects")
                
                # Convert to Question objects with validation
                questions = []
                for i, q_data in enumerate(questions_data):
                    if not isinstance(q_data, dict):
                        logger.warning(f"⚠️ Question {i+1} is not a dict, skipping")
                        continue
                    
                    # Validate required fields
                    if not q_data.get('question_text'):
                        logger.warning(f"⚠️ Question {i+1} missing question_text, skipping")
                        continue
                    
                    # Clean the question text to remove unwanted references
                    question_text = q_data.get('question_text', '')
                    question_text = self._remove_book_references(question_text)
                    
                    question = Question(
                        difficulty=q_data.get('difficulty', difficulty),
                        type=q_data.get('type', question_type),
                        question_text=question_text,
                        options=q_data.get('options', []),
                        answer=str(q_data.get('answer', ''))
                    )
                    questions.append(question)
                    logger.info(f"✅ Question {i+1}: {question.question_text[:100]}...")
                
                if len(questions) == count:
                    logger.info(f"🎉 SUCCESS: Generated exactly {len(questions)} questions from content")
                elif len(questions) > 0:
                    logger.warning(f"⚠️ Generated {len(questions)} questions, expected {count}")
                else:
                    logger.error("❌ No valid questions generated")
                
                return questions[:count]  # Ensure we don't exceed the requested count
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON parsing error: {e}")
                logger.error(f"❌ Raw response that failed to parse: {result}")
                return []
            
        except Exception as e:
            logger.error(f"❌ Error generating questions from content: {e}")
            import traceback
            logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
            return []
            




    def _remove_book_references(self, question_text: str) -> str:
        """Remove book name references and guide titles from question text"""
        try:
            import re
            
            # Enhanced patterns to remove unwanted phrases
            patterns_to_remove = [
                # "According to" patterns
                r'(?:according to|as described in|referencing|detailed in|from|in)\s+(?:the\s+)?(?:content|text|book|material|course\s+book)[,\s]*',
                r'(?:according to|as described in|referencing|detailed in|from|in)\s+(?:the\s+)?chapter\s+\d+[,\s]*',
                r'according\s+to\s+the[^,.?]*[,\s]*',
                r'as\s+(?:mentioned|stated|described)\s+in[^,.?]*[,\s]*',
                r'based\s+on\s+the\s+provided[^,.?]*[,\s]*',
                
                # Chapter references
                r'(?:what does|what is)\s+chapter\s+\d+.*?(?:cover|describe|focus on)[,\s]*',
                r'chapter\s+\d+\s+(?:of\s+the\s+)?(?:course\s+)?book[,\s]*',
                r'(?:as\s+described\s+in\s+)?chapter\s+\d+[,\s]*',
                
                # Content references
                r'the\s+content\s+(?:describes|mentions|states)[,\s]*',
                r'the\s+text\s+(?:describes|mentions|states)[,\s]*',
                r'the\s+(?:course\s+)?book\s+(?:describes|mentions|states)[,\s]*',
                
                # Book/guide references
                r'(?:according to|as described in|referencing|detailed in|from|in)\s+(?:the\s+)?[A-Z_][A-Z0-9_]*(?:\s+[A-Z_][A-Z0-9_]*)*(?:\s+GUIDE?|HANDBOOK|MANUAL|BOOK)?[,\s]*',
                r'(?:according to|as described in|referencing|detailed in|from|in)\s+(?:the\s+)?\"[^\"]+\"[,\s]*',
                r'(?:according to|as described in|referencing|detailed in|from|in)\s+(?:the\s+)?\'[^\']+\'[,\s]*',
                
                # Other reference patterns
                r'[,\s]*referencing considerations detailed in[^,.?]*[,\s]*',
                r'[,\s]*as outlined in[^,.?]*[,\s]*',
                r'[,\s]*mentioned in[^,.?]*[,\s]*',
                r'[,\s]*described in[^,.?]*[,\s]*',
            ]
            
            cleaned_text = question_text
            
            # Apply all patterns
            for pattern in patterns_to_remove:
                cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE)
            
            # Apply cleanup patterns
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text)  # Multiple spaces to single
            cleaned_text = re.sub(r'^[,\s]+|[,\s]+$', '', cleaned_text)  # Leading/trailing
            cleaned_text = re.sub(r'\?+$', '?', cleaned_text)  # Multiple question marks
            
            # Ensure proper capitalization
            if cleaned_text and not cleaned_text[0].isupper():
                cleaned_text = cleaned_text[0].upper() + cleaned_text[1:]
            
            # Log if changes were made
            if cleaned_text != question_text:
                logger.info(f"📝 Cleaned question text: '{question_text[:50]}...' → '{cleaned_text[:50]}...'")
            
            return cleaned_text.strip()
            
        except Exception as e:
            logger.error(f"❌ Error cleaning question text: {e}")
            return question_text

    async def _generate_questions_for_curriculum(self, curriculum_name: str, topic: str, parameters: Dict[str, Any]) -> List[Question]:
        """Generate questions for an entire curriculum"""
        try:
            # Search for content across the entire curriculum
            logger.info(f"Searching curriculum '{curriculum_name}' for question generation with topic: {topic}")
            
            # Use broader search queries to get diverse content from curriculum
            search_queries = [
                "introduction overview concepts",
                "advanced topics techniques methods",
                "practical applications examples",
                "key principles fundamentals",
                topic  # Include the specific topic as well
            ]
            
            all_content = []
            for query in search_queries:
                results = await self._search_curriculum_embeddings(curriculum_name, query, k=4)
                if results:
                    all_content.extend([r['content'] for r in results])
            
            # Remove duplicates and combine content
            unique_content = list(set(all_content))
            content = "\n\n".join(unique_content[:15])  # Limit to prevent context overflow
            
            if not content:
                logger.warning(f"No content found for curriculum '{curriculum_name}'")
                return []
            
            # Extract parameters for comprehensive exam generation
            count = parameters.get('count', 2)
            difficulty_levels = parameters.get('difficulty', ['medium'])
            question_types = parameters.get('question_types', ['multiple_choice_single_answer'])
            user_message = parameters.get('user_message', '')
            
            # Create dynamic difficulty and type constraints
            difficulty_constraint = f"Focus on {', '.join(difficulty_levels)} difficulty levels"
            type_constraint = f"Generate only these question types: {', '.join(question_types)}"
            
            # Enhanced question generation prompt for curriculum-wide exams
            question_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are a professional exam author and educational assessment specialist. Generate high-quality technical exam questions based STRICTLY on the provided content from the {curriculum_name} curriculum.

CURRICULUM EXAM SPECIFICATIONS:
- {difficulty_constraint}
- {type_constraint}
- Generate exactly {count} questions
- Cover diverse topics from across the curriculum
- User Request: "{user_message}"

DISTRIBUTION GUIDELINES:
- Distribute questions evenly across different subject areas in the curriculum
- Ensure questions cover various books/materials in the curriculum
- If multiple question types specified, vary the types throughout
- Make questions comprehensive and representative of the entire curriculum

CRITICAL CONTENT FOCUS REQUIREMENTS:
- ONLY create questions about TECHNICAL CONTENT, concepts, theories, procedures, and subject matter
- Write questions as if they are from a professional certification exam covering the entire curriculum
- Questions must be direct, clear, and professional without any meta-references

STRICTLY FORBIDDEN QUESTION ELEMENTS:
- DO NOT mention chapters, sections, or book structure ("Chapter 2", "Section 1.3", etc.)
- DO NOT use phrases like "According to the text", "Based on the provided text", "The book states", "As described in the book"
- DO NOT ask about book organization, preface, introduction, or meta-information
- DO NOT ask "What does the book teach" or "What does the book aim to"
- DO NOT reference the source material in questions

REQUIRED QUESTION STYLE:
- Write questions in direct, technical language
- Ask about concepts, processes, tools, and techniques directly
- Use professional terminology appropriate for the field
- Questions should sound like they come from industry certification exams covering multiple subject areas

Your response MUST be a JSON array of question objects. Each question object must have:
- "difficulty": one of "easy", "medium", or "hard" (matching the specified levels)
- "type": one of "multiple_choice_single_answer", "true_false", or "open_ended_question" (matching specified types)
- "question_text": The full text of the question (clear, specific, and exam-appropriate)
- "options": Array of 4 choices for multiple choice, empty array for others
- "answer": The correct answer as a STRING (for true/false use "True" or "False", for multiple choice use the exact option text)

CURRICULUM EXAM QUALITY STANDARDS:
- Easy questions: Test basic recall of technical definitions and concepts from across the curriculum
- Medium questions: Test application of concepts and analysis of scenarios from multiple subject areas
- Hard questions: Test evaluation, synthesis, and critical thinking across curriculum domains
- Multiple choice: Provide 4 plausible technical options with clear distinctions, only one correct answer
- True/False: Create statements about technical facts that are unambiguously true or false
- Open-ended: Ask for explanations that demonstrate understanding across curriculum topics

CRITICAL REQUIREMENTS:
- The "answer" field must ALWAYS be a string
- Base questions on technical concepts from the curriculum content
- Make questions appropriate for comprehensive curriculum assessment
- Ensure clear, unambiguous wording
- Questions must test actual technical understanding across multiple subject areas
- NO meta-references to source material whatsoever"""),
                ("human", "Curriculum Content: {content}\nTopic: {topic}\nGenerate {count} professional technical exam questions covering the breadth of the curriculum. Write each question as if it appears on a comprehensive certification exam covering multiple subject areas.")
            ])
            
            chain = question_prompt | self.get_current_llm() | StrOutputParser()
            
            logger.info(f"Invoking AI chain for curriculum: {curriculum_name} using Google Gemini")
            
            try:
                result = await chain.ainvoke({
                    "content": content,
                    "topic": topic,
                    "count": count,
                    "difficulty_constraint": difficulty_constraint,
                    "type_constraint": type_constraint
                })
            except Exception as e:
                logger.error(f"Error generating questions for curriculum {curriculum_name}: {e}")
                raise e
            
            logger.info(f"Raw AI response for curriculum {curriculum_name}: {result[:500]}...")
            
            # Parse questions
            try:
                # Clean the response
                cleaned_result = result.strip()
                if cleaned_result.startswith('```json'):
                    cleaned_result = cleaned_result.replace('```json\n', '').replace('\n```', '')
                elif cleaned_result.startswith('```'):
                    cleaned_result = cleaned_result.replace('```\n', '').replace('\n```', '')
                
                logger.info(f"Cleaned response for parsing: {cleaned_result[:300]}...")
                questions_data = json.loads(cleaned_result)
                logger.info(f"Successfully parsed {len(questions_data)} questions for curriculum: {curriculum_name}")
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing error for curriculum {curriculum_name}: {e}")
                logger.error(f"Raw response: {result}")
                return []
            except Exception as e:
                logger.error(f"Unexpected error parsing response for curriculum {curriculum_name}: {e}")
                return []
            
            questions = []
            for q_data in questions_data:
                # Convert answer to string to handle boolean values from LLM
                answer_value = q_data.get('answer', '')
                if isinstance(answer_value, bool):
                    answer_str = str(answer_value)
                else:
                    answer_str = str(answer_value) if answer_value is not None else ''
                
                question = Question(
                    difficulty=q_data.get('difficulty', 'medium'),
                    type=q_data.get('type', 'multiple_choice_single_answer'),
                    question_text=q_data.get('question_text', ''),
                    options=q_data.get('options', []),
                    answer=answer_str
                )
                questions.append(question)
            
            return questions
            
        except Exception as e:
            logger.error(f"Error generating questions for curriculum {curriculum_name}: {e}")
            return []

    async def _generate_questions_for_topic(self, book_title: str, topic: str, parameters: Dict[str, Any]) -> List[Question]:
        """Generate questions for a specific topic"""
        try:
            logger.info(f"🔄 Using fallback method for book '{book_title}' topic '{topic}'")
            
            # Get book info to determine correct curriculum
            book_info = await self._get_book_curriculum_info(book_title)
            curriculum_name = book_info.get('curriculum_name') if book_info else "IT"
            logger.info(f"📚 Using curriculum '{curriculum_name}' for book '{book_title}'")

            if book_title and book_title != "General Content":
                # Use book-specific search with multiple attempts for different topic aspects
                all_chunks = []
                
                # Try main search first
                search_results = await self._search_book_embeddings(curriculum_name, book_title, topic, k=5)
                if search_results:
                    all_chunks.extend([r['content'] for r in search_results])
                    logger.info(f"✅ Found {len(search_results)} chunks for main topic search")
                
                # If it's a comprehensive search, try additional topics based on curriculum
                if "comprehensive" in topic.lower() or "whole book" in topic.lower():
                    if "law" in curriculum_name.lower():
                        additional_topics = [
                            "civil law contracts obligations",
                            "legal rights responsibilities procedures",
                            "judicial system court processes"
                        ]
                    else:
                        additional_topics = [
                            "introduction fundamentals principles",
                            "key concepts main topics",
                            "practical applications examples"
                        ]
                    
                    for additional_topic in additional_topics:
                        more_results = await self._search_book_embeddings(curriculum_name, book_title, additional_topic, k=3)
                        if more_results:
                            all_chunks.extend([r['content'] for r in more_results])
                            logger.info(f"✅ Found {len(more_results)} chunks for additional topic: {additional_topic}")
                
                if not all_chunks:
                    # If no chunks found, try to extract topics and search again
                    topics = await self._extract_book_topics(curriculum_name, book_title)
                    logger.info(f"🔄 Retrying search with extracted topics: {topics}")
                    
                    for topic in topics:
                        more_results = await self._search_book_embeddings(curriculum_name, book_title, topic, k=3)
                        if more_results:
                            all_chunks.extend([r['content'] for r in more_results])
                            logger.info(f"✅ Found {len(more_results)} chunks for topic: {topic}")
                    
                    if not all_chunks:
                        logger.warning(f"⚠️ Still no embeddings found after topic-based search")
                        
                content_chunks = all_chunks
            else:
                # Use general curriculum search with topic extraction
                topics = await self._extract_book_topics(curriculum_name, "General Content")
                all_chunks = []
                
                for topic in topics:
                    results = await self._search_curriculum_embeddings(curriculum_name, topic, k=3)
                    if results:
                        all_chunks.extend([r['content'] for r in results])
                        logger.info(f"✅ Found {len(results)} chunks for curriculum topic: {topic}")
                
                content_chunks = all_chunks
            
            # Ensure content_chunks is a list and not None
            if not content_chunks:
                content_chunks = []
                logger.warning("⚠️ No content chunks retrieved, using fallback content")
            
            # Filter out None values and empty strings
            valid_chunks = [chunk for chunk in content_chunks if chunk and isinstance(chunk, str)]
            
            if valid_chunks:
                content = "\n\n".join(valid_chunks)
                logger.info(f"✅ Fallback method retrieved {len(valid_chunks)} valid content chunks")
            else:
                content = f"General content about {topic}"
                logger.warning(f"⚠️ No valid content chunks found for topic: {topic}")
                
        except Exception as e:
            logger.error(f"❌ Error in fallback search: {e}")
            content = f"General content about {topic}"
            valid_chunks = []
            
            # Extract parameters for comprehensive exam generation
            count = parameters.get('count', 2)
            difficulty_levels = parameters.get('difficulty', ['medium'])
            question_types = parameters.get('question_types', ['multiple_choice_single_answer'])
            scope_type = parameters.get('scope_type', 'whole_book')
            specific_topics = parameters.get('specific_topics', '')
            time_limit = parameters.get('time_limit', 30)
            user_message = parameters.get('user_message', '')
            
            # Create dynamic difficulty and type constraints
            difficulty_constraint = f"Focus on {', '.join(difficulty_levels)} difficulty levels"
            type_constraint = f"Generate only these question types: {', '.join(question_types)}"
            
            # Create scope-specific instruction
            scope_instruction = ""
            if scope_type == 'specific_topics' and specific_topics:
                scope_instruction = f"Focus SPECIFICALLY on these topics: {specific_topics}. "
            else:
                scope_instruction = "Cover comprehensive content from the book. "
            
            # Create time-based instruction
            time_instruction = ""
            if time_limit:
                time_per_question = time_limit / count if count > 0 else 2
                if time_per_question < 1:
                    time_instruction = "Create quick, focused questions suitable for rapid assessment. "
                elif time_per_question > 5:
                    time_instruction = "Create in-depth questions that require thorough analysis. "
                else:
                    time_instruction = f"Create questions appropriate for {time_per_question:.1f} minutes per question. "
            
            # Enhanced question generation prompt for comprehensive exams
            question_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are a professional exam author and educational assessment specialist. Generate high-quality technical exam questions based STRICTLY on the provided content.

COMPREHENSIVE EXAM SPECIFICATIONS:
- {difficulty_constraint}
- {type_constraint}
- Generate exactly {count} questions
- {scope_instruction}
- {time_instruction}
- User Request: "{user_message}"

DISTRIBUTION GUIDELINES:
- Distribute questions evenly across specified difficulty levels
- If multiple question types specified, vary the types throughout
- Ensure each question tests different aspects of the content

CRITICAL CONTENT FOCUS REQUIREMENTS:
- ONLY create questions about TECHNICAL CONTENT, concepts, theories, procedures, and subject matter
- Write questions as if they are from a professional certification exam or university exam
- Questions must be direct, clear, and professional without any meta-references

STRICTLY FORBIDDEN QUESTION ELEMENTS:
- DO NOT mention chapters, sections, or book structure ("Chapter 2", "Section 1.3", etc.)
- DO NOT use phrases like "According to the text", "Based on the provided text", "The book states", "As described in the book"
- DO NOT ask about book organization, preface, introduction, or meta-information
- DO NOT ask "What does the book teach" or "What does the book aim to"
- DO NOT reference the source material in questions

REQUIRED QUESTION STYLE:
- Write questions in direct, technical language
- Ask about concepts, processes, tools, and techniques directly
- Use professional terminology appropriate for the field
- Questions should sound like they come from industry certification exams

Your response MUST be a JSON array of question objects. Each question object must have:
- "difficulty": one of "easy", "medium", or "hard" (matching the specified levels)
- "type": one of "multiple_choice_single_answer", "true_false", or "open_ended_question" (matching specified types)
- "question_text": The full text of the question (clear, specific, and exam-appropriate)
- "options": Array of 4 choices for multiple choice, empty array for others
- "answer": The correct answer as a STRING (for true/false use "True" or "False", for multiple choice use the exact option text)

EXAM QUESTION QUALITY STANDARDS:
- Easy questions: Test basic recall of technical definitions, concepts, and simple comprehension
- Medium questions: Test application of concepts, analysis of technical scenarios, and connections between ideas
- Hard questions: Test evaluation of solutions, synthesis of complex concepts, and critical thinking about technical problems
- Multiple choice: Provide 4 plausible technical options with clear distinctions, only one correct answer
- True/False: Create statements about technical facts that are unambiguously true or false
- Open-ended: Ask for explanations of technical concepts, comparisons of methods, applications of principles

PROFESSIONAL QUESTION EXAMPLES (GOOD):
- "What is the primary function of Apache Kafka in data streaming?"
- "Which algorithm is most efficient for sorting large datasets?"
- "What are the key advantages of using Docker containers?"
- "How does load balancing improve system performance?"
- "What happens when a database transaction fails?"
- "Which data structure provides O(1) lookup time?"

AVOID THESE PHRASES AND PATTERNS (BAD):
- "According to the text/book/chapter..."
- "Based on the provided information..."
- "What tools are mentioned in Chapter X?"
- "What does the book teach about..."
- "As described in the book..."
- "Considering the provided text..."
- "The book aims to..."
- "What is discussed in Section X?"

WRITE QUESTIONS LIKE A PROFESSIONAL EXAM:
- Direct technical questions about concepts and tools
- No reference to source material or book structure
- Professional, industry-standard language
- Focus on practical knowledge and understanding

CRITICAL REQUIREMENTS:
- The "answer" field must ALWAYS be a string
- Base questions on technical concepts from the content
- Make questions appropriate for professional certification or academic exams
- Ensure clear, unambiguous wording
- Questions must test actual technical understanding
- NO meta-references to source material whatsoever"""),
                ("human", "Content: {content}\nTopic: {topic}\nGenerate {count} professional technical exam questions. Write each question as if it appears on a certification exam or university test. Focus ONLY on technical concepts and avoid any reference to source material.")
            ])
            
            chain = question_prompt | self.get_current_llm() | StrOutputParser()
            
            logger.info(f"Invoking AI chain for topic: {topic} using Google Gemini")
            
            try:
                result = await chain.ainvoke({
                    "content": content,
                    "topic": topic,
                    "count": count,
                    "difficulty_constraint": difficulty_constraint,
                    "type_constraint": type_constraint
                })
            except Exception as e:
                logger.error(f"Error generating questions for topic {topic}: {e}")
                raise e
            
            logger.info(f"Raw AI response for topic {topic}: {result[:500]}...")
            
            # Parse questions
            try:
                # Clean the response
                cleaned_result = result.strip()
                if cleaned_result.startswith('```json'):
                    cleaned_result = cleaned_result.replace('```json\n', '').replace('\n```', '')
                elif cleaned_result.startswith('```'):
                    cleaned_result = cleaned_result.replace('```\n', '').replace('\n```', '')
                
                logger.info(f"Cleaned response for parsing: {cleaned_result[:300]}...")
                questions_data = json.loads(cleaned_result)
                logger.info(f"Successfully parsed {len(questions_data)} questions for topic: {topic}")
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing error for topic {topic}: {e}")
                logger.error(f"Raw response: {result}")
                return []
            except Exception as e:
                logger.error(f"Unexpected error parsing response for topic {topic}: {e}")
                return []
            
            questions = []
            for q_data in questions_data:
                # Convert answer to string to handle boolean values from LLM
                answer_value = q_data.get('answer', '')
                if isinstance(answer_value, bool):
                    answer_str = str(answer_value)
                else:
                    answer_str = str(answer_value) if answer_value is not None else ''
                
                question = Question(
                    difficulty=q_data.get('difficulty', 'medium'),
                    type=q_data.get('type', 'multiple_choice_single_answer'),
                    question_text=q_data.get('question_text', ''),
                    options=q_data.get('options', []),
                    answer=answer_str
                )
                questions.append(question)
            
            return questions
            
        except Exception as e:
            logger.error(f"Error generating questions for topic {topic}: {e}")
            return []

    async def generate_lecture(self, request: LectureRequest) -> str:
        """Generate lecture for a book with comprehensive parameters"""
        try:
            # Create knowledge retriever tool
            knowledge_tool = self._create_knowledge_search_tool(request.book_title)
            knowledge_tool.name = "knowledge_retriever_tool" # Ensure the name matches the prompt

            # Create agent for lecture generation
            tools = [knowledge_tool]
            current_llm = self.get_current_llm()
            
            # Try to create the agent with better error handling
            try:
                agent = create_tool_calling_agent(current_llm, tools, self.lecture_prompt)
                agent_executor = AgentExecutor(
                    agent=agent, 
                    tools=tools, 
                    verbose=False,  # Disable verbose to reduce output clutter
                    handle_parsing_errors=True,  # This helps with tool calling issues
                    max_iterations=5,  # Limit iterations to prevent infinite loops
                    return_intermediate_steps=False  # Don't return intermediate steps
                )
            except Exception as agent_error:
                logger.error(f"Error creating agent: {agent_error}")
                raise agent_error
            
            # Prepare parameters with fallbacks
            category = request.category or "General"
            title = request.title or f"Lecture on {request.book_title}"
            scope = request.scope or "whole_book"
            specific_topics = request.specific_topics if scope == "specific_topics" else ""
            detail_level = request.detail_level or "overview"
            
            logger.info(f"Generating lecture with parameters: category={category}, title={title}, scope={scope}, detail_level={detail_level}")
            
            # Create a more focused input that encourages proper tool usage
            input_text = f"""Please create a comprehensive {detail_level} lecture titled "{title}" about {request.book_title} in the {category} category.

Requirements:
- Use the knowledge_retriever_tool to search for relevant content from the book
- Create a well-structured lecture script following the format specified
- Scope: {scope}
{f"- Focus specifically on: {specific_topics}" if specific_topics else ""}

Begin by searching for relevant content using the knowledge retrieval tool."""
            
            try:
                result = await agent_executor.ainvoke({
                    "book_title": request.book_title,
                    "category": category,
                    "title": title,
                    "scope": scope,
                    "specific_topics": specific_topics,
                    "detail_level": detail_level,
                    "user_message": request.user_message,
                    "input": input_text,
                })
                
                # Clean the output to remove any debugging code or unwanted content
                cleaned_output = self._clean_lecture_output(result['output'])
                return cleaned_output
                
            except Exception as execution_error:
                logger.error(f"Error during agent execution: {execution_error}")
                
                # Check if it's a parsing error and try to extract useful content
                error_str = str(execution_error).lower()
                if "parsing" in error_str or "tool" in error_str:
                    # Try a simpler approach - direct content retrieval and simple generation
                    logger.info("Falling back to direct content retrieval approach")
                    return await self._generate_lecture_fallback(request)
                else:
                    raise execution_error
            
        except Exception as e:
            logger.error(f"Error generating lecture: {e}")
            raise

    async def _generate_lecture_fallback(self, request: LectureRequest) -> str:
        """Fallback method for lecture generation when agent fails"""
        try:
            logger.info("Using fallback lecture generation method")
            
            # Directly search for content
            table_name = request.book_title
            
            # Search queries based on scope
            if request.scope == "specific_topics" and request.specific_topics:
                search_query = request.specific_topics
            else:
                search_query = f"overview introduction main concepts {request.book_title}"
            
            # Get content directly
            content_results = await self._search_vector_table(table_name, search_query, k=8)
            content = "\n\n".join(content_results) if content_results else "No content found"
            
            # Generate lecture using simple LLM chain
            fallback_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a professional lecture creator. Create a comprehensive lecture script based on the provided content.

Follow this structure:
# LECTURE SCRIPT: {title}
**Category:** {category} | **Duration:** Estimated time | **Level:** {detail_level}

## LECTURE OVERVIEW
- **Learning Objectives:** What students will achieve
- **Key Concepts:** Main topics covered

## MAIN CONTENT
[Create detailed sections based on the content provided]

## CONCLUSION
- **Key Takeaways:** Essential points
- **Next Steps:** Future learning

Base your lecture entirely on the provided content. Make it engaging and educational."""),
                ("human", """Content: {content}

Create a {detail_level} lecture titled "{title}" for category "{category}".
Book: {book_title}
Scope: {scope}
{specific_topics_instruction}""")
            ])
            
            # Prepare variables
            category = request.category or "General"
            title = request.title or f"Lecture on {request.book_title}"
            detail_level = request.detail_level or "overview"
            scope = request.scope or "whole_book"
            specific_topics_instruction = f"Focus on: {request.specific_topics}" if request.specific_topics else ""
            
            chain = fallback_prompt | self.get_current_llm() | StrOutputParser()
            
            result = await chain.ainvoke({
                "content": content,
                "title": title,
                "category": category,
                "detail_level": detail_level,
                "book_title": request.book_title,
                "scope": scope,
                "specific_topics_instruction": specific_topics_instruction
            })
            
            # Clean the output for the fallback method too
            return self._clean_lecture_output(result)
            
        except Exception as e:
            logger.error(f"Error in fallback lecture generation: {e}")
            return f"I apologize, but I encountered an error generating the lecture: {str(e)}"

    def _clean_lecture_output(self, output: str) -> str:
        """Clean the lecture output to remove unwanted debugging code and tool calls"""
        try:
            import re
            
            # Remove Python code blocks that contain tool calls
            # Pattern to match ```python ... ``` blocks
            python_code_pattern = r'```python\s*\n.*?```'
            cleaned_output = re.sub(python_code_pattern, '', output, flags=re.DOTALL)
            
            # Remove any remaining tool call references
            tool_call_patterns = [
                r'print\(default_api\.knowledge_retriever_tool\([^)]+\)\)',
                r'default_api\.knowledge_retriever_tool\([^)]+\)',
                r'knowledge_retriever_tool\([^)]+\)',
                r'> Entering new AgentExecutor chain\.\.\.',
                r'> Finished chain\.',
                r'```\s*\n*```'  # Empty code blocks
            ]
            
            for pattern in tool_call_patterns:
                cleaned_output = re.sub(pattern, '', cleaned_output, flags=re.MULTILINE)
            
            # Remove multiple consecutive newlines
            cleaned_output = re.sub(r'\n{3,}', '\n\n', cleaned_output)
            
            # Remove leading/trailing whitespace
            cleaned_output = cleaned_output.strip()
            
            # If the output is too short after cleaning, it might have been mostly debugging
            if len(cleaned_output) < 100:
                logger.warning("Output was mostly debugging code, using fallback generation")
                return "The lecture content was not generated properly. Please try again."
            
            return cleaned_output
            
        except Exception as e:
            logger.error(f"Error cleaning lecture output: {e}")
            # Return original output if cleaning fails
            return output

    def _format_questions_response(self, question_response: QuestionResponse) -> str:
        """Format questions response for chat"""
        formatted = f"# Questions for: {question_response.chapter}\n\n"
        
        for i, question in enumerate(question_response.questions_generated, 1):
            formatted += f"**Question {i}: ({question.difficulty}, {question.type})**\n"
            formatted += f"{question.question_text}\n"
            
            if question.options:
                for option in question.options:
                    formatted += f"- {option}\n"
            
            formatted += f"**Answer:** {question.answer}\n\n---\n\n"
        
        return formatted

    async def _get_or_create_session(self, session_id: str, book_title: str) -> Dict[str, Any]:
        """Get existing session or create new one"""
        try:
            # CRITICAL FIX: Only try to get existing session if session_id is provided and not empty
            session = None
            if session_id and session_id.strip() and session_id != "null":
                logger.info(f"Attempting to find existing session: {session_id}")
                session = await self.db.get_chat_session(session_id)
                
                if session:
                    logger.info(f"Found existing session: {session['id']} for book: {session.get('book_title', 'Unknown')}")
                    return session
                else:
                    logger.warning(f"Session {session_id} not found in database, will create new session")
            else:
                logger.info(f"No valid session_id provided (got: '{session_id}'), creating new session")
            
            # Create new session only if existing session not found or session_id is invalid
            logger.info(f"Creating new session for book: {book_title}")
            
            # Get book info
            book = await self.db.get_book_by_title(book_title)
            if not book:
                raise ValueError(f"Book '{book_title}' not found")
            
            # Create new session
            new_session_id = await self.db.create_chat_session(
                user_id="default_user",  # In production, get from auth
                book_id=book['id'],
                session_name=f"Chat about {book_title}"
            )
            
            # Get the newly created session
            session = await self.db.get_chat_session(new_session_id)
            if not session:
                raise RuntimeError(f"Failed to retrieve newly created session {new_session_id}")
                
            logger.info(f"Created new session: {session['id']} for book: {book_title}")
            return session
            
        except Exception as e:
            logger.error(f"Error getting/creating session: {e}")
            raise

    async def _get_or_create_curriculum_session(self, session_id: str, curriculum: str) -> Dict[str, Any]:
        """Get existing session or create new one for curriculum"""
        try:
            # Only try to get existing session if session_id is provided and not empty
            session = None
            if session_id and session_id.strip() and session_id != "null":
                logger.info(f"Attempting to find existing session: {session_id}")
                session = await self.db.get_chat_session(session_id)
                
                if session:
                    logger.info(f"Found existing session: {session['id']} for curriculum: {session.get('curriculum_name', 'Unknown')}")
                    return session
                else:
                    logger.warning(f"Session {session_id} not found in database, will create new session")
            else:
                logger.info(f"No valid session_id provided (got: '{session_id}'), creating new session")
            
            # Create new session for curriculum - for now use the first book in the curriculum
            logger.info(f"Creating new session for curriculum: {curriculum}")
            
            # Get curriculum info
            curriculum_info = await self.db.get_curriculum_by_name(curriculum)
            if not curriculum_info:
                raise ValueError(f"Curriculum '{curriculum}' not found")
            
            # Get a book from this curriculum (for now, get the first one)
            books_in_curriculum = await self.db.get_books_by_curriculum(curriculum_info['id'])
            if not books_in_curriculum:
                raise ValueError(f"No books found in curriculum '{curriculum}'")
            
            first_book = books_in_curriculum[0]
            
            # Create new session using the first book
            new_session_id = await self.db.create_chat_session(
                user_id="550e8400-e29b-41d4-a716-446655440000",  # Default UUID for demo
                book_id=first_book['id'],
                session_name=f"Chat about {curriculum}"
            )
            
            # Get the newly created session
            session = await self.db.get_chat_session(new_session_id)
            if not session:
                raise RuntimeError(f"Failed to retrieve newly created session {new_session_id}")
                
            logger.info(f"Created new session: {session['id']} for curriculum: {curriculum}")
            return session
            
        except Exception as e:
            logger.error(f"Error getting/creating curriculum session: {e}")
            raise

    async def _handle_curriculum_question_answering(self, request: ChatRequest, session: Dict[str, Any]) -> str:
        """Handle question answering for curriculum-based chat"""
        try:
            # Get or create chat history for the session (like in the regular method)
            session_id = str(session['id'])
            if session_id not in self.chat_histories:
                self.chat_histories[session_id] = ConversationBufferMemory(
                    memory_key="chat_history", 
                    return_messages=True
                )
            memory = self.chat_histories[session_id]
            
            # Load existing messages from database into memory if memory is empty
            if len(memory.chat_memory.messages) == 0:
                await self.memory_manager.load_chat_history_to_memory(session_id, memory, limit=50)
            
            # DIRECT VECTOR SEARCH APPROACH - Let's directly search the curriculum first
            logger.info(f"🔍 DIRECT SEARCH: Starting curriculum search for '{request.curriculum}' with query: {request.user_message[:50]}...")
            
            # Search curriculum embeddings directly
            search_results = await self._search_curriculum_embeddings(request.curriculum, request.user_message, k=6)
            
            if search_results:
                combined_content = "\n\n".join([r['content'] for r in search_results])
                logger.info(f"✅ DIRECT SEARCH SUCCESS: Found {len(search_results)} chunks from curriculum '{request.curriculum}'")
                
                # Now use this content with a simple LLM call
                simple_prompt = ChatPromptTemplate.from_messages([
                    ("system", f"""You are an expert educational assistant. You have been provided with relevant content from the {request.curriculum} curriculum to answer the user's question.

Use the provided curriculum content to give a comprehensive, well-structured answer.

**RESPONSE STRUCTURE:**
🎯 **DIRECT ANSWER**
Start with a clear, direct answer to the user's question.

📚 **DETAILED EXPLANATION**
Provide thorough explanation using the curriculum content.

🔑 **KEY CONCEPTS**
Highlight important concepts and terms.

💡 **PRACTICAL EXAMPLES**
Include relevant examples from the content.

Always end with: (Source: Internal Knowledge Base)

**CURRICULUM CONTENT:**
{combined_content}"""),
                    MessagesPlaceholder(variable_name="chat_history"),
                    ("human", "{user_message}")
                ])
                
                # Get chat history for context
                chat_history = memory.chat_memory.messages if memory.chat_memory.messages else []
                
                chain = simple_prompt | self.llm | StrOutputParser()
                response = await chain.ainvoke({
                    "user_message": request.user_message,
                    "chat_history": chat_history
                })
                
                # Save context to memory
                memory.save_context(
                    inputs={"input": request.user_message},
                    outputs={"output": response}
                )
                
                logger.info(f"✅ CURRICULUM RESPONSE GENERATED: Using {len(search_results)} chunks from vector database")
                return response
                
            else:
                logger.warning(f"❌ NO CONTENT FOUND: No curriculum content found for query: {request.user_message[:50]}...")
                return f"I couldn't find specific information about your question in the {request.curriculum} curriculum. This might be because the content hasn't been properly indexed or your question is outside the curriculum scope. Please try rephrasing your question or ask about topics covered in the {request.curriculum} curriculum."
            
        except Exception as e:
            logger.error(f"Error handling curriculum question answering: {e}")
            return f"I apologize, but I encountered an error while processing your question about {request.curriculum}. Please try again."

    # Session management methods
    async def create_session(self, user_id: str, book_title: str, session_name: str = None) -> ChatSessionModel:
        """Create new chat session"""
        try:
            # Get book info
            book = await self.db.get_book_by_title(book_title)
            if not book:
                raise ValueError(f"Book '{book_title}' not found")
            
            # Create session
            session_id = await self.db.create_chat_session(
                user_id=user_id,
                book_id=book['id'],
                session_name=session_name or f"Chat about {book_title}"
            )
            
            # Get created session
            session_data = await self.db.get_chat_session(session_id)
            
            # Create response manually with string conversion
            return ChatSessionModel(
                id=str(session_data['id']),
                user_id=str(session_data['user_id']),
                book_id=session_data['book_id'],
                session_name=session_data['session_name'],
                created_at=session_data['created_at'],
                updated_at=session_data['updated_at']
            )
            
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            raise

    async def create_curriculum_session(self, user_id: str, curriculum_name: str, session_name: str = None) -> ChatSessionModel:
        """Create new curriculum-based chat session"""
        try:
            # Ensure user exists (create if not)
            await self._ensure_user_exists(user_id)
            
            # Get curriculum info
            curriculum_info = await self.db.get_curriculum_by_name(curriculum_name)
            if not curriculum_info:
                raise ValueError(f"Curriculum '{curriculum_name}' not found")
            
            # Get books in this curriculum
            books_in_curriculum = await self.db.get_books_by_curriculum(curriculum_info['id'])
            if not books_in_curriculum:
                raise ValueError(f"No books found in curriculum '{curriculum_name}'")
            
            # Use the first book for session creation (the system will search across all books in the curriculum)
            first_book = books_in_curriculum[0]
            
            # Create session
            session_id = await self.db.create_chat_session(
                user_id=user_id,
                book_id=first_book['id'],
                session_name=session_name or f"Chat with {curriculum_name} Curriculum"
            )
            
            # Get created session
            session_data = await self.db.get_chat_session(session_id)
            
            # Create response manually with string conversion
            return ChatSessionModel(
                id=str(session_data['id']),
                user_id=str(session_data['user_id']),
                book_id=session_data['book_id'],
                session_name=session_data['session_name'],
                created_at=session_data['created_at'],
                updated_at=session_data['updated_at']
            )
            
        except Exception as e:
            logger.error(f"Error creating curriculum session: {e}")
            raise

    async def _ensure_user_exists(self, user_id: str):
        """Ensure user exists in database, create if not"""
        try:
            # Check if user exists
            async with self.db.get_connection() as conn:
                user_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM users WHERE id = $1)",
                    user_id
                )
                
                if not user_exists:
                    # Create a demo user
                    await conn.execute(
                        "INSERT INTO users (id, full_name, email, password_hash) VALUES ($1, $2, $3, $4)",
                        user_id,
                        f"User {user_id[:8]}",
                        f"user_{user_id[:8]}@zakerly.com",
                        "demo_hash"
                    )
                    logger.info(f"Created demo user: {user_id}")
                    
        except Exception as e:
            logger.error(f"Error ensuring user exists: {e}")
            raise

    async def get_session(self, session_id: str) -> Optional[ChatSessionModel]:
        """Get session by ID"""
        try:
            session_data = await self.db.get_chat_session(session_id)
            if session_data:
                # Create response manually with string conversion
                return ChatSessionModel(
                    id=str(session_data['id']),
                    user_id=session_data['user_id'],
                    book_id=session_data['book_id'],
                    session_name=session_data['session_name'],
                    created_at=session_data['created_at'],
                    updated_at=session_data['updated_at']
                )
            return None
            
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            raise

    async def get_user_sessions(self, user_id: str) -> List[ChatSessionModel]:
        """Get all sessions for a user"""
        try:
            sessions_data = await self.db.get_user_sessions(user_id)
            return [ChatSessionModel(**session_data) for session_data in sessions_data]
            
        except Exception as e:
            logger.error(f"Error getting user sessions: {e}")
            raise

    async def get_chat_history(self, session_id: str, limit: int = 50) -> List[ChatMessageModel]:
        """Get chat history for session"""
        try:
            history_data = await self.db.get_chat_history(session_id, limit)
            return [ChatMessageModel(**msg_data) for msg_data in history_data]
            
        except Exception as e:
            logger.error(f"Error getting chat history: {e}")
            raise

    async def delete_session(self, session_id: str) -> bool:
        """Delete chat session"""
        try:
            # Clear in-memory chat history
            if session_id in self.chat_histories:
                del self.chat_histories[session_id]
            
            # Clear database messages
            await self.memory_manager.clear_session_history(session_id)
            
            result = await self.db.execute_command(
                "DELETE FROM chat_sessions WHERE id = $1", session_id
            )
            return "DELETE 1" in result
            
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            raise

    # Memory management methods
    async def get_memory_stats(self, session_id: str) -> Dict[str, Any]:
        """Get memory statistics for a session"""
        try:
            message_count = await self.memory_manager.get_message_count(session_id)
            recent_messages = await self.memory_manager.get_recent_messages(session_id, limit=10)
            
            return {
                "session_id": session_id,
                "total_messages": message_count,
                "recent_messages_count": len(recent_messages),
                "memory_type": "conversation_buffer"
            }
        except Exception as e:
            logger.error(f"Error getting memory stats: {e}")
            return {}

    async def clear_session_memory(self, session_id: str) -> bool:
        """Clear memory for a specific session"""
        try:
            # Clear in-memory chat history
            if session_id in self.chat_histories:
                self.chat_histories[session_id].clear()
            
            # Clear database messages
            return await self.memory_manager.clear_session_history(session_id)
            
        except Exception as e:
            logger.error(f"Error clearing session memory: {e}")
            return False

    async def get_recent_messages(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages for a session"""
        try:
            messages = await self.memory_manager.get_recent_messages(session_id, limit)
            
            # Convert to dict format
            result = []
            for msg in messages:
                result.append({
                    "type": "user" if msg.__class__.__name__ == "HumanMessage" else "assistant",
                    "content": msg.content
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting recent messages: {e}")
            return []

    async def get_session_entities(self, session_id: str) -> Dict[str, Any]:
        """Get extracted entities for a session (simplified - returns empty for compatibility)"""
        try:
            # Since we simplified the memory system, we don't extract entities anymore
            # Return empty dict for API compatibility
            return {
                "message": "Entity extraction not available in simplified memory system",
                "entities": {}
            }
        except Exception as e:
            logger.error(f"Error getting session entities: {e}")
            return {"entities": {}}

    async def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get conversation summary for a session (simplified - returns message count)"""
        try:
            # Since we simplified the memory system, we don't create summaries anymore
            # Return basic info for API compatibility
            message_count = await self.memory_manager.get_message_count(session_id)
            return {
                "message": "Conversation summarization not available in simplified memory system",
                "summary": f"Session has {message_count} total messages",
                "message_count": message_count
            }
        except Exception as e:
            logger.error(f"Error getting session summary: {e}")
            return {"summary": ""}

    async def cleanup_expired_memories(self) -> Dict[str, Any]:
        """Clean up expired memories (simplified - no complex memory to clean)"""
        try:
            # Since we simplified the memory system, there are no expired memories to clean
            # Return success message for API compatibility
            return {
                "status": "success", 
                "message": "No expired memories to clean in simplified memory system"
            }
        except Exception as e:
            logger.error(f"Error cleaning up expired memories: {e}")
            return {"status": "error", "message": str(e)}

    # Lecture Scripts methods
    async def create_lecture_script(self, user_id: str, request) -> dict:
        """Create a new lecture script (supports both curriculum and book-based scripts)"""
        try:
            # Insert into database
            query = """
                INSERT INTO lecture_scripts 
                (user_id, curriculum_id, book_id, title, scope, specific_topics, specific_books, 
                 detail_level, difficulty, duration, content, script_style, target_audience,
                 include_examples, include_exercises, include_visual_aids)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                RETURNING id, user_id, curriculum_id, book_id, title, scope, specific_topics, specific_books,
                         detail_level, difficulty, duration, content, script_style, target_audience,
                         include_examples, include_exercises, include_visual_aids, created_at, updated_at
            """
            
            # Handle both curriculum and book-based requests
            curriculum_id = getattr(request, 'curriculum_id', None)
            book_id = getattr(request, 'book_id', None)
            specific_books = getattr(request, 'specific_books', None)
            script_style = getattr(request, 'script_style', 'lecture')
            target_audience = getattr(request, 'target_audience', 'intermediate')
            include_examples = getattr(request, 'include_examples', True)
            include_exercises = getattr(request, 'include_exercises', False)
            include_visual_aids = getattr(request, 'include_visual_aids', True)
            
            # Convert specific_books list to JSON string if provided
            specific_books_json = None
            if specific_books and isinstance(specific_books, list):
                import json
                specific_books_json = json.dumps(specific_books)
            
            result = await self.db.execute_query(
                query,
                user_id, curriculum_id, book_id, request.title, request.scope,
                request.specific_topics, specific_books_json, request.detail_level, 
                request.difficulty, request.duration, request.content, script_style,
                target_audience, include_examples, include_exercises, include_visual_aids
            )
            
            if result:
                row = result[0]
                return {
                    "id": str(row["id"]),
                    "user_id": str(row["user_id"]),
                    "curriculum_id": row["curriculum_id"],
                    "book_id": row["book_id"],
                    "title": row["title"],
                    "scope": row["scope"],
                    "specific_topics": row["specific_topics"],
                    "specific_books": row["specific_books"],
                    "detail_level": row["detail_level"],
                    "difficulty": row["difficulty"],
                    "duration": row["duration"],
                    "content": row["content"],
                    "script_style": row["script_style"],
                    "target_audience": row["target_audience"],
                    "include_examples": row["include_examples"],
                    "include_exercises": row["include_exercises"],
                    "include_visual_aids": row["include_visual_aids"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error creating lecture script: {e}")
            raise e

    async def get_lecture_script(self, script_id: str, user_id: str) -> dict:
        """Get a specific lecture script by ID"""
        try:
            query = """
                SELECT id, user_id, book_id, title, scope, specific_topics, detail_level, difficulty, duration, content, created_at, updated_at
                FROM lecture_scripts
                WHERE id = $1 AND user_id = $2
            """
            
            result = await self.db.execute_query(query, script_id, user_id)
            
            if result:
                row = result[0]
                return {
                    "id": str(row["id"]),
                    "user_id": str(row["user_id"]),
                    "book_id": row["book_id"],
                    "title": row["title"],
                    "scope": row["scope"],
                    "specific_topics": row["specific_topics"],
                    "detail_level": row["detail_level"],
                    "difficulty": row["difficulty"],
                    "duration": row["duration"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting lecture script {script_id}: {e}")
            raise e

    async def get_user_scripts(self, user_id: str) -> List[dict]:
        """Get all lecture scripts for a user (supports both curriculum and book-based scripts)"""
        try:
            query = """
                SELECT ls.id, ls.user_id, ls.curriculum_id, ls.book_id, ls.title, ls.scope, 
                       ls.specific_topics, ls.specific_books, ls.detail_level, ls.difficulty, 
                       ls.duration, ls.content, ls.script_style, ls.target_audience,
                       ls.include_examples, ls.include_exercises, ls.include_visual_aids,
                       ls.created_at, ls.updated_at,
                       b.title as book_title, c.name as curriculum_name
                FROM lecture_scripts ls
                LEFT JOIN books b ON ls.book_id = b.id
                LEFT JOIN curriculum c ON ls.curriculum_id = c.id
                WHERE ls.user_id = $1
                ORDER BY ls.created_at DESC
            """
            
            result = await self.db.execute_query(query, user_id)
            
            scripts = []
            if result:
                for row in result:
                    # Parse specific_books JSON if exists
                    specific_books = None
                    if row["specific_books"]:
                        try:
                            import json
                            specific_books = json.loads(row["specific_books"])
                        except:
                            specific_books = None
                    
                    scripts.append({
                        "id": str(row["id"]),
                        "user_id": str(row["user_id"]),
                        "curriculum_id": row["curriculum_id"],
                        "book_id": row["book_id"],
                        "title": row["title"],
                        "scope": row["scope"],
                        "specific_topics": row["specific_topics"],
                        "specific_books": specific_books,
                        "detail_level": row["detail_level"],
                        "difficulty": row["difficulty"],
                        "duration": row["duration"],
                        "content": row["content"],
                        "script_style": row["script_style"],
                        "target_audience": row["target_audience"],
                        "include_examples": row["include_examples"],
                        "include_exercises": row["include_exercises"],
                        "include_visual_aids": row["include_visual_aids"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "book_title": row["book_title"],
                        "curriculum_name": row["curriculum_name"]
                    })
            
            return scripts
            
        except Exception as e:
            logger.error(f"Error getting user scripts: {e}")
            raise e

    async def update_lecture_script(self, script_id: str, user_id: str, request) -> dict:
        """Update a lecture script"""
        try:
            # Build dynamic update query
            update_fields = []
            values = []
            param_count = 1
            
            if request.title is not None:
                update_fields.append(f"title = ${param_count}")
                values.append(request.title)
                param_count += 1
                
            if request.content is not None:
                update_fields.append(f"content = ${param_count}")
                values.append(request.content)
                param_count += 1
                
            if request.scope is not None:
                update_fields.append(f"scope = ${param_count}")
                values.append(request.scope)
                param_count += 1
                
            if request.specific_topics is not None:
                update_fields.append(f"specific_topics = ${param_count}")
                values.append(request.specific_topics)
                param_count += 1
                
            if request.detail_level is not None:
                update_fields.append(f"detail_level = ${param_count}")
                values.append(request.detail_level)
                param_count += 1
                
            if request.difficulty is not None:
                update_fields.append(f"difficulty = ${param_count}")
                values.append(request.difficulty)
                param_count += 1
                
            if request.duration is not None:
                update_fields.append(f"duration = ${param_count}")
                values.append(request.duration)
                param_count += 1
            
            if not update_fields:
                # Nothing to update, return existing script
                return await self.get_lecture_script(script_id, user_id)
            
            update_fields.append(f"updated_at = ${param_count}")
            values.append(datetime.utcnow())
            param_count += 1
            
            # Add WHERE clause parameters
            values.extend([script_id, user_id])
            
            query = f"""
                UPDATE lecture_scripts 
                SET {', '.join(update_fields)}
                WHERE id = ${param_count} AND user_id = ${param_count + 1}
                RETURNING id, user_id, book_id, title, scope, specific_topics, detail_level, difficulty, duration, content, created_at, updated_at
            """
            
            result = await self.db.execute_query(query, *values)
            
            if result:
                row = result[0]
                return {
                    "id": str(row["id"]),
                    "user_id": str(row["user_id"]),
                    "book_id": row["book_id"],
                    "title": row["title"],
                    "scope": row["scope"],
                    "specific_topics": row["specific_topics"],
                    "detail_level": row["detail_level"],
                    "difficulty": row["difficulty"],
                    "duration": row["duration"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error updating lecture script {script_id}: {e}")
            raise e

    async def delete_lecture_script(self, script_id: str, user_id: str) -> bool:
        """Delete a lecture script"""
        try:
            query = """
                DELETE FROM lecture_scripts 
                WHERE id = $1 AND user_id = $2
            """
            
            result = await self.db.execute_query(query, script_id, user_id)
            return result is not None
            
        except Exception as e:
            logger.error(f"Error deleting lecture script {script_id}: {e}")
            raise e

    # Enhanced Curriculum Script Generation Methods
    async def generate_curriculum_script(self, request: dict) -> str:
        """Generate script based on curriculum scope (Case 1, 2, or 3)"""
        try:
            scope = request.get('scope', 'whole_curriculum')
            
            if scope == 'whole_curriculum':
                return await self._generate_curriculum_script(request)
            elif scope == 'whole_book':
                return await self._generate_book_script(request)
            elif scope == 'specific_topics':
                return await self._generate_topic_script(request)
            else:
                raise ValueError(f"Invalid scope: {scope}")
                
        except Exception as e:
            logger.error(f"Error generating curriculum script: {e}")
            raise e

    async def _generate_curriculum_script(self, request: dict) -> str:
        """Case 1: Generate script covering whole curriculum"""
        try:
            curriculum_id = request['curriculum_id']
            title = request.get('title', 'Comprehensive Curriculum Overview')
            detail_level = request.get('detail_level', 'overview')
            
            logger.info(f"Generating Case 1 script for curriculum {curriculum_id}")
            
            # Step 1: Extract curriculum-wide topics
            curriculum_topics = await self._extract_curriculum_wide_topics(curriculum_id)
            
            if not curriculum_topics:
                raise ValueError("No topics found in curriculum")
            
            # Step 2: Get books in curriculum
            curriculum_books = await self._get_curriculum_books(curriculum_id)
            book_titles = [book['title'] for book in curriculum_books]
            
            # Step 3: Generate comprehensive script
            script_prompt = f"""Create a comprehensive lecture script covering the entire curriculum with these specifications:

**Title:** {title}
**Scope:** Whole Curriculum ({len(curriculum_books)} books)
**Detail Level:** {detail_level}
**Books Covered:** {', '.join(book_titles)}

**Key Topics to Address:**
{chr(10).join(f"- {topic}" for topic in curriculum_topics[:20])}

**Instructions:**
1. Create an executive overview that ties together all curriculum components
2. Structure the content to show connections between different subject areas
3. Include strategic insights that span multiple books/topics
4. Provide a roadmap for comprehensive understanding
5. Use {detail_level} level of detail throughout

**Format:**
# LECTURE SCRIPT: {title}

## I. CURRICULUM OVERVIEW
[Comprehensive introduction covering the full scope]

## II. INTEGRATED LEARNING FRAMEWORK
[How all components work together]

## III. CORE COMPETENCY AREAS
[Major topic clusters with cross-references]

## IV. STRATEGIC INSIGHTS
[High-level connections and applications]

## V. IMPLEMENTATION ROADMAP
[How to approach this comprehensive curriculum]

## VI. CONCLUSION
[Synthesis and next steps]

Generate a professional, comprehensive script that demonstrates mastery across the entire curriculum."""
            
            # Use direct LLM call for better control
            script_content = await self.llm.ainvoke(script_prompt)
            return script_content.content if hasattr(script_content, 'content') else str(script_content)
            
        except Exception as e:
            logger.error(f"Error generating curriculum script: {e}")
            raise e

    async def _generate_book_script(self, request: dict) -> str:
        """Case 2: Generate script for whole book"""
        try:
            curriculum_id = request['curriculum_id']
            book_ids = request['specific_books']
            title = request.get('title', 'Comprehensive Book Analysis')
            detail_level = request.get('detail_level', 'detailed')
            
            if not book_ids:
                raise ValueError("No books specified")
            
            logger.info(f"Generating Case 2 script for book(s) {book_ids}")
            
            # Step 1: Get book details
            book_details = []
            for book_id in book_ids:
                book_info = await self._get_book_info(book_id)
                if book_info:
                    book_details.append(book_info)
            
            if not book_details:
                raise ValueError("No valid books found")
            
            # Step 2: Extract topics from all book TOCs
            all_topics = []
            for book in book_details:
                toc_topics = await self._extract_topics_from_book_toc(book['title'])
                all_topics.extend(toc_topics)
            
            # Remove duplicates and get unique topics
            unique_topics = list(set(all_topics))
            
            # Step 3: Generate focused book script
            book_titles = [book['title'] for book in book_details]
            
            script_prompt = f"""Create a comprehensive lecture script for the specified book(s):

**Title:** {title}
**Scope:** Whole Book Analysis
**Detail Level:** {detail_level}
**Book(s):** {', '.join(book_titles)}

**Key Topics from Book TOC:**
{chr(10).join(f"- {topic}" for topic in unique_topics[:25])}

**Instructions:**
1. Provide deep, focused coverage of the book content
2. Organize by major themes and chapters
3. Include specific examples and detailed explanations
4. Use {detail_level} level of analysis throughout
5. Create practical learning applications

**Format:**
# LECTURE SCRIPT: {title}

## I. BOOK OVERVIEW
[Introduction to the book's scope and objectives]

## II. FOUNDATIONAL CONCEPTS
[Core principles and theories]

## III. DETAILED ANALYSIS
[Chapter-by-chapter or theme-based coverage]

## IV. PRACTICAL APPLICATIONS
[Real-world examples and case studies]

## V. CRITICAL INSIGHTS
[Key takeaways and important concepts]

## VI. SYNTHESIS & CONCLUSIONS
[Integration and next steps]

Focus on providing comprehensive, detailed coverage that demonstrates deep understanding of the book content."""
            
            # Use direct LLM call
            script_content = await self.llm.ainvoke(script_prompt)
            return script_content.content if hasattr(script_content, 'content') else str(script_content)
            
        except Exception as e:
            logger.error(f"Error generating book script: {e}")
            raise e

    async def _generate_topic_script(self, request: dict) -> str:
        """Case 3: Generate script for specific topics"""
        try:
            curriculum_id = request['curriculum_id']
            book_ids = request.get('specific_books', [])
            topics = request.get('specific_topics', '')
            title = request.get('title', 'Focused Topic Analysis')
            detail_level = request.get('detail_level', 'detailed')
            
            if not topics.strip():
                raise ValueError("No specific topics provided")
            
            logger.info(f"Generating Case 3 script for topics: {topics}")
            
            # Step 1: Parse and clean topics
            topic_list = [topic.strip() for topic in topics.split(',') if topic.strip()]
            
            # Step 2: Get context from specified books or curriculum
            context_books = []
            if book_ids:
                for book_id in book_ids:
                    book_info = await self._get_book_info(book_id)
                    if book_info:
                        context_books.append(book_info['title'])
            else:
                # If no specific books, get curriculum overview
                curriculum_books = await self._get_curriculum_books(curriculum_id)
                context_books = [book['title'] for book in curriculum_books[:5]]  # Limit for focus
            
            # Step 3: Generate topic-focused script
            script_prompt = f"""Create a comprehensive lecture script focused on specific topics:

**Title:** {title}
**Scope:** Specific Topics Analysis
**Detail Level:** {detail_level}
**Target Topics:** {', '.join(topic_list)}
**Context Books:** {', '.join(context_books)}

**Instructions:**
1. Focus exclusively on the specified topics
2. Provide deep, detailed analysis of each topic
3. Show connections between related topics
4. Include practical examples and applications
5. Use {detail_level} level of depth throughout

**Format:**
# LECTURE SCRIPT: {title}

## I. TOPIC OVERVIEW
[Introduction to the specific topics covered]

## II. DETAILED TOPIC ANALYSIS
{chr(10).join(f"### {topic}" for topic in topic_list)}
[Comprehensive coverage of each topic]

## III. INTERCONNECTIONS
[How these topics relate to each other]

## IV. PRACTICAL APPLICATIONS
[Real-world uses and examples]

## V. ADVANCED CONCEPTS
[Deeper insights and complex aspects]

## VI. SUMMARY & INTEGRATION
[Key takeaways and synthesis]

Provide focused, detailed coverage that demonstrates expertise in the specified topics."""
            
            # Use direct LLM call
            script_content = await self.llm.ainvoke(script_prompt)
            return script_content.content if hasattr(script_content, 'content') else str(script_content)
            
        except Exception as e:
            logger.error(f"Error generating topic script: {e}")
            raise e

    async def _get_book_info(self, book_id: int) -> Optional[Dict[str, Any]]:
        """Get book information by book ID"""
        try:
            book_info = await self.db.get_book_by_id(book_id)
            if not book_info:
                logger.warning(f"No book found with ID: {book_id}")
                return None
            
            return {
                'id': book_info['id'],
                'title': book_info['title'],
                'author': book_info.get('author'),
                'curriculum_id': book_info['curriculum_id'],
                'curriculum_name': book_info.get('curriculum_name'),
                'file_name': book_info.get('file_name'),
                'publication_year': book_info.get('publication_year')
            }
        except Exception as e:
            logger.error(f"Error getting book info for ID {book_id}: {e}")
            return None

    async def _get_curriculum_books(self, curriculum_id: int) -> List[Dict[str, Any]]:
        """Get all books in a curriculum"""
        try:
            books = await self.db.get_books_by_curriculum(curriculum_id)
            if not books:
                logger.warning(f"No books found for curriculum ID: {curriculum_id}")
                return []
                
            return [
                {
                    'id': book['id'],
                    'title': book['title'],
                    'author': book.get('author'),
                    'curriculum_id': book['curriculum_id'],
                    'file_name': book.get('file_name'),
                    'publication_year': book.get('publication_year')
                }
                for book in books
            ]
        except Exception as e:
            logger.error(f"Error getting curriculum books for ID {curriculum_id}: {e}")
            return []

    async def _extract_topics_from_book_toc(self, book_title: str) -> List[str]:
        """Extract topics from a book's table of contents"""
        try:
            # Get book and curriculum info
            book_info = await self._get_book_curriculum_info(book_title)
            if not book_info:
                logger.warning(f"Book '{book_title}' not found for TOC extraction")
                return []
            
            curriculum_name = book_info.get('curriculum_name', 'Unknown')
            
            # Use existing method to extract book topics
            topics = await self._extract_book_topics(curriculum_name, book_title)
            
            logger.info(f"Extracted {len(topics)} topics from '{book_title}' TOC")
            return topics
            
        except Exception as e:
            logger.error(f"Error extracting TOC topics from '{book_title}': {e}")
            return []