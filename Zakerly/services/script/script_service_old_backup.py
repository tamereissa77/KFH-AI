import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain.tools import Tool

from models import LectureRequest, LectureScript, LectureScriptRequest, LectureScriptUpdate
from database import DatabaseManager
from memory import SimpleMemoryManager

logger = logging.getLogger(__name__)

class ScriptService:
    def __init__(self, db: DatabaseManager, memory_manager: SimpleMemoryManager):
        self.db = db
        self.memory_manager = memory_manager
        
        # Initialize LLM
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            temperature=0.3,
            max_tokens=8192
        )
        
        # Create lecture generation prompt
        self.lecture_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a world-class lecture creator and educational content developer with expertise in curriculum design and pedagogical best practices.

Your task is to create comprehensive, engaging lecture scripts based on the provided book content and requirements.

IMPORTANT: You have access to a knowledge_retriever_tool that can search for relevant content from the book. You MUST use this tool to gather accurate, relevant information before creating your lecture.

Guidelines for lecture creation:
1. Always start by using the knowledge_retriever_tool to search for relevant content
2. Create well-structured, professional lecture scripts
3. Include clear learning objectives and key takeaways
4. Adapt the content level and style based on the specified parameters
5. Make the content engaging and educational

When using the knowledge retrieval tool:
- Search for key concepts, theories, examples, and detailed explanations
- Use multiple searches if needed to cover different aspects of the topic
- Base your lecture content primarily on the retrieved information

Output Format:
Create a professional lecture script with clear sections, engaging content, and educational value. Include relevant examples and explanations from the book content."""),
            ("human", """Create a lecture with these parameters:
- Book: {book_title}
- Category: {category}
- Title: {title}
- Scope: {scope}
- Detail Level: {detail_level}
- Specific Topics: {specific_topics}
- User Message: {user_message}

{input}""")
        ])

    def get_current_llm(self):
        """Get the current LLM instance"""
        return self.llm

    def _create_knowledge_search_tool(self, table_name: str) -> Tool:
        """Create knowledge search tool for a specific table"""
        async def search_knowledge(query: str) -> str:
            """Search for relevant content in the book vector database"""
            try:
                # Clean the table name for vector search
                cleaned_table = table_name.lower().replace(' ', '_').replace('-', '_')
                
                # Perform vector search
                results = await self._search_vector_table(cleaned_table, query, k=6)
                
                if results:
                    return f"Found relevant content:\n\n" + "\n\n".join(results)
                else:
                    return f"No specific content found for query: {query}"
                    
            except Exception as e:
                logger.error(f"Error in knowledge search: {e}")
                return f"Error searching for content: {str(e)}"
        
        return Tool(
            name="knowledge_retriever_tool",
            description=f"Search for relevant content and information from {table_name}. Use this to gather accurate information before creating lecture content.",
            func=search_knowledge
        )

    async def _search_vector_table(self, table_name: str, query: str, k: int = 5) -> List[str]:
        """Search vector embeddings table for relevant content"""
        try:
            # First, check if the table exists
            check_query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = $1
                );
            """
            
            table_exists = await self.db.execute_query(check_query, table_name)
            
            if not table_exists or not table_exists[0]['exists']:
                logger.warning(f"Vector table {table_name} does not exist")
                return []
            
            # Search using vector similarity
            search_query = f"""
                SELECT content, 1 - (embedding <=> $1::vector) as similarity
                FROM {table_name}
                ORDER BY embedding <=> $1::vector
                LIMIT $2;
            """
            
            # Get embedding for the query using a simple approach
            # For now, we'll do a text search fallback
            fallback_query = f"""
                SELECT content
                FROM {table_name}
                WHERE content ILIKE $1
                LIMIT $2;
            """
            
            results = await self.db.execute_query(fallback_query, f"%{query}%", k)
            
            if results:
                return [row['content'] for row in results]
            else:
                return []
                
        except Exception as e:
            logger.error(f"Error searching vector table {table_name}: {e}")
            return []

    async def generate_lecture(self, request: LectureRequest) -> str:
        """Generate lecture for a book with comprehensive parameters"""
        try:
            # Create knowledge retriever tool
            knowledge_tool = self._create_knowledge_search_tool(request.book_title)
            knowledge_tool.name = "knowledge_retriever_tool"

            # Create agent for lecture generation
            tools = [knowledge_tool]
            current_llm = self.get_current_llm()
            
            try:
                agent = create_tool_calling_agent(current_llm, tools, self.lecture_prompt)
                agent_executor = AgentExecutor(
                    agent=agent, 
                    tools=tools, 
                    verbose=False,
                    handle_parsing_errors=True,
                    max_iterations=5,
                    return_intermediate_steps=False
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
            
            # Create focused input for agent
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
                
                # Clean the output
                cleaned_output = self._clean_lecture_output(result['output'])
                return cleaned_output
                
            except Exception as execution_error:
                logger.error(f"Error during agent execution: {execution_error}")
                
                # Fallback to direct generation
                error_str = str(execution_error).lower()
                if "parsing" in error_str or "tool" in error_str:
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
            table_name = request.book_title.lower().replace(' ', '_').replace('-', '_')
            
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
            
            return self._clean_lecture_output(result)
            
        except Exception as e:
            logger.error(f"Error in fallback lecture generation: {e}")
            return f"I apologize, but I encountered an error generating the lecture: {str(e)}"

    def _clean_lecture_output(self, output: str) -> str:
        """Clean the lecture output to remove unwanted debugging code and tool calls"""
        try:
            import re
            
            # Remove Python code blocks that contain tool calls
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
            return output

    # Lecture Scripts CRUD operations
    async def create_lecture_script(self, user_id: str, request: LectureScriptRequest) -> dict:
        """Create a new lecture script"""
        try:
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
            
            # Handle request attributes
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

    async def get_lecture_script(self, script_id: str, user_id: str) -> Optional[dict]:
        """Get a specific lecture script by ID"""
        try:
            query = """
                SELECT id, user_id, curriculum_id, book_id, title, scope, specific_topics, 
                       specific_books, detail_level, difficulty, duration, content, 
                       script_style, target_audience, include_examples, include_exercises, 
                       include_visual_aids, created_at, updated_at
                FROM lecture_scripts
                WHERE id = $1 AND user_id = $2
            """
            
            result = await self.db.execute_query(query, script_id, user_id)
            
            if result:
                row = result[0]
                
                # Parse specific_books JSON if exists
                specific_books = None
                if row["specific_books"]:
                    try:
                        specific_books = json.loads(row["specific_books"])
                    except:
                        specific_books = None
                
                return {
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
                    "updated_at": row["updated_at"]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting lecture script {script_id}: {e}")
            raise e

    async def get_user_scripts(self, user_id: str) -> List[dict]:
        """Get all lecture scripts for a user"""
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

    async def update_lecture_script(self, script_id: str, user_id: str, request: LectureScriptUpdate) -> Optional[dict]:
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
                RETURNING id, user_id, curriculum_id, book_id, title, scope, specific_topics, 
                         specific_books, detail_level, difficulty, duration, content, 
                         script_style, target_audience, include_examples, include_exercises, 
                         include_visual_aids, created_at, updated_at
            """
            
            result = await self.db.execute_query(query, *values)
            
            if result:
                row = result[0]
                
                # Parse specific_books JSON if exists
                specific_books = None
                if row["specific_books"]:
                    try:
                        specific_books = json.loads(row["specific_books"])
                    except:
                        specific_books = None
                
                return {
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
        """Generate script based on curriculum scope"""
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
        """Generate script covering whole curriculum"""
        try:
            curriculum_id = request['curriculum_id']
            title = request.get('title', 'Comprehensive Curriculum Overview')
            detail_level = request.get('detail_level', 'overview')
            
            logger.info(f"Generating whole curriculum script for curriculum {curriculum_id}")
            
            # Get curriculum books
            curriculum_books = await self._get_curriculum_books(curriculum_id)
            book_titles = [book['title'] for book in curriculum_books]
            
            # Extract curriculum-wide topics
            curriculum_topics = await self._extract_curriculum_wide_topics(curriculum_id)
            
            script_prompt = f"""Create a comprehensive lecture script covering the entire curriculum:

**Title:** {title}
**Scope:** Whole Curriculum ({len(curriculum_books)} books)
**Detail Level:** {detail_level}
**Books Covered:** {', '.join(book_titles)}

**Key Topics:**
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
            
            script_content = await self.llm.ainvoke(script_prompt)
            return script_content.content if hasattr(script_content, 'content') else str(script_content)
            
        except Exception as e:
            logger.error(f"Error generating curriculum script: {e}")
            raise e

    async def _generate_book_script(self, request: dict) -> str:
        """Generate script for whole book"""
        try:
            curriculum_id = request['curriculum_id']
            book_ids = request['specific_books']
            title = request.get('title', 'Comprehensive Book Analysis')
            detail_level = request.get('detail_level', 'detailed')
            
            if not book_ids:
                raise ValueError("No books specified")
            
            logger.info(f"Generating book script for book(s) {book_ids}")
            
            # Get book details
            book_details = []
            for book_id in book_ids:
                book_info = await self._get_book_info(book_id)
                if book_info:
                    book_details.append(book_info)
            
            if not book_details:
                raise ValueError("No valid books found")
            
            book_titles = [book['title'] for book in book_details]
            
            script_prompt = f"""Create a comprehensive lecture script for the specified book(s):

**Title:** {title}
**Scope:** Whole Book Analysis
**Detail Level:** {detail_level}
**Book(s):** {', '.join(book_titles)}

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
            
            script_content = await self.llm.ainvoke(script_prompt)
            return script_content.content if hasattr(script_content, 'content') else str(script_content)
            
        except Exception as e:
            logger.error(f"Error generating book script: {e}")
            raise e

    async def _generate_topic_script(self, request: dict) -> str:
        """Generate script for specific topics"""
        try:
            curriculum_id = request['curriculum_id']
            book_ids = request.get('specific_books', [])
            topics = request.get('specific_topics', '')
            title = request.get('title', 'Focused Topic Analysis')
            detail_level = request.get('detail_level', 'detailed')
            
            if not topics.strip():
                raise ValueError("No specific topics provided")
            
            logger.info(f"Generating topic script for topics: {topics}")
            
            # Parse topics
            topic_list = [topic.strip() for topic in topics.split(',') if topic.strip()]
            
            # Get context from specified books or curriculum
            context_books = []
            if book_ids:
                for book_id in book_ids:
                    book_info = await self._get_book_info(book_id)
                    if book_info:
                        context_books.append(book_info['title'])
            else:
                curriculum_books = await self._get_curriculum_books(curriculum_id)
                context_books = [book['title'] for book in curriculum_books[:5]]
            
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

Focus exclusively on the specified topics with deep analysis."""
            
            script_content = await self.llm.ainvoke(script_prompt)
            return script_content.content if hasattr(script_content, 'content') else str(script_content)
            
        except Exception as e:
            logger.error(f"Error generating topic script: {e}")
            raise e

    # Helper methods
    async def _get_curriculum_books(self, curriculum_id: str) -> List[dict]:
        """Get all books in a curriculum"""
        try:
            query = """
                SELECT b.id, b.title, b.author, b.description
                FROM curriculum_books cb
                JOIN books b ON cb.book_id = b.id
                WHERE cb.curriculum_id = $1
                ORDER BY b.title
            """
            
            result = await self.db.execute_query(query, curriculum_id)
            return [{"id": row["id"], "title": row["title"], "author": row["author"], "description": row["description"]} for row in result] if result else []
            
        except Exception as e:
            logger.error(f"Error getting curriculum books: {e}")
            return []

    async def _get_book_info(self, book_id: str) -> Optional[dict]:
        """Get book information by ID"""
        try:
            query = """
                SELECT id, title, author, description
                FROM books
                WHERE id = $1
            """
            
            result = await self.db.execute_query(query, book_id)
            if result:
                row = result[0]
                return {
                    "id": row["id"],
                    "title": row["title"],
                    "author": row["author"],
                    "description": row["description"]
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting book info for {book_id}: {e}")
            return None

    async def _extract_curriculum_wide_topics(self, curriculum_id: str) -> List[str]:
        """Extract topics from all books in curriculum"""
        try:
            # Get all books in curriculum
            books = await self._get_curriculum_books(curriculum_id)
            
            all_topics = []
            for book in books:
                # Extract topics from book table of contents or content
                topics = await self._extract_topics_from_book_toc(book['title'])
                all_topics.extend(topics)
            
            # Remove duplicates and return unique topics
            return list(set(all_topics))
            
        except Exception as e:
            logger.error(f"Error extracting curriculum topics: {e}")
            return []

    async def _extract_topics_from_book_toc(self, book_title: str) -> List[str]:
        """Extract topics from book table of contents"""
        try:
            # Search for table of contents or chapter information
            table_name = book_title.lower().replace(' ', '_').replace('-', '_')
            
            # Look for content that might be table of contents
            toc_content = await self._search_vector_table(table_name, "table of contents chapters topics overview", k=10)
            
            if toc_content:
                # Simple extraction of potential topics from content
                topics = []
                for content in toc_content:
                    # Extract potential topic lines (simple heuristic)
                    lines = content.split('\n')
                    for line in lines:
                        line = line.strip()
                        # Look for chapter-like or topic-like entries
                        if len(line) > 10 and len(line) < 100 and any(keyword in line.lower() for keyword in ['chapter', 'section', 'part', 'unit', 'lesson']):
                            topics.append(line)
                
                return topics[:15]  # Limit to reasonable number
            
            return []
            
        except Exception as e:
            logger.error(f"Error extracting topics from book TOC: {e}")
            return []