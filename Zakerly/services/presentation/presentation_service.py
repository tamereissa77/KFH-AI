import logging
from typing import List, Optional, Dict, Any
import json
import os
import asyncio
from contextlib import asynccontextmanager
import asyncpg

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

import sys
sys.path.append('/app/shared')

from database import DatabaseManager
from utils import RedisManager

logger = logging.getLogger(__name__)

class PresentationService:
    def __init__(self):
        # Initialize database and redis
        self.db = DatabaseManager(os.getenv("DATABASE_URL"))
        self.redis = RedisManager(os.getenv("REDIS_URL", "redis://redis:6379/0"))
        
        # Initialize embeddings
        self.embeddings = OllamaEmbeddings(
            model=os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:latest"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
        )
        
        # Primary LLM (Google Gemini)
        gemini_model = os.getenv("CHAT_MODEL_NAME", "gemini-2.0-flash-exp")
        try:
            self.llm = ChatGoogleGenerativeAI(
                model=gemini_model,
                temperature=float(os.getenv("CHAT_MODEL_TEMPERATURE", "0.7")),
                google_api_key=os.getenv("GOOGLE_API_KEY"),
                top_k=40,
                top_p=0.8,
                max_tokens=4096,
                convert_system_message_to_human=True
            )
        except Exception as llm_init_error:
            logger.warning(f"⚠️ Primary LLM initialization failed: {llm_init_error}")
            self.llm = ChatGoogleGenerativeAI(
                model=gemini_model,
                temperature=0.7,
                google_api_key=os.getenv("GOOGLE_API_KEY"),
                convert_system_message_to_human=True
            )
        
        self.connection_string = os.getenv("DATABASE_URL")
        logger.info(f"✅ PresentationService initialized with {gemini_model}")

    async def cleanup(self):
        """Cleanup resources"""
        pass

    def get_current_llm(self):
        """Get the current LLM instance"""
        return self.llm

    @asynccontextmanager
    async def get_db_connection(self):
        """Get database connection from pool"""
        conn = await asyncpg.connect(self.connection_string)
        try:
            yield conn
        finally:
            await conn.close()

    # ==================== MAIN ENTRY POINT ====================
    
    async def generate_curriculum_presentation(
        self,
        user_id: str,
        curriculum_id: Optional[int] = None,
        book_id: Optional[int] = None,
        title: str = "Presentation",
        scope: str = "whole_curriculum",
        specific_topics: Optional[str] = None,
        detail_level: str = "detailed",
        difficulty: str = "intermediate",
        slides_count: int = 15,
        slide_style: str = "professional",
        include_diagrams: bool = True,
        include_code_examples: bool = False
    ) -> Dict[str, Any]:
        """Main entry point - Generate presentation using sophisticated 3-case system"""
        try:
            logger.info(f"🎯 PRESENTATION SERVICE: Generation started")
            logger.info(f"Request: curriculum_id={curriculum_id}, book_id={book_id}, scope={scope}")
            
            # CASE 1: Whole Curriculum Presentation
            if scope == 'whole_curriculum':
                logger.info("🌟 CASE 1: Generating presentation for WHOLE CURRICULUM")
                return await self._generate_curriculum_presentation(
                    curriculum_id, title, detail_level, difficulty, 
                    slides_count, slide_style, include_diagrams, include_code_examples
                )
            
            # CASE 2: Single Book Presentation
            elif scope == 'whole_book':
                logger.info("📚 CASE 2: Generating presentation for WHOLE BOOK")
                return await self._generate_book_presentation(
                    book_id, title, detail_level, difficulty,
                    slides_count, slide_style, include_diagrams, include_code_examples
                )
            
            # CASE 3: Specific Topics Presentation
            elif scope == 'specific_topics':
                logger.info("🎯 CASE 3: Generating presentation for SPECIFIC TOPICS")
                return await self._generate_topic_presentation(
                    curriculum_id, book_id, specific_topics, title, detail_level,
                    difficulty, slides_count, slide_style, include_diagrams, include_code_examples
                )
            
            else:
                raise ValueError(f"Invalid scope: {scope}")
                
        except Exception as e:
            logger.error(f"❌ Error generating presentation: {e}")
            raise e

    # ==================== CASE 1: CURRICULUM PRESENTATION ====================
    
    async def _generate_curriculum_presentation(
        self, curriculum_id: int, title: str, detail_level: str,
        difficulty: str, slides_count: int, slide_style: str,
        include_diagrams: bool, include_code_examples: bool
    ) -> Dict[str, Any]:
        """CASE 1: Comprehensive curriculum-wide presentation generation"""
        try:
            logger.info(f"🌟 CASE 1 START: Curriculum presentation for ID {curriculum_id}")
            logger.info(f"📖 STEP 1: Extracting curriculum-wide topics")
            
            # Step 1: Extract curriculum-wide topics using 4-method approach
            curriculum_topics = await self._extract_curriculum_wide_topics(curriculum_id)
            
            if not curriculum_topics:
                logger.warning("⚠️ No topics extracted, using fallback")
                curriculum_topics = ["Overview", "Core Concepts", "Key Technologies", "Best Practices"]
            
            logger.info(f"✅ STEP 1 DONE: Found {len(curriculum_topics)} curriculum topics")
            
            # Step 2: Get curriculum info
            logger.info(f"📚 STEP 2: Getting curriculum information")
            curriculum_info = await self.db.get_curriculum_by_id(curriculum_id)
            curriculum_name = curriculum_info['name'] if curriculum_info else "Curriculum"
            
            # Get books in curriculum
            curriculum_books = await self._get_curriculum_books(curriculum_id)
            book_titles = [book['title'] for book in curriculum_books]
            
            logger.info(f"✅ STEP 2 DONE: Found {len(curriculum_books)} books")
            
            # Step 3: Search for comprehensive content
            logger.info(f"🔍 STEP 3: Searching for content chunks")
            
            # Limit topics for content search
            search_topics = curriculum_topics[:15]
            all_chunks = []
            
            for topic in search_topics:
                chunks = await self._search_curriculum_embeddings(
                    curriculum_name,
                    topic,
                    k=3
                )
                all_chunks.extend(chunks)
            
            logger.info(f"✅ STEP 3 DONE: Retrieved {len(all_chunks)} content chunks")
            
            # Step 4: Generate presentation with LLM
            logger.info(f"✍️ STEP 4: Generating presentation slides")
            
            presentation_content = await self._generate_presentation_with_llm(
                title=title,
                context_type="curriculum",
                context_name=curriculum_name,
                topics=curriculum_topics,
                content_chunks=all_chunks,
                books=book_titles,
                detail_level=detail_level,
                difficulty=difficulty,
                slides_count=slides_count,
                slide_style=slide_style,
                include_diagrams=include_diagrams,
                include_code_examples=include_code_examples
            )
            
            logger.info(f"✅ STEP 4 DONE: Presentation generated with {presentation_content.get('total_slides', 0)} slides")
            
            return presentation_content
            
        except Exception as e:
            logger.error(f"❌ CASE 1 ERROR: {e}")
            raise e

    # ==================== CASE 2: BOOK PRESENTATION ====================
    
    async def _generate_book_presentation(
        self, book_id: int, title: str, detail_level: str,
        difficulty: str, slides_count: int, slide_style: str,
        include_diagrams: bool, include_code_examples: bool
    ) -> Dict[str, Any]:
        """CASE 2: Single book presentation generation"""
        try:
            logger.info(f"📚 CASE 2 START: Book presentation for ID {book_id}")
            logger.info(f"📖 STEP 1: Extracting book topics from TOC")
            
            # Step 1: Extract topics from book TOC
            book_topics = await self._extract_book_topics(book_id)
            
            if not book_topics:
                logger.warning("⚠️ No topics extracted, using fallback")
                book_topics = ["Overview", "Main Content", "Summary"]
            
            logger.info(f"✅ STEP 1 DONE: Found {len(book_topics)} book topics")
            
            # Step 2: Get book info
            logger.info(f"📚 STEP 2: Getting book information")
            book_info = await self.db.get_book_by_id(book_id)
            book_title = book_info['title'] if book_info else "Book"
            
            logger.info(f"✅ STEP 2 DONE: Book - {book_title}")
            
            # Step 3: Search for book content
            logger.info(f"🔍 STEP 3: Searching for book content")
            
            all_chunks = []
            search_topics = book_topics[:12]
            
            for topic in search_topics:
                chunks = await self._search_book_embeddings(book_id, topic, k=3)
                all_chunks.extend(chunks)
            
            logger.info(f"✅ STEP 3 DONE: Retrieved {len(all_chunks)} content chunks")
            
            # Step 4: Generate presentation
            logger.info(f"✍️ STEP 4: Generating book presentation")
            
            presentation_content = await self._generate_presentation_with_llm(
                title=title,
                context_type="book",
                context_name=book_title,
                topics=book_topics,
                content_chunks=all_chunks,
                books=[book_title],
                detail_level=detail_level,
                difficulty=difficulty,
                slides_count=slides_count,
                slide_style=slide_style,
                include_diagrams=include_diagrams,
                include_code_examples=include_code_examples
            )
            
            logger.info(f"✅ STEP 4 DONE: Presentation generated with {presentation_content.get('total_slides', 0)} slides")
            
            return presentation_content
            
        except Exception as e:
            logger.error(f"❌ CASE 2 ERROR: {e}")
            raise e

    # ==================== CASE 3: TOPIC PRESENTATION ====================
    
    async def _generate_topic_presentation(
        self, curriculum_id: Optional[int], book_id: Optional[int],
        specific_topics: str, title: str, detail_level: str,
        difficulty: str, slides_count: int, slide_style: str,
        include_diagrams: bool, include_code_examples: bool
    ) -> Dict[str, Any]:
        """CASE 3: Topic-focused presentation generation"""
        try:
            logger.info(f"🎯 CASE 3 START: Topic presentation")
            logger.info(f"📖 STEP 1: Parsing specific topics")
            
            # Step 1: Parse topics
            topics = [t.strip() for t in specific_topics.split(',') if t.strip()]
            
            if not topics:
                raise ValueError("No valid topics provided")
            
            logger.info(f"✅ STEP 1 DONE: Found {len(topics)} topics: {topics}")
            
            # Step 2: Get context info
            logger.info(f"📚 STEP 2: Getting context information")
            context_name = "Topics"
            
            if book_id:
                book_info = await self.db.get_book_by_id(book_id)
                context_name = book_info['title'] if book_info else "Book"
            elif curriculum_id:
                curriculum_info = await self.db.get_curriculum_by_id(curriculum_id)
                context_name = curriculum_info['name'] if curriculum_info else "Curriculum"
            
            logger.info(f"✅ STEP 2 DONE: Context - {context_name}")
            
            # Step 3: Enhanced search for each topic
            logger.info(f"🔍 STEP 3: Searching for topic content")
            
            all_chunks = []
            for topic in topics:
                if book_id:
                    chunks = await self._search_book_embeddings(book_id, topic, k=5)
                elif curriculum_id:
                    chunks = await self._search_curriculum_embeddings(context_name, topic, k=5)
                else:
                    raise ValueError("Must provide either book_id or curriculum_id")
                
                all_chunks.extend(chunks)
            
            logger.info(f"✅ STEP 3 DONE: Retrieved {len(all_chunks)} content chunks")
            
            # Step 4: Generate focused presentation
            logger.info(f"✍️ STEP 4: Generating topic-focused presentation")
            
            presentation_content = await self._generate_presentation_with_llm(
                title=title,
                context_type="topics",
                context_name=context_name,
                topics=topics,
                content_chunks=all_chunks,
                books=[context_name],
                detail_level=detail_level,
                difficulty=difficulty,
                slides_count=slides_count,
                slide_style=slide_style,
                include_diagrams=include_diagrams,
                include_code_examples=include_code_examples
            )
            
            logger.info(f"✅ STEP 4 DONE: Presentation generated with {presentation_content.get('total_slides', 0)} slides")
            
            return presentation_content
            
        except Exception as e:
            logger.error(f"❌ CASE 3 ERROR: {e}")
            raise e

    # ==================== LLM GENERATION ====================
    
    async def _generate_presentation_with_llm(
        self, title: str, context_type: str, context_name: str,
        topics: List[str], content_chunks: List[Dict], books: List[str],
        detail_level: str, difficulty: str, slides_count: int,
        slide_style: str, include_diagrams: bool, include_code_examples: bool
    ) -> Dict[str, Any]:
        """Generate presentation using LLM with sophisticated prompting"""
        
        # Prepare content
        content_preview = "\n\n".join([
            f"Section {i+1}:\n{chunk.get('content', '')[:600]}"
            for i, chunk in enumerate(content_chunks[:20])
        ])
        
        # Prepare content preview - escape any curly braces to prevent template conflicts
        content_preview_text = content_preview.replace('{', '{{').replace('}', '}}')
        topics_str = "\n".join([f"- {topic}" for topic in topics])
        books_str = ", ".join(books[:5])
        
        # Adjust style instructions
        style_instructions = {
            "professional": "Use clean, corporate design with minimal text, strong headlines, and professional color schemes. Focus on clarity and authority.",
            "creative": "Use engaging visuals, creative layouts, varied slide designs, and storytelling elements. Make it memorable and visually appealing.",
            "minimal": "Use minimalist design with maximum white space, single key points per slide, and simple visuals. Less is more."
        }
        
        style_guide = style_instructions.get(slide_style, style_instructions["professional"])
        
        # Build prompt using string concatenation to avoid f-string issues with content
        system_prompt = """You are an expert presentation designer and educational content creator. You specialize in creating compelling, professional presentations that effectively communicate complex information.

Your task is to create a """ + str(slides_count) + """-slide presentation about \"""" + title + """\".""" + """

**Style Guide**: """ + style_guide + """

**Detail Level**: """ + detail_level.upper() + """
- Overview: High-level concepts, broad strokes, minimal detail
- Detailed: Moderate depth, key details included, balanced coverage
- Comprehensive: Deep dive, extensive detail, thorough coverage

**Difficulty Level**: """ + difficulty.upper() + """
- Beginner: Simple language, basic concepts, lots of explanations
- Intermediate: Technical but accessible, assumes some background
- Advanced: Expert-level content, technical depth, sophisticated concepts

**Visual Requirements**:
- Include diagrams: """ + str(include_diagrams) + """
- Include code examples: """ + str(include_code_examples) + """

**CRITICAL RULES**:
1. Create EXACTLY """ + str(slides_count) + """ slides (no more, no less)
2. Each slide must have: title, content (2-5 bullet points), visual_suggestions (if applicable), speaker_notes
3. First slide must be title slide
4. Last slide must be summary/conclusion
5. Content slides must cover all major topics
6. Keep bullet points concise (max 15 words each)
7. Provide actionable visual suggestions for diagrams/images
8. Speaker notes should be brief but helpful (2-3 sentences)

**Output Format** (JSON):
{
  "title": "Presentation Title Here",
  "slides": [
    {
      "slide_number": 1,
      "title": "Presentation Title",
      "content": ["Subtitle or tagline", "Presenter info"],
      "visual_suggestions": ["Background image suggestion", "Logo placement"],
      "speaker_notes": "Opening remarks and introduction"
    },
    {
      "slide_number": 2,
      "title": "Main Topic 1",
      "content": ["Key point 1", "Key point 2", "Key point 3"],
      "visual_suggestions": ["Diagram showing X", "Icon for Y"],
      "speaker_notes": "Explanation and transition notes"
    }
  ],
  "total_slides": """ + str(slides_count) + """,
  "estimated_duration": 30
}

**Context**: """ + context_type.upper() + """ - """ + context_name + """
**Books/Sources**: """ + books_str + """

**Topics to Cover**:
""" + topics_str + """

**Available Content**:
""" + content_preview_text + """

Generate the presentation now. Return ONLY valid JSON, no additional text."""

        try:
            # Generate with LLM - use direct prompt without template variables
            response = await self.llm.ainvoke(system_prompt)
            
            # Extract content from response
            if hasattr(response, 'content'):
                response_text = response.content
            else:
                response_text = str(response)
            
            # Parse JSON response
            # Clean response (remove markdown code blocks if present)
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            presentation_data = json.loads(response_text)
            
            # Validate structure
            if "slides" not in presentation_data:
                raise ValueError("Invalid presentation format: missing 'slides'")
            
            if len(presentation_data["slides"]) != slides_count:
                logger.warning(f"⚠️ Slide count mismatch: expected {slides_count}, got {len(presentation_data['slides'])}")
            
            presentation_data["total_slides"] = len(presentation_data["slides"])
            
            # Calculate estimated duration (2-3 minutes per slide)
            if "estimated_duration" not in presentation_data:
                presentation_data["estimated_duration"] = len(presentation_data["slides"]) * 2
            
            return presentation_data
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response: {response[:500]}")
            raise ValueError(f"Failed to generate valid presentation format: {e}")
        except Exception as e:
            logger.error(f"❌ Error in LLM generation: {e}")
            raise e

    # ==================== TOPIC EXTRACTION METHODS ====================
    
    async def _extract_curriculum_wide_topics(self, curriculum_id: int) -> List[str]:
        """Extract comprehensive curriculum topics using 4-method approach"""
        try:
            all_topics = []
            
            # METHOD 1: Extract from all books' TOCs
            logger.info("📚 METHOD 1: Extracting from all books' TOCs")
            toc_topics = await self._extract_topics_from_all_books_toc(curriculum_id)
            all_topics.extend(toc_topics)
            logger.info(f"  ✓ METHOD 1: Found {len(toc_topics)} topics from TOCs")
            
            # METHOD 2: Extract from curriculum overview/description
            logger.info("📋 METHOD 2: Extracting from curriculum overview")
            overview_topics = await self._extract_topics_from_curriculum_overview(curriculum_id)
            all_topics.extend(overview_topics)
            logger.info(f"  ✓ METHOD 2: Found {len(overview_topics)} topics from overview")
            
            # METHOD 3: Analyze curriculum content
            logger.info("📖 METHOD 3: Analyzing curriculum content")
            content_topics = await self._extract_topics_from_curriculum_content(curriculum_id)
            all_topics.extend(content_topics)
            logger.info(f"  ✓ METHOD 3: Found {len(content_topics)} topics from content")
            
            # METHOD 4: Extract keywords from random chunks
            logger.info("🎲 METHOD 4: Extracting keywords from random chunks")
            keyword_topics = await self._extract_keywords_from_random_chunks(curriculum_id)
            all_topics.extend(keyword_topics)
            logger.info(f"  ✓ METHOD 4: Found {len(keyword_topics)} topics from keywords")
            
            # Deduplicate and rank
            final_topics = await self._deduplicate_and_rank_topics(all_topics)
            logger.info(f"✅ FINAL: {len(final_topics)} unique topics after deduplication")
            
            return final_topics[:20]  # Return top 20 topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting curriculum topics: {e}")
            return []

    async def _extract_topics_from_all_books_toc(self, curriculum_id: int) -> List[str]:
        """METHOD 1: Extract topics from all books' TOCs"""
        try:
            curriculum_info = await self.db.get_curriculum_by_id(curriculum_id)
            curriculum_name = curriculum_info['name'] if curriculum_info else ""
            
            books = await self._get_curriculum_books(curriculum_id)
            all_topics = []
            
            for book in books[:5]:  # Limit to first 5 books
                book_id = book['id']
                book_topics = await self._extract_book_topics(book_id)
                all_topics.extend(book_topics)
            
            return all_topics
            
        except Exception as e:
            logger.error(f"Error in METHOD 1: {e}")
            return []

    async def _extract_topics_from_curriculum_overview(self, curriculum_id: int) -> List[str]:
        """METHOD 2: Extract from curriculum overview"""
        try:
            curriculum_info = await self.db.get_curriculum_by_id(curriculum_id)
            if not curriculum_info:
                return []
            
            curriculum_name = curriculum_info['name']
            description = curriculum_info.get('description', '')
            
            # Search for overview content
            overview_chunks = await self._search_curriculum_embeddings(
                curriculum_name,
                f"overview introduction objectives {curriculum_name}",
                k=5
            )
            
            if not overview_chunks:
                return []
            
            # Extract topics with LLM
            content = "\n\n".join([chunk.get('content', '')[:500] for chunk in overview_chunks])
            
            prompt = f"""Extract 5-8 main topics or concepts from this curriculum overview.
Return only a comma-separated list of topics.

Overview:
{content[:2000]}

Topics:"""
            
            llm_prompt = ChatPromptTemplate.from_messages([("human", prompt)])
            chain = llm_prompt | self.llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            topics = [t.strip() for t in response.split(',') if t.strip()]
            return topics[:8]
            
        except Exception as e:
            logger.error(f"Error in METHOD 2: {e}")
            return []

    async def _extract_topics_from_curriculum_content(self, curriculum_id: int) -> List[str]:
        """METHOD 3: Analyze curriculum content"""
        try:
            curriculum_info = await self.db.get_curriculum_by_id(curriculum_id)
            if not curriculum_info:
                return []
            
            curriculum_name = curriculum_info['name']
            
            # Search for various content types
            searches = [
                f"{curriculum_name} main concepts",
                f"{curriculum_name} key topics",
                f"{curriculum_name} important features"
            ]
            
            all_chunks = []
            for search_query in searches:
                chunks = await self._search_curriculum_embeddings(curriculum_name, search_query, k=3)
                all_chunks.extend(chunks)
            
            if not all_chunks:
                return []
            
            # Extract topics from content
            content = "\n\n".join([chunk.get('content', '')[:400] for chunk in all_chunks[:6]])
            
            prompt = f"""Analyze this content and extract 6-8 main topics, concepts, or themes.
Return only a comma-separated list.

Content:
{content[:2000]}

Topics:"""
            
            llm_prompt = ChatPromptTemplate.from_messages([("human", prompt)])
            chain = llm_prompt | self.llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            topics = [t.strip() for t in response.split(',') if t.strip()]
            return topics[:8]
            
        except Exception as e:
            logger.error(f"Error in METHOD 3: {e}")
            return []

    async def _extract_keywords_from_random_chunks(self, curriculum_id: int) -> List[str]:
        """METHOD 4: Extract keywords from random chunks"""
        try:
            curriculum_info = await self.db.get_curriculum_by_id(curriculum_id)
            if not curriculum_info:
                return []
            
            curriculum_name = curriculum_info['name']
            
            # Get random content chunks
            chunks = await self._search_curriculum_embeddings(
                curriculum_name,
                curriculum_name,  # Just search curriculum name
                k=10
            )
            
            if not chunks:
                return []
            
            # Extract keywords
            content = "\n\n".join([chunk.get('content', '')[:300] for chunk in chunks[:8]])
            
            prompt = f"""Extract 8-10 key technical terms, concepts, or topics from this content.
Return only a comma-separated list of keywords/topics.

Content:
{content[:2000]}

Keywords:"""
            
            llm_prompt = ChatPromptTemplate.from_messages([("human", prompt)])
            chain = llm_prompt | self.llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            keywords = [k.strip() for k in response.split(',') if k.strip()]
            return keywords[:10]
            
        except Exception as e:
            logger.error(f"Error in METHOD 4: {e}")
            return []

    async def _extract_book_topics(self, book_id: int) -> List[str]:
        """Extract topics from book TOC"""
        try:
            # Search for TOC content
            toc_chunks = await self._search_for_toc_content(book_id)
            
            if not toc_chunks:
                logger.warning(f"No TOC found for book {book_id}")
                return []
            
            # Parse TOC with LLM
            topics = await self._parse_toc_topics(toc_chunks)
            return topics
            
        except Exception as e:
            logger.error(f"Error extracting book topics: {e}")
            return []

    async def _search_for_toc_content(self, book_id: int) -> List[Dict]:
        """Search for table of contents"""
        try:
            toc_queries = [
                "table of contents",
                "contents",
                "chapter",
                "chapters overview"
            ]
            
            all_toc_chunks = []
            for query in toc_queries:
                chunks = await self._search_book_embeddings(book_id, query, k=2)
                all_toc_chunks.extend(chunks)
            
            # Deduplicate
            seen = set()
            unique_chunks = []
            for chunk in all_toc_chunks:
                content = chunk.get('content', '')
                if content not in seen:
                    seen.add(content)
                    unique_chunks.append(chunk)
            
            return unique_chunks[:8]
            
        except Exception as e:
            logger.error(f"Error searching for TOC: {e}")
            return []

    async def _parse_toc_topics(self, toc_chunks: List[Dict]) -> List[str]:
        """Parse TOC to extract topics"""
        try:
            toc_content = "\n\n".join([chunk.get('content', '')[:600] for chunk in toc_chunks])
            
            prompt = f"""Extract the main chapter titles and section topics from this table of contents.
Return only a comma-separated list of topics (8-12 topics).

Table of Contents:
{toc_content[:2500]}

Topics:"""
            
            llm_prompt = ChatPromptTemplate.from_messages([("human", prompt)])
            chain = llm_prompt | self.llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            topics = [t.strip() for t in response.split(',') if t.strip()]
            return topics[:12]
            
        except Exception as e:
            logger.error(f"Error parsing TOC: {e}")
            return []

    async def _deduplicate_and_rank_topics(self, topics: List[str]) -> List[str]:
        """Deduplicate and rank topics by frequency"""
        try:
            # Count frequency
            topic_count = {}
            for topic in topics:
                topic_lower = topic.lower().strip()
                if len(topic_lower) > 3:  # Ignore very short topics
                    topic_count[topic_lower] = topic_count.get(topic_lower, 0) + 1
            
            # Sort by frequency
            sorted_topics = sorted(topic_count.items(), key=lambda x: x[1], reverse=True)
            
            # Return unique topics (use original case from first occurrence)
            unique_topics = []
            for topic_lower, _ in sorted_topics:
                # Find original case
                for original_topic in topics:
                    if original_topic.lower().strip() == topic_lower:
                        unique_topics.append(original_topic)
                        break
            
            return unique_topics
            
        except Exception as e:
            logger.error(f"Error deduplicating topics: {e}")
            return list(set(topics))

    # ==================== SEARCH METHODS ====================
    
    async def _search_curriculum_embeddings(
        self, curriculum_name: str, query: str, k: int = 5
    ) -> List[Dict]:
        """Search curriculum embeddings"""
        try:
            # Generate query embedding
            query_embedding = await self.embeddings.aembed_query(query)
            
            # Convert embedding list to string format for PostgreSQL vector type
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            # Get the curriculum-specific table name
            table_name = f"curriculum_embeddings_{curriculum_name.lower().replace(' ', '_')}"
            
            async with self.get_db_connection() as conn:
                query_sql = f"""
                    SELECT 
                        ce.id,
                        ce.book_id,
                        ce.content,
                        ce.metadata,
                        ce.embedding <=> $1::vector AS distance
                    FROM {table_name} ce
                    ORDER BY ce.embedding <=> $1::vector
                    LIMIT $2
                """
                
                results = await conn.fetch(query_sql, embedding_str, k)
                
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Error searching curriculum embeddings: {e}")
            return []

    async def _search_book_embeddings(self, book_id: int, query: str, k: int = 5) -> List[Dict]:
        """Search book embeddings"""
        try:
            # Get book info to find curriculum
            book_info = await self.db.get_book_by_id(book_id)
            if not book_info:
                logger.error(f"Book {book_id} not found")
                return []
            
            curriculum_id = book_info.get('curriculum_id')
            if not curriculum_id:
                logger.error(f"Book {book_id} has no curriculum_id")
                return []
            
            # Get curriculum info to find the table name
            curriculum_info = await self.db.get_curriculum_by_id(curriculum_id)
            if not curriculum_info:
                logger.error(f"Curriculum {curriculum_id} not found")
                return []
            
            curriculum_name = curriculum_info['name']
            
            # Generate query embedding
            query_embedding = await self.embeddings.aembed_query(query)
            
            # Convert embedding list to string format for PostgreSQL vector type
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            # Get the correct curriculum embeddings table name
            table_name = f"curriculum_embeddings_{curriculum_name.lower().replace(' ', '_')}"
            
            async with self.get_db_connection() as conn:
                query_sql = f"""
                    SELECT 
                        ce.id,
                        ce.book_id,
                        ce.content,
                        ce.metadata,
                        ce.embedding <=> $1::vector AS distance
                    FROM {table_name} ce
                    WHERE ce.book_id = $2
                    ORDER BY ce.embedding <=> $1::vector
                    LIMIT $3
                """
                
                results = await conn.fetch(query_sql, embedding_str, book_id, k)
                
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Error searching book embeddings: {e}")
            return []

    async def _get_curriculum_books(self, curriculum_id: int) -> List[Dict]:
        """Get all books in curriculum"""
        try:
            async with self.get_db_connection() as conn:
                results = await conn.fetch("""
                    SELECT id, title, author, description
                    FROM books
                    WHERE curriculum_id = $1
                    ORDER BY id
                """, curriculum_id)
                
                return [dict(row) for row in results]
                
        except Exception as e:
            logger.error(f"Error getting curriculum books: {e}")
            return []

    # ==================== DATABASE CRUD OPERATIONS ====================
    
    async def create_presentation(
        self, user_id: str, book_id: Optional[int], title: str,
        scope: str, specific_topics: Optional[str], detail_level: str,
        difficulty: str, slides_count: int, slide_style: str,
        include_diagrams: bool, include_code_examples: bool, content: Dict
    ) -> Dict[str, Any]:
        """Create presentation in database"""
        try:
            async with self.get_db_connection() as conn:
                # ✅ CRITICAL: Validate user exists before creating presentation
                user_check = await conn.fetchrow(
                    "SELECT id FROM users WHERE id = $1",
                    user_id
                )
                
                if not user_check:
                    logger.error(f"❌ User with ID {user_id} not found in database. User needs to log in again.")
                    raise ValueError("User not found. Please log out and log in again to refresh your session.")
                
                logger.info(f"✅ User {user_id} validated successfully")
                
                result = await conn.fetchrow("""
                    INSERT INTO presentations (
                        user_id, book_id, title, scope, specific_topics,
                        detail_level, difficulty, slides_count, slide_style,
                        include_diagrams, include_code_examples, content
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    RETURNING id, user_id, book_id, title, scope, specific_topics,
                              detail_level, difficulty, slides_count, slide_style,
                              include_diagrams, include_code_examples, content,
                              created_at, updated_at
                """, user_id, book_id, title, scope, specific_topics, detail_level,
                    difficulty, slides_count, slide_style, include_diagrams,
                    include_code_examples, json.dumps(content))
                
                return dict(result)
                
        except ValueError as ve:
            # Re-raise validation errors
            raise ve
        except Exception as e:
            logger.error(f"Error creating presentation: {e}")
            raise e

    async def get_presentation(self, presentation_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get presentation by ID"""
        try:
            async with self.get_db_connection() as conn:
                result = await conn.fetchrow("""
                    SELECT id, user_id, book_id, title, scope, specific_topics,
                           detail_level, difficulty, slides_count, slide_style,
                           include_diagrams, include_code_examples, content,
                           created_at, updated_at
                    FROM presentations
                    WHERE id = $1 AND user_id = $2
                """, presentation_id, user_id)
                
                if result:
                    presentation = dict(result)
                    # Parse JSON content
                    if isinstance(presentation['content'], str):
                        presentation['content'] = json.loads(presentation['content'])
                    return presentation
                return None
                
        except Exception as e:
            logger.error(f"Error getting presentation: {e}")
            return None

    async def get_user_presentations(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all presentations for a user"""
        try:
            async with self.get_db_connection() as conn:
                results = await conn.fetch("""
                    SELECT 
                        p.id, p.user_id, p.book_id, p.title, p.scope,
                        p.specific_topics, p.detail_level, p.difficulty,
                        p.slides_count, p.slide_style, p.include_diagrams,
                        p.include_code_examples, p.content, p.created_at, p.updated_at,
                        b.title as book_title,
                        c.name as curriculum_name
                    FROM presentations p
                    LEFT JOIN books b ON p.book_id = b.id
                    LEFT JOIN curriculum c ON b.curriculum_id = c.id
                    WHERE p.user_id = $1
                    ORDER BY p.created_at DESC
                """, user_id)
                
                presentations = []
                for row in results:
                    presentation = dict(row)
                    # Parse JSON content
                    if isinstance(presentation['content'], str):
                        presentation['content'] = json.loads(presentation['content'])
                    presentations.append(presentation)
                
                return presentations
                
        except Exception as e:
            logger.error(f"Error getting user presentations: {e}")
            return []

    async def update_presentation(
        self, presentation_id: str, user_id: str,
        title: Optional[str] = None, content: Optional[Dict] = None
    ) -> Optional[Dict[str, Any]]:
        """Update presentation"""
        try:
            updates = []
            params = []
            param_count = 1
            
            if title:
                updates.append(f"title = ${param_count}")
                params.append(title)
                param_count += 1
            
            if content:
                updates.append(f"content = ${param_count}")
                params.append(json.dumps(content))
                param_count += 1
            
            if not updates:
                return await self.get_presentation(presentation_id, user_id)
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.extend([presentation_id, user_id])
            
            query = f"""
                UPDATE presentations
                SET {', '.join(updates)}
                WHERE id = ${param_count} AND user_id = ${param_count + 1}
                RETURNING id, user_id, book_id, title, scope, specific_topics,
                          detail_level, difficulty, slides_count, slide_style,
                          include_diagrams, include_code_examples, content,
                          created_at, updated_at
            """
            
            async with self.get_db_connection() as conn:
                result = await conn.fetchrow(query, *params)
                
                if result:
                    presentation = dict(result)
                    if isinstance(presentation['content'], str):
                        presentation['content'] = json.loads(presentation['content'])
                    return presentation
                return None
                
        except Exception as e:
            logger.error(f"Error updating presentation: {e}")
            return None

    async def delete_presentation(self, presentation_id: str, user_id: str) -> bool:
        """Delete presentation"""
        try:
            async with self.get_db_connection() as conn:
                result = await conn.execute("""
                    DELETE FROM presentations
                    WHERE id = $1 AND user_id = $2
                """, presentation_id, user_id)
                
                return result == "DELETE 1"
                
        except Exception as e:
            logger.error(f"Error deleting presentation: {e}")
            return False
