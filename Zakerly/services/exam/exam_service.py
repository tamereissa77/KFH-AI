import logging
from typing import List, Optional, Dict, Any
import json
import os
import re
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import asyncpg
from datetime import datetime

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

import sys
sys.path.append('/app/shared')

from models import (
    QuestionGenerationRequest, QuestionResponse, Question
)
from database import DatabaseManager
from utils import RedisManager

logger = logging.getLogger(__name__)

class ExamService:
    def __init__(self, db_manager: DatabaseManager, redis_manager: RedisManager):
        self.db = db_manager
        self.redis = redis_manager
        
        # Initialize LangChain components
        self.embeddings = OllamaEmbeddings(
            model=os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:latest"),
            base_url=os.getenv("OLLAMA_BASE_URL")
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
                max_tokens=2048,
                convert_system_message_to_human=True  # Fix: Gemini doesn't support SystemMessage
            )
        except Exception as llm_init_error:
            logger.warning(f"⚠️ Primary LLM initialization failed: {llm_init_error}")
            self.llm = ChatGoogleGenerativeAI(
                model=gemini_model,
                temperature=0.7,
                google_api_key=os.getenv("GOOGLE_API_KEY"),
                convert_system_message_to_human=True  # Fix: Gemini doesn't support SystemMessage
            )
        
        self.connection_string = os.getenv("DATABASE_URL")
        logger.info(f"✅ ExamService initialized with {gemini_model}")

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

    async def generate_questions(self, request: QuestionGenerationRequest) -> QuestionResponse:
        """Main entry point - Generate questions using sophisticated 3-case system"""
        try:
            logger.info(f"🎯 EXAM SERVICE: Question generation started")
            logger.info(f"Request: curriculum_id={request.curriculum_id}, book={request.book_title}, scope={request.scope_type}")
            
            # Prepare exam parameters
            exam_parameters = {
                'count': request.count or 10,
                'difficulty': request.difficulty or ['medium'],
                'question_types': request.question_types or ['multiple_choice_single_answer'],
                'time_limit': request.time_limit or 30,
                'user_message': request.user_message or '',
                'specific_topics': request.specific_topics or ''
            }
            
            # CASE 1: Whole Curriculum Exam
            if request.scope_type == 'whole_curriculum' and request.curriculum_id:
                logger.info("🌟 CASE 1: Generating questions for WHOLE CURRICULUM")
                
                curriculum_info = await self.db.get_curriculum_by_id(int(request.curriculum_id))
                if not curriculum_info:
                    raise ValueError(f"Curriculum with ID {request.curriculum_id} not found")
                
                curriculum_name = curriculum_info['name']
                
                all_questions = await self._generate_questions_with_curriculum_agent(
                    curriculum_name, exam_parameters
                )
                
                logger.info(f"✅ Generated {len(all_questions)} questions for curriculum {curriculum_name}")
                
                return QuestionResponse(
                    chapter=f"{curriculum_name} Curriculum - Comprehensive Exam",
                    questions_generated=all_questions
                )
            
            # CASE 2: Single Book Exam
            elif request.scope_type == 'whole_book' and request.book_title:
                logger.info("📚 CASE 2: Generating questions for SINGLE BOOK")
                
                book_info = await self._get_book_curriculum_info(request.book_title)
                curriculum_name = book_info.get('curriculum_name') if book_info else 'General Studies'
                
                all_questions = await self._generate_questions_with_book_agent(
                    request.book_title, curriculum_name, exam_parameters
                )
                
                logger.info(f"✅ Generated {len(all_questions)} questions for book {request.book_title}")
                
                return QuestionResponse(
                    chapter=f"{request.book_title} - Comprehensive Book Exam",
                    questions_generated=all_questions
                )
            
            # CASE 3: Specific Topics Exam
            elif request.scope_type == 'specific_topics' and request.specific_topics:
                logger.info("🎯 CASE 3: Generating questions for SPECIFIC TOPICS")
                
                book_title = request.book_title or 'General Book'
                book_info = await self._get_book_curriculum_info(book_title)
                curriculum_name = book_info.get('curriculum_name') if book_info else 'General Studies'
                
                all_questions = await self._generate_questions_with_topic_agent(
                    book_title, curriculum_name, request.specific_topics, exam_parameters
                )
                
                logger.info(f"✅ Generated {len(all_questions)} questions for topics: {request.specific_topics}")
                
                return QuestionResponse(
                    chapter=f"{book_title} - {request.specific_topics}",
                    questions_generated=all_questions
                )
            
            else:
                logger.info("🔄 FALLBACK: Using book-based generation")
                book_title = request.book_title or 'General Content'
                book_info = await self._get_book_curriculum_info(book_title)
                curriculum_name = book_info.get('curriculum_name') if book_info else 'General Studies'
                
                all_questions = await self._generate_questions_with_book_agent(
                    book_title, curriculum_name, exam_parameters
                )
                
                return QuestionResponse(
                    chapter=f"{book_title} - General Exam",
                    questions_generated=all_questions
                )
            
        except Exception as e:
            logger.error(f"❌ Error in question generation: {e}")
            raise

    # ==================== CASE 1: CURRICULUM EXAM ====================
    
    async def _generate_questions_with_curriculum_agent(self, curriculum_name: str, exam_parameters: Dict[str, Any]) -> List[Question]:
        """CASE 1: Systematic curriculum-wide question generation with 3 steps"""
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
            
            # STEP 3: Generate comprehensive questions
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
            import traceback
            logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
            return self._generate_default_questions(exam_parameters, [curriculum_name])

    async def _extract_curriculum_wide_topics(self, curriculum_name: str) -> List[str]:
        """Extract comprehensive topics using 4 methods"""
        try:
            logger.info(f"🌟 Extracting comprehensive topics from entire curriculum '{curriculum_name}'")
            
            all_topics = []
            
            # METHOD 1: Extract from all books' TOCs
            toc_topics = await self._extract_topics_from_all_books_toc(curriculum_name)
            all_topics.extend(toc_topics)
            
            # METHOD 2: Search for curriculum overview
            overview_topics = await self._extract_topics_from_curriculum_overview(curriculum_name)
            all_topics.extend(overview_topics)
            
            # METHOD 3: Content-based keyword analysis
            content_keywords = await self._extract_topics_from_curriculum_content(curriculum_name)
            all_topics.extend(content_keywords)
            
            # METHOD 4: Dynamic random chunk analysis
            random_keywords = await self._extract_keywords_from_random_chunks(curriculum_name)
            all_topics.extend(random_keywords)
            
            # Deduplicate and rank
            final_topics = await self._deduplicate_and_rank_curriculum_topics(all_topics, curriculum_name)
            
            logger.info(f"✅ CURRICULUM TOPICS EXTRACTED: {len(final_topics)} topics")
            return final_topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting curriculum-wide topics: {e}")
            return await self._extract_keywords_from_random_chunks(curriculum_name)

    async def _extract_topics_from_all_books_toc(self, curriculum_name: str) -> List[str]:
        """METHOD 1: Extract topics from TOCs of all books"""
        try:
            logger.info(f"📚 METHOD 1: Extracting from all books' TOCs")
            
            curriculum_info = await self.db.get_curriculum_by_name(curriculum_name)
            if not curriculum_info:
                return []
            
            books = await self.db.get_books_by_curriculum(curriculum_info['id'])
            logger.info(f"📖 Found {len(books)} books in curriculum")
            
            all_book_topics = []
            for book in books:
                book_title = book['title']
                book_topics = await self._extract_book_topics(curriculum_name, book_title)
                if book_topics:
                    all_book_topics.extend(book_topics)
                    logger.info(f"✅ Extracted {len(book_topics)} topics from '{book_title}'")
            
            logger.info(f"📚 TOC METHOD: Total {len(all_book_topics)} topics")
            return all_book_topics
            
        except Exception as e:
            logger.error(f"❌ Error in METHOD 1: {e}")
            return []

    async def _extract_topics_from_curriculum_overview(self, curriculum_name: str) -> List[str]:
        """METHOD 2: Search for curriculum overview/syllabus"""
        try:
            logger.info(f"📋 METHOD 2: Searching for curriculum overview")
            
            overview_queries = [
                "curriculum overview syllabus",
                "program structure objectives",
                "course description main topics"
            ]
            
            overview_chunks = []
            for query in overview_queries:
                chunks = await self._search_curriculum_embeddings(curriculum_name, query, k=3)
                if chunks:
                    overview_chunks.extend(chunks)
            
            if not overview_chunks:
                return []
            
            overview_content = "\n\n".join([chunk['content'] for chunk in overview_chunks[:5]])
            topics = await self._extract_topics_using_llm(overview_content, curriculum_name, "overview")
            
            logger.info(f"📋 OVERVIEW METHOD: Extracted {len(topics)} topics")
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error in METHOD 2: {e}")
            return []

    async def _extract_topics_from_curriculum_content(self, curriculum_name: str) -> List[str]:
        """METHOD 3: Content-based keyword analysis"""
        try:
            logger.info(f"📊 METHOD 3: Content analysis")
            
            content_queries = [
                "introduction fundamentals",
                "advanced topics concepts",
                "practical applications"
            ]
            
            all_content = []
            for query in content_queries:
                chunks = await self._search_curriculum_embeddings(curriculum_name, query, k=5)
                if chunks:
                    all_content.extend([chunk['content'] for chunk in chunks])
            
            if not all_content:
                return []
            
            combined_content = "\n\n".join(all_content[:10])
            keywords = await self._extract_topics_using_llm(combined_content, curriculum_name, "content")
            
            logger.info(f"📊 CONTENT METHOD: Extracted {len(keywords)} keywords")
            return keywords
            
        except Exception as e:
            logger.error(f"❌ Error in METHOD 3: {e}")
            return []

    async def _extract_keywords_from_random_chunks(self, curriculum_name: str) -> List[str]:
        """METHOD 4: Dynamic random chunk analysis"""
        try:
            logger.info(f"🎲 METHOD 4: Random chunk analysis")
            
            random_chunks = await self._get_random_curriculum_chunks(curriculum_name, count=10)
            
            if not random_chunks:
                return []
            
            combined_content = "\n\n".join([chunk['content'] for chunk in random_chunks])
            keywords = await self._extract_topics_using_llm(combined_content, curriculum_name, "random")
            
            logger.info(f"🎲 RANDOM METHOD: Extracted {len(keywords)} keywords")
            return keywords
            
        except Exception as e:
            logger.error(f"❌ Error in METHOD 4: {e}")
            return []

    async def _extract_topics_using_llm(self, content: str, curriculum_name: str, method_type: str) -> List[str]:
        """Extract topics from content using LLM"""
        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", f"""Extract 10-12 searchable keywords and topics from this {method_type} content.
Return ONLY a JSON array of strings: ["topic1", "topic2", ...]
Focus on specific technical terms, concepts, and subject areas."""),
                ("human", "Content:\n\n{content}\n\nExtract key topics:")
            ])
            
            chain = prompt | self.get_current_llm() | StrOutputParser()
            result = await chain.ainvoke({"content": content[:4000]})
            
            topics = self._parse_topics_from_llm_response(result)
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting topics with LLM: {e}")
            return []

    async def _deduplicate_and_rank_curriculum_topics(self, all_topics: List[str], curriculum_name: str) -> List[str]:
        """Deduplicate and rank topics"""
        try:
            normalized_topics = {}
            for topic in all_topics:
                if topic and len(topic.strip()) > 2:
                    normalized = re.sub(r'\s+', ' ', topic.lower().strip())
                    normalized = re.sub(r'[^\w\s-]', '', normalized)
                    if len(normalized) > 3:
                        normalized_topics[normalized] = topic
            
            topic_counts = Counter(normalized_topics.keys())
            
            top_topics = []
            for normalized_topic, count in topic_counts.most_common(20):
                if len(top_topics) < 15:
                    top_topics.append(normalized_topics[normalized_topic])
            
            if not top_topics:
                top_topics = (await self._extract_keywords_from_random_chunks(curriculum_name))[:10]
            
            logger.info(f"✅ Final topics after deduplication: {len(top_topics)}")
            return top_topics
            
        except Exception as e:
            logger.error(f"❌ Error deduplicating: {e}")
            return all_topics[:15] if all_topics else []

    async def _get_chunks_for_curriculum_topics(self, curriculum_name: str, topics: List[str]) -> List[Dict[str, Any]]:
        """Get content chunks for curriculum topics"""
        try:
            all_chunks = []
            
            for i, topic in enumerate(topics[:10]):
                logger.info(f"📄 Getting chunks for topic {i+1}: '{topic[:30]}...'")
                chunks = await self._search_curriculum_embeddings(curriculum_name, topic, k=3)
                if chunks:
                    all_chunks.extend(chunks)
            
            # Deduplicate
            unique_chunks = []
            seen_content = set()
            for chunk in all_chunks:
                content_hash = hash(chunk['content'][:100])
                if content_hash not in seen_content:
                    unique_chunks.append(chunk)
                    seen_content.add(content_hash)
            
            logger.info(f"✅ Retrieved {len(unique_chunks)} unique chunks")
            return unique_chunks
            
        except Exception as e:
            logger.error(f"❌ Error getting chunks: {e}")
            return []

    async def _generate_comprehensive_curriculum_questions(self, curriculum_name: str, chunks: List[Dict[str, Any]], topics: List[str], exam_parameters: Dict[str, Any]) -> List[Question]:
        """Generate comprehensive questions from curriculum content"""
        try:
            combined_content = "\n\n".join([chunk['content'] for chunk in chunks])
            topics_str = ", ".join(topics[:8])
            
            questions = await self._generate_questions_from_content(
                content=combined_content,
                topic=f"{curriculum_name} curriculum covering: {topics_str}",
                exam_parameters=exam_parameters
            )
            
            return questions
            
        except Exception as e:
            logger.error(f"❌ Error generating questions: {e}")
            return []

    # ==================== CASE 2: BOOK EXAM ====================
    
    async def _generate_questions_with_book_agent(self, book_title: str, curriculum_name: str, exam_parameters: Dict[str, Any]) -> List[Question]:
        """CASE 2: Book-specific question generation with TOC parsing"""
        try:
            logger.info(f"📚 CASE 2 START: Book generation for '{book_title}'")
            
            # STEP 1: Extract topics from book TOC
            logger.info(f"🔍 STEP 1: Extracting topics from book TOC")
            topics = await self._extract_book_topics(curriculum_name, book_title)
            
            if not topics:
                logger.warning(f"⚠️ No topics from TOC, using content fallback")
                topics = await self._extract_keywords_from_random_chunks(curriculum_name)
            
            logger.info(f"✅ STEP 1 DONE: Found {len(topics)} book topics")
            
            # STEP 2: Search book for topic content
            logger.info(f"🔍 STEP 2: Searching book for topic content")
            chunks = await self._search_book_for_topics(book_title, curriculum_name, topics)
            
            if not chunks:
                logger.error(f"❌ STEP 2 FAILED: No chunks found")
                return self._generate_default_questions(exam_parameters, topics)
            
            logger.info(f"✅ STEP 2 DONE: Retrieved {len(chunks)} chunks")
            
            # STEP 3: Generate questions
            logger.info(f"📝 STEP 3: Generating questions")
            combined_content = "\n\n".join([chunk.get('content', '') for chunk in chunks])
            
            questions = await self._generate_questions_from_content(
                content=combined_content,
                topic=f"book {book_title}",
                exam_parameters=exam_parameters
            )
            
            if questions and len(questions) >= exam_parameters['count']:
                logger.info(f"✅ SUCCESS: Generated {len(questions)} questions")
                return questions[:exam_parameters['count']]
            else:
                return self._generate_default_questions(exam_parameters, topics)
                
        except Exception as e:
            logger.error(f"❌ CASE 2 ERROR: {e}")
            import traceback
            logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
            return self._generate_default_questions(exam_parameters, [book_title])

    async def _extract_book_topics(self, curriculum_name: str, book_title: str) -> List[str]:
        """Extract topics from book TOC using multiple methods"""
        try:
            logger.info(f"📖 Extracting topics from TOC for '{book_title}'")
            
            book_info = await self._get_book_curriculum_info(book_title)
            if not book_info:
                return []
            
            book_id = book_info['id']
            
            # Search for TOC content
            toc_chunks = await self._search_for_toc_content(book_title, curriculum_name, book_id)
            
            # Get beginning chunks
            beginning_chunks = await self._get_beginning_chunks(book_title, curriculum_name, book_id)
            
            all_toc_chunks = toc_chunks + beginning_chunks
            
            if not all_toc_chunks:
                return []
            
            # Parse topics
            topics = await self._parse_toc_topics(all_toc_chunks, book_title, curriculum_name)
            
            logger.info(f"✅ Extracted {len(topics)} topics from TOC")
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting book topics: {e}")
            return []

    async def _search_for_toc_content(self, book_title: str, curriculum_name: str, book_id: int) -> List[Dict[str, Any]]:
        """Search for table of contents using multiple queries"""
        toc_queries = [
            "table of contents",
            "contents",
            "chapter",
            "section",
            "overview"
        ]
        
        toc_chunks = []
        for query in toc_queries:
            try:
                chunks = await self._search_book_embeddings(book_title, curriculum_name, query, k=2)
                if chunks:
                    toc_chunks.extend(chunks)
            except:
                continue
        
        # Deduplicate
        unique_chunks = []
        seen_content = set()
        for chunk in toc_chunks:
            if isinstance(chunk, dict) and 'content' in chunk:
                content_hash = hash(chunk['content'][:100])
                if content_hash not in seen_content:
                    unique_chunks.append(chunk)
                    seen_content.add(content_hash)
        
        return unique_chunks

    async def _get_beginning_chunks(self, book_title: str, curriculum_name: str, book_id: int, chunk_count: int = 8) -> List[Dict[str, Any]]:
        """Get first chunks of book where TOC typically appears"""
        try:
            async with self.get_db_connection() as conn:
                table_name = f"curriculum_embeddings_{curriculum_name.lower().replace(' ', '_')}"
                
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
                
                return chunks
                
        except Exception as e:
            logger.error(f"❌ Error getting beginning chunks: {e}")
            return []

    async def _parse_toc_topics(self, toc_chunks: List[Dict[str, Any]], book_title: str, curriculum_name: str) -> List[str]:
        """Parse TOC content to extract keywords using LLM"""
        try:
            toc_content = "\n\n".join([chunk.get('content', '') for chunk in toc_chunks if chunk.get('content')])
            
            if not toc_content.strip():
                return []
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", """Extract searchable keywords and terms from this Table of Contents.
Focus on: chapter topics, technical terms, methods, tools, concepts.
Return ONLY a JSON array: ["keyword1", "keyword2", ...]
Maximum 12 keywords."""),
                ("human", "TOC Content:\n\n{content}\n\nExtract keywords:")
            ])
            
            chain = prompt | self.get_current_llm() | StrOutputParser()
            response = await chain.ainvoke({"content": toc_content[:4000]})
            
            keywords = self._parse_topics_from_llm_response(response)
            return keywords
            
        except Exception as e:
            logger.error(f"❌ Error parsing TOC: {e}")
            return []

    async def _search_book_for_topics(self, book_title: str, curriculum_name: str, topics: List[str]) -> List[Dict[str, Any]]:
        """Search book for content related to extracted topics"""
        try:
            all_chunks = []
            
            for topic in topics[:10]:
                chunks = await self._search_book_embeddings(book_title, curriculum_name, topic, k=2)
                if chunks:
                    all_chunks.extend(chunks)
            
            # Deduplicate
            unique_chunks = []
            seen_content = set()
            for chunk in all_chunks:
                content_hash = hash(chunk.get('content', '')[:100])
                if content_hash not in seen_content:
                    unique_chunks.append(chunk)
                    seen_content.add(content_hash)
            
            return unique_chunks[:15]
            
        except Exception as e:
            logger.error(f"❌ Error searching book: {e}")
            return []

    async def _search_book_embeddings(self, book_title: str, curriculum_name: str, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """Search book-specific embeddings using vector similarity"""
        try:
            # Get book info
            book_info = await self._get_book_curriculum_info(book_title)
            if not book_info:
                return []
            
            book_id = book_info['id']
            
            # Generate embedding for the query using Ollama
            query_embedding = await self.embeddings.aembed_query(query)
            
            # Search in book-specific embeddings
            results = await self.db.search_book_specific_embeddings(curriculum_name, book_id, query_embedding, k)
            
            logger.info(f"✅ Retrieved {len(results)} chunks from book '{book_title}'")
            return results
            
        except Exception as e:
            logger.error(f"❌ Error searching book embeddings: {e}")
            return []

    # ==================== CASE 3: TOPIC EXAM ====================
    
    async def _generate_questions_with_topic_agent(self, book_title: str, curriculum_name: str, specific_topics: str, exam_parameters: Dict[str, Any]) -> List[Question]:
        """CASE 3: Topic-specific question generation"""
        try:
            logger.info(f"🎯 CASE 3 START: Topic generation for '{specific_topics}'")
            
            # STEP 1: Analyze and expand topics
            logger.info(f"🔍 STEP 1: Analyzing and expanding topics")
            expanded_topics = await self._analyze_and_expand_topics(specific_topics)
            
            logger.info(f"✅ STEP 1 DONE: Expanded to {len(expanded_topics)} search terms")
            
            # STEP 2: Enhanced search
            logger.info(f"🔍 STEP 2: Enhanced search for topic content")
            chunks = await self._search_for_specific_topics_enhanced(curriculum_name, expanded_topics)
            
            if not chunks:
                logger.error(f"❌ STEP 2 FAILED: No chunks found")
                return self._generate_default_questions(exam_parameters, [specific_topics])
            
            logger.info(f"✅ STEP 2 DONE: Retrieved {len(chunks)} chunks")
            
            # STEP 3: Generate questions
            logger.info(f"📝 STEP 3: Generating topic-focused questions")
            combined_content = "\n\n".join([chunk.get('content', '') for chunk in chunks])
            
            questions = await self._generate_questions_from_content(
                content=combined_content,
                topic=specific_topics,
                exam_parameters=exam_parameters
            )
            
            if questions and len(questions) >= exam_parameters['count']:
                logger.info(f"✅ SUCCESS: Generated {len(questions)} questions")
                return questions[:exam_parameters['count']]
            else:
                return self._generate_default_questions(exam_parameters, [specific_topics])
                
        except Exception as e:
            logger.error(f"❌ CASE 3 ERROR: {e}")
            import traceback
            logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
            return self._generate_default_questions(exam_parameters, [specific_topics])

    async def _analyze_and_expand_topics(self, specific_topics: str) -> List[str]:
        """Analyze and expand user-provided topics using LLM"""
        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", """Expand this topic into 5-8 related search terms.
Return ONLY a JSON array: ["term1", "term2", ...]"""),
                ("human", "Topic: {topic}\n\nExpand to search terms:")
            ])
            
            chain = prompt | self.get_current_llm() | StrOutputParser()
            response = await chain.ainvoke({"topic": specific_topics})
            
            expanded = self._parse_topics_from_llm_response(response)
            
            # Always include original topic
            if specific_topics not in expanded:
                expanded.insert(0, specific_topics)
            
            return expanded[:8]
            
        except Exception as e:
            logger.error(f"❌ Error expanding topics: {e}")
            return [specific_topics]

    async def _search_for_specific_topics_enhanced(self, curriculum_name: str, topics: List[str]) -> List[Dict[str, Any]]:
        """Enhanced search for specific topics"""
        try:
            all_chunks = []
            
            for topic in topics:
                chunks = await self._search_curriculum_embeddings(curriculum_name, topic, k=2)
                if chunks:
                    all_chunks.extend(chunks)
            
            # Deduplicate
            unique_chunks = []
            seen_content = set()
            for chunk in all_chunks:
                content_hash = hash(chunk.get('content', '')[:100])
                if content_hash not in seen_content:
                    unique_chunks.append(chunk)
                    seen_content.add(content_hash)
            
            return unique_chunks[:10]
            
        except Exception as e:
            logger.error(f"❌ Error in enhanced search: {e}")
            return []

    # ==================== CORE GENERATION METHODS ====================
    
    async def _generate_questions_from_content(self, content: str, topic: str, exam_parameters: Dict[str, Any]) -> List[Question]:
        """Core method: Generate questions from content with sophisticated prompt"""
        try:
            logger.info(f"📝 GENERATING: {exam_parameters['count']} questions from {len(content)} chars")
            
            if not content or len(content.strip()) < 50:
                logger.error(f"❌ Content too short")
                return []
            
            difficulty = exam_parameters.get('difficulty', ['medium'])[0]
            question_type = exam_parameters.get('question_types', ['multiple_choice_single_answer'])[0]
            count = exam_parameters.get('count', 10)
            
            # Sophisticated prompt
            question_prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are a professional exam creator. Generate EXACTLY {count} technical exam questions.

STRICTLY FORBIDDEN PHRASES - DO NOT USE:
❌ "According to the content"
❌ "According to the text" 
❌ "As described in Chapter X"
❌ "What does Chapter X cover"
❌ "The book states"
❌ "Based on the provided content"

REQUIRED QUESTION STYLE:
✅ Write direct technical questions
✅ Professional certification exam style
✅ No source material references

JSON FORMAT:
Return a JSON array with {count} objects:
- "difficulty": "{difficulty}"
- "type": "{question_type}"
- "question_text": "Direct technical question"
- "options": ["A", "B", "C", "D"] (for multiple choice)
- "answer": "Correct answer"

Generate EXACTLY {count} questions."""),
                ("human", "Content:\n\n{content}\n\nGenerate {count} {difficulty} questions.")
            ])
            
            chain = question_prompt | self.get_current_llm() | StrOutputParser()
            
            result = await chain.ainvoke({
                "topic": topic,
                "content": content[:8000],
                "count": count,
                "difficulty": difficulty,
                "question_type": question_type
            })
            
            logger.info(f"🔍 LLM Response: {len(result)} chars")
            
            # Parse JSON
            cleaned_result = result.strip()
            
            if cleaned_result.startswith('```json'):
                cleaned_result = cleaned_result.replace('```json\n', '').replace('```json', '').replace('\n```', '').replace('```', '')
            elif cleaned_result.startswith('```'):
                cleaned_result = cleaned_result.replace('```\n', '').replace('```', '')
            
            if '```' in cleaned_result:
                cleaned_result = cleaned_result.split('```')[0]
            
            start_idx = cleaned_result.find('[')
            end_idx = cleaned_result.rfind(']')
            
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                cleaned_result = cleaned_result[start_idx:end_idx+1]
            
            questions_data = json.loads(cleaned_result)
            
            if not isinstance(questions_data, list):
                logger.error("❌ Response is not a JSON array")
                return []
            
            # Convert to Question objects
            questions = []
            for i, q_data in enumerate(questions_data):
                if not isinstance(q_data, dict):
                    continue
                
                if not q_data.get('question_text'):
                    continue
                
                # Clean question text
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
                logger.info(f"✅ Question {i+1}: {question.question_text[:60]}...")
            
            logger.info(f"🎉 SUCCESS: Generated {len(questions)} questions")
            return questions[:count]
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON parsing error: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Error generating questions: {e}")
            import traceback
            logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
            return []

    def _remove_book_references(self, question_text: str) -> str:
        """Remove book references and meta-phrases from questions"""
        try:
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
            ]
            
            cleaned_text = question_text
            
            for pattern in patterns_to_remove:
                cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE)
            
            # Cleanup
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
            cleaned_text = re.sub(r'^[,\s]+|[,\s]+$', '', cleaned_text)
            cleaned_text = re.sub(r'\?+$', '?', cleaned_text)
            
            # Capitalize
            if cleaned_text and not cleaned_text[0].isupper():
                cleaned_text = cleaned_text[0].upper() + cleaned_text[1:]
            
            if cleaned_text != question_text:
                logger.info(f"📝 Cleaned: '{question_text[:40]}...' → '{cleaned_text[:40]}...'")
            
            return cleaned_text.strip()
            
        except Exception as e:
            logger.error(f"❌ Error cleaning question: {e}")
            return question_text

    # ==================== HELPER METHODS ====================
    
    async def _search_curriculum_embeddings(self, curriculum_name: str, query: str, k: int = 6) -> List[Dict[str, Any]]:
        """Search curriculum embeddings using vector similarity"""
        try:
            # Generate embedding for the query using Ollama
            query_embedding = await self.embeddings.aembed_query(query)
            
            # Search in curriculum embedding table
            results = await self.db.search_curriculum_embeddings(curriculum_name, query_embedding, limit=k)
            
            logger.info(f"✅ Retrieved {len(results)} chunks from curriculum '{curriculum_name}'")
            return results
            
        except Exception as e:
            logger.error(f"❌ Error searching curriculum embeddings: {e}")
            return []

    async def _get_random_curriculum_chunks(self, curriculum_name: str, count: int = 10) -> List[Dict[str, Any]]:
        """Get random chunks from curriculum"""
        try:
            async with self.get_db_connection() as conn:
                table_name = f"curriculum_embeddings_{curriculum_name.lower().replace(' ', '_')}"
                
                query = f"""
                SELECT content, metadata 
                FROM {table_name} 
                ORDER BY RANDOM() 
                LIMIT $1
                """
                
                results = await conn.fetch(query, count)
                
                return [{'content': row['content'], 'metadata': row['metadata'] or {}} for row in results]
                
        except Exception as e:
            logger.error(f"❌ Error getting random chunks: {e}")
            return []

    async def _get_book_curriculum_info(self, book_title: str) -> Optional[Dict[str, Any]]:
        """Get book information"""
        try:
            return await self.db.get_book_by_title(book_title)
        except Exception as e:
            logger.error(f"❌ Error getting book info: {e}")
            return None

    def _parse_topics_from_llm_response(self, response: str) -> List[str]:
        """Parse topics from LLM JSON response"""
        try:
            cleaned = response.strip()
            
            if cleaned.startswith('```json'):
                cleaned = cleaned.replace('```json\n', '').replace('```json', '').replace('\n```', '').replace('```', '')
            elif cleaned.startswith('```'):
                cleaned = cleaned.replace('```\n', '').replace('```', '')
            
            start_idx = cleaned.find('[')
            end_idx = cleaned.rfind(']')
            
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = cleaned[start_idx:end_idx+1]
                topics = json.loads(json_str)
                
                clean_topics = []
                for topic in topics:
                    if isinstance(topic, str) and len(topic.strip()) > 2:
                        clean_topic = topic.strip()
                        if len(clean_topic) <= 100:
                            clean_topics.append(clean_topic)
                
                return clean_topics
            
            return []
            
        except Exception as e:
            logger.error(f"❌ Error parsing topics: {e}")
            return []

    def _generate_default_questions(self, exam_parameters: Dict[str, Any], topics: List[str]) -> List[Question]:
        """Generate default fallback questions"""
        try:
            questions = []
            count = exam_parameters.get('count', 5)
            difficulty = exam_parameters.get('difficulty', ['medium'])[0]
            
            for i in range(min(count, len(topics) * 2)):
                topic = topics[i % len(topics)] if topics else "General Topic"
                question = Question(
                    difficulty=difficulty,
                    type="multiple_choice_single_answer",
                    question_text=f"What is a key concept related to {topic}?",
                    options=[
                        f"Primary aspect of {topic}",
                        f"Secondary feature of {topic}",
                        f"Alternative approach to {topic}",
                        f"Unrelated concept"
                    ],
                    answer=f"Primary aspect of {topic}"
                )
                questions.append(question)
            
            return questions[:count]
            
        except Exception as e:
            logger.error(f"❌ Error generating default questions: {e}")
            return []
