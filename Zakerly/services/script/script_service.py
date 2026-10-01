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

from models import LectureScriptRequest, LectureScriptUpdate
from database import DatabaseManager
from utils import RedisManager

logger = logging.getLogger(__name__)

class ScriptService:
    def __init__(self, db_manager: DatabaseManager, redis_manager: RedisManager):
        self.db = db_manager
        self.redis = redis_manager
        
        # Initialize embeddings
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
                max_tokens=8192,
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
        logger.info(f"✅ ScriptService initialized with {gemini_model}")

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
    
    async def generate_curriculum_script(self, request: dict) -> str:
        """Main entry point - Generate script using sophisticated 3-case system"""
        try:
            logger.info(f"🎯 SCRIPT SERVICE: Script generation started")
            logger.info(f"Request: curriculum_id={request.get('curriculum_id')}, scope={request.get('scope')}")
            
            scope = request.get('scope', 'whole_curriculum')
            
            # CASE 1: Whole Curriculum Script
            if scope == 'whole_curriculum':
                logger.info("🌟 CASE 1: Generating script for WHOLE CURRICULUM")
                return await self._generate_curriculum_script(request)
            
            # CASE 2: Single Book Script
            elif scope == 'whole_book':
                logger.info("📚 CASE 2: Generating script for WHOLE BOOK")
                return await self._generate_book_script(request)
            
            # CASE 3: Specific Topics Script
            elif scope == 'specific_topics':
                logger.info("🎯 CASE 3: Generating script for SPECIFIC TOPICS")
                return await self._generate_topic_script(request)
            
            else:
                raise ValueError(f"Invalid scope: {scope}")
                
        except Exception as e:
            logger.error(f"❌ Error generating curriculum script: {e}")
            raise e

    # ==================== CASE 1: CURRICULUM SCRIPT ====================
    
    async def _generate_curriculum_script(self, request: dict) -> str:
        """CASE 1: Comprehensive curriculum-wide script generation"""
        try:
            curriculum_id = request['curriculum_id']
            title = request.get('title', 'Comprehensive Curriculum Overview')
            detail_level = request.get('detail_level', 'overview')
            
            logger.info(f"🌟 CASE 1 START: Curriculum script for ID {curriculum_id}")
            logger.info(f"📖 STEP 1: Extracting curriculum-wide topics")
            
            # Step 1: Extract curriculum-wide topics using 4-method approach
            curriculum_topics = await self._extract_curriculum_wide_topics(curriculum_id)
            
            if not curriculum_topics:
                logger.warning("⚠️ No topics extracted, using fallback")
                curriculum_topics = ["General curriculum overview", "Core concepts", "Key principles"]
            
            logger.info(f"✅ STEP 1 DONE: Found {len(curriculum_topics)} curriculum topics")
            
            # Step 2: Get books in curriculum
            logger.info(f"📚 STEP 2: Getting curriculum books")
            curriculum_books = await self._get_curriculum_books(curriculum_id)
            book_titles = [book['title'] for book in curriculum_books]
            
            logger.info(f"✅ STEP 2 DONE: Found {len(curriculum_books)} books")
            
            # Step 3: Search for comprehensive curriculum content
            logger.info(f"🔍 STEP 3: Searching for comprehensive content")
            curriculum_info = await self.db.get_curriculum_by_id(int(curriculum_id))
            curriculum_name = curriculum_info['name'] if curriculum_info else "Unknown Curriculum"
            
            # Get overview chunks
            overview_chunks = await self._search_curriculum_embeddings(
                curriculum_name, 
                f"curriculum overview introduction objectives {title}", 
                k=8
            )
            
            content_preview = "\n\n".join([chunk.get('content', '')[:500] for chunk in overview_chunks[:3]])
            
            logger.info(f"✅ STEP 3 DONE: Retrieved {len(overview_chunks)} overview chunks")
            
            # Step 4: Generate comprehensive script
            logger.info(f"✍️ STEP 4: Generating comprehensive curriculum script")
            
            script_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are Professor A.I., an elite educational content creator specializing in transforming academic material into sophisticated, engaging lecture scripts. Your expertise lies in creating professional-grade educational content that rivals the best university lectures.

**Your Mission:** Transform curriculum knowledge into a polished, comprehensive lecture script that demonstrates mastery of pedagogical principles and subject matter expertise.

**CRITICAL REQUIREMENTS:**
- Create a sophisticated lecture script with academic rigor
- Base your script on the provided curriculum information
- Your final response must ONLY contain the formatted lecture script
- DO NOT include any meta-commentary or references like "According to...", "The book mentions...", etc.
- Focus solely on delivering a clean, professional lecture script
- Structure the content to show connections between different subject areas
- Include strategic insights that span multiple topics

**Lecture Script Structure (Professional Format):**

```
# LECTURE SCRIPT: [Title]

**Curriculum:** [Curriculum Name] | **Duration:** [Estimated time] | **Level:** [Detail Level]

## LECTURE OVERVIEW
- **Learning Objectives:** What students will achieve
- **Curriculum Scope:** Comprehensive coverage across all components
- **Key Competency Areas:** Major domains of knowledge

## I. CURRICULUM INTRODUCTION
[Comprehensive introduction covering the full curriculum scope]

## II. INTEGRATED LEARNING FRAMEWORK
[How all curriculum components work together]

## III. CORE COMPETENCY AREAS
[Major topic clusters with cross-references between books]

### 3.1 [Competency Area 1]
[Detailed coverage]

### 3.2 [Competency Area 2]
[Detailed coverage]

[Continue for all major areas]

## IV. STRATEGIC INSIGHTS
[High-level connections and applications across the curriculum]

## V. IMPLEMENTATION ROADMAP
[How to approach this comprehensive curriculum systematically]

## VI. SYNTHESIS & CONCLUSION
- **Key Takeaways:** Essential concepts across the curriculum
- **Interconnections:** How topics relate and build upon each other
- **Next Steps:** Future learning pathways
```

**Quality Standards:**
- Executive perspective that ties all components together
- Clear progression of ideas across the curriculum
- Professional academic tone throughout
- No references to source materials
- No meta-commentary
- Pure instructional content"""),
                ("human", """Create a sophisticated lecture script with these specifications:

**Title:** {title}
**Curriculum:** {curriculum_name}
**Scope:** Whole Curriculum ({book_count} books)
**Detail Level:** {detail_level}

**Books Covered:**
{book_list}

**Key Topics to Address:**
{topic_list}

**Curriculum Content Preview:**
{content_preview}

Please generate a complete, professional lecture script following the specified format and quality standards. Focus on providing a comprehensive overview that integrates all curriculum components.""")
            ])
            
            chain = script_prompt | self.get_current_llm() | StrOutputParser()
            
            script_content = await chain.ainvoke({
                "title": title,
                "curriculum_name": curriculum_name,
                "book_count": len(curriculum_books),
                "detail_level": detail_level,
                "book_list": "\n".join(f"- {book_title}" for book_title in book_titles),
                "topic_list": "\n".join(f"- {topic}" for topic in curriculum_topics[:20]),
                "content_preview": content_preview
            })
            
            logger.info(f"✅ CASE 1 COMPLETE: Generated {len(script_content)} character script")
            
            return script_content
            
        except Exception as e:
            logger.error(f"❌ Error generating curriculum script: {e}")
            raise e

    async def _extract_curriculum_wide_topics(self, curriculum_id: int) -> List[str]:
        """Extract topics from entire curriculum using 4-method approach (similar to exam service)"""
        try:
            logger.info("🔍 Extracting curriculum-wide topics using 4-method approach")
            
            all_topics = []
            
            # METHOD 1: Extract topics from all books' TOCs
            logger.info("📚 METHOD 1: Extracting topics from all books' TOCs")
            toc_topics = await self._extract_topics_from_all_books_toc(curriculum_id)
            all_topics.extend(toc_topics)
            logger.info(f"  → Found {len(toc_topics)} topics from TOCs")
            
            # METHOD 2: Extract from curriculum overview/description
            logger.info("📝 METHOD 2: Extracting topics from curriculum overview")
            overview_topics = await self._extract_topics_from_curriculum_overview(curriculum_id)
            all_topics.extend(overview_topics)
            logger.info(f"  → Found {len(overview_topics)} topics from overview")
            
            # METHOD 3: Extract from curriculum content analysis
            logger.info("🔬 METHOD 3: Analyzing curriculum content")
            content_topics = await self._extract_topics_from_curriculum_content(curriculum_id)
            all_topics.extend(content_topics)
            logger.info(f"  → Found {len(content_topics)} topics from content")
            
            # METHOD 4: LLM-based keyword extraction from random chunks
            logger.info("🎲 METHOD 4: Random chunk analysis")
            random_topics = await self._extract_keywords_from_random_chunks(curriculum_id)
            all_topics.extend(random_topics)
            logger.info(f"  → Found {len(random_topics)} keywords from random chunks")
            
            # Deduplicate and rank
            unique_topics = await self._deduplicate_and_rank_curriculum_topics(all_topics)
            
            logger.info(f"✅ Total unique topics extracted: {len(unique_topics)}")
            return unique_topics[:30]  # Limit to top 30 topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting curriculum topics: {e}")
            return []

    async def _extract_topics_from_all_books_toc(self, curriculum_id: int) -> List[str]:
        """METHOD 1: Extract topics from all books' table of contents"""
        try:
            books = await self._get_curriculum_books(curriculum_id)
            all_toc_topics = []
            
            for book in books[:10]:  # Limit to first 10 books
                book_topics = await self._extract_topics_from_book_toc(book['title'])
                all_toc_topics.extend(book_topics)
            
            return all_toc_topics
            
        except Exception as e:
            logger.error(f"❌ Error in METHOD 1: {e}")
            return []

    async def _extract_topics_from_curriculum_overview(self, curriculum_id: int) -> List[str]:
        """METHOD 2: Extract topics from curriculum overview/syllabus"""
        try:
            curriculum_info = await self.db.get_curriculum_by_id(int(curriculum_id))
            if not curriculum_info:
                return []
            
            curriculum_name = curriculum_info['name']
            description = curriculum_info.get('description', '')
            
            # Search for curriculum overview
            overview_chunks = await self._search_curriculum_embeddings(
                curriculum_name,
                "curriculum overview syllabus objectives main topics",
                k=5
            )
            
            overview_content = description + "\n\n"
            overview_content += "\n\n".join([chunk.get('content', '') for chunk in overview_chunks])
            
            if not overview_content.strip():
                return []
            
            # Use LLM to extract topics
            topics = await self._extract_topics_using_llm(overview_content, "curriculum overview")
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error in METHOD 2: {e}")
            return []

    async def _extract_topics_from_curriculum_content(self, curriculum_id: int) -> List[str]:
        """METHOD 3: Extract topics from general curriculum content"""
        try:
            curriculum_info = await self.db.get_curriculum_by_id(int(curriculum_id))
            if not curriculum_info:
                return []
            
            curriculum_name = curriculum_info['name']
            
            # Search for general content topics
            search_queries = [
                "main concepts key topics",
                "fundamental principles theories",
                "core subjects areas"
            ]
            
            all_chunks = []
            for query in search_queries:
                chunks = await self._search_curriculum_embeddings(curriculum_name, query, k=3)
                all_chunks.extend(chunks)
            
            if not all_chunks:
                return []
            
            content_text = "\n\n".join([chunk.get('content', '')[:1000] for chunk in all_chunks[:5]])
            
            topics = await self._extract_topics_using_llm(content_text, "curriculum content")
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error in METHOD 3: {e}")
            return []

    async def _extract_keywords_from_random_chunks(self, curriculum_id: int) -> List[str]:
        """METHOD 4: Extract keywords from random chunks"""
        try:
            curriculum_info = await self.db.get_curriculum_by_id(int(curriculum_id))
            if not curriculum_info:
                return []
            
            curriculum_name = curriculum_info['name']
            
            # Get random chunks
            random_chunks = await self._get_random_curriculum_chunks(curriculum_name, count=10)
            
            if not random_chunks:
                return []
            
            sample_content = "\n\n".join([chunk.get('content', '')[:800] for chunk in random_chunks[:5]])
            
            keywords = await self._extract_topics_using_llm(sample_content, "random curriculum sampling")
            return keywords
            
        except Exception as e:
            logger.error(f"❌ Error in METHOD 4: {e}")
            return []

    async def _extract_topics_using_llm(self, content: str, source: str) -> List[str]:
        """Use LLM to extract topics/keywords from content"""
        try:
            if not content.strip():
                return []
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", """Extract key topics, concepts, and themes from the provided educational content.
Focus on: main subjects, technical terms, theoretical concepts, methodologies, and core themes.
Return ONLY a JSON array: ["topic1", "topic2", ...]
Maximum 15 topics. Be specific and relevant."""),
                ("human", "Content from {source}:\n\n{content}\n\nExtract topics:")
            ])
            
            chain = prompt | self.get_current_llm() | StrOutputParser()
            response = await chain.ainvoke({"content": content[:3000], "source": source})
            
            topics = self._parse_topics_from_llm_response(response)
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting topics with LLM: {e}")
            return []

    def _parse_topics_from_llm_response(self, response: str) -> List[str]:
        """Parse topics from LLM JSON response"""
        try:
            # Try to find JSON array in response
            import re
            json_match = re.search(r'\[.*?\]', response, re.DOTALL)
            if json_match:
                topics_array = json.loads(json_match.group(0))
                if isinstance(topics_array, list):
                    return [str(topic).strip() for topic in topics_array if topic]
            
            # Fallback: split by newlines or commas
            topics = []
            for line in response.split('\n'):
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('```'):
                    # Remove bullet points, numbers, etc.
                    cleaned = re.sub(r'^[\d\.\-\*\•]+\s*', '', line)
                    if cleaned and len(cleaned) > 3:
                        topics.append(cleaned)
            
            return topics[:15]
            
        except Exception as e:
            logger.error(f"❌ Error parsing topics: {e}")
            return []

    async def _deduplicate_and_rank_curriculum_topics(self, topics: List[str]) -> List[str]:
        """Deduplicate and rank topics by frequency"""
        try:
            from collections import Counter
            
            # Clean and normalize topics
            cleaned_topics = []
            for topic in topics:
                cleaned = topic.strip().lower()
                if cleaned and len(cleaned) > 3:
                    cleaned_topics.append(cleaned)
            
            # Count frequencies
            topic_counts = Counter(cleaned_topics)
            
            # Sort by frequency (descending)
            ranked_topics = [topic for topic, count in topic_counts.most_common(50)]
            
            # Return with original casing (first occurrence)
            unique_topics = []
            seen = set()
            for topic in topics:
                topic_lower = topic.strip().lower()
                if topic_lower in ranked_topics and topic_lower not in seen:
                    unique_topics.append(topic.strip())
                    seen.add(topic_lower)
            
            return unique_topics
            
        except Exception as e:
            logger.error(f"❌ Error deduplicating topics: {e}")
            return list(set(topics))[:30]

    # ==================== CASE 2: BOOK SCRIPT ====================
    
    async def _generate_book_script(self, request: dict) -> str:
        """CASE 2: Book-specific script generation with TOC parsing"""
        try:
            curriculum_id = request['curriculum_id']
            book_ids = request.get('specific_books', [])
            title = request.get('title', 'Comprehensive Book Analysis')
            detail_level = request.get('detail_level', 'detailed')
            
            if not book_ids:
                raise ValueError("No books specified for book script generation")
            
            logger.info(f"📚 CASE 2 START: Book script for book IDs {book_ids}")
            
            # Step 1: Get book details
            logger.info(f"📖 STEP 1: Getting book details")
            book_details = []
            for book_id in book_ids:
                book_info = await self._get_book_info(book_id)
                if book_info:
                    book_details.append(book_info)
            
            if not book_details:
                raise ValueError("No valid books found")
            
            book_titles = [book['title'] for book in book_details]
            logger.info(f"✅ STEP 1 DONE: Found {len(book_details)} books")
            
            # Step 2: Extract topics from all book TOCs
            logger.info(f"🔍 STEP 2: Extracting topics from book TOCs")
            all_topics = []
            for book in book_details:
                toc_topics = await self._extract_topics_from_book_toc(book['title'])
                all_topics.extend(toc_topics)
            
            # Remove duplicates
            unique_topics = list(set(all_topics))
            logger.info(f"✅ STEP 2 DONE: Extracted {len(unique_topics)} unique topics")
            
            # Step 3: Search for comprehensive book content
            logger.info(f"📚 STEP 3: Searching for book content")
            
            curriculum_info = await self.db.get_curriculum_by_id(int(curriculum_id))
            curriculum_name = curriculum_info['name'] if curriculum_info else "Unknown Curriculum"
            
            # Get content chunks for the books
            all_content_chunks = []
            for book in book_details:
                chunks = await self._search_book_content(
                    book['title'],
                    curriculum_name,
                    f"{title} overview main concepts",
                    k=5
                )
                all_content_chunks.extend(chunks)
            
            content_preview = "\n\n".join([chunk.get('content', '')[:600] for chunk in all_content_chunks[:4]])
            
            logger.info(f"✅ STEP 3 DONE: Retrieved {len(all_content_chunks)} content chunks")
            
            # Step 4: Generate comprehensive book script
            logger.info(f"✍️ STEP 4: Generating comprehensive book script")
            
            script_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are Professor A.I., an elite educational content creator specializing in transforming academic material into sophisticated, engaging lecture scripts.

**Your Mission:** Create a polished, comprehensive lecture script for specific book(s) that demonstrates deep understanding and pedagogical expertise.

**CRITICAL REQUIREMENTS:**
- Provide deep, focused coverage of the book content
- Organize by major themes and chapters
- Include specific examples and detailed explanations
- DO NOT include any meta-commentary or references like "According to...", "The book states...", etc.
- Focus solely on delivering clean, professional instructional content
- Create practical learning applications

**Lecture Script Structure:**

```
# LECTURE SCRIPT: [Title]

**Book(s):** [Book titles] | **Duration:** [Estimated time] | **Level:** [Detail Level]

## LECTURE OVERVIEW
- **Learning Objectives:** What students will master
- **Book Scope:** Coverage and focus areas
- **Key Themes:** Major concepts covered

## I. BOOK INTRODUCTION
[Introduction to the book's scope and objectives]

## II. FOUNDATIONAL CONCEPTS
[Core principles, theories, and fundamental knowledge]

## III. DETAILED ANALYSIS
[Comprehensive coverage organized by themes or chapters]

### 3.1 [Major Theme 1]
[Detailed coverage with examples]

### 3.2 [Major Theme 2]
[Detailed coverage with examples]

[Continue for all major themes]

## IV. PRACTICAL APPLICATIONS
[Real-world examples, case studies, and applications]

## V. CRITICAL INSIGHTS
[Key takeaways, important concepts, and deeper understanding]

## VI. SYNTHESIS & CONCLUSIONS
- **Summary:** Integration of all concepts
- **Key Points:** Essential knowledge
- **Next Steps:** Future learning directions
```

**Quality Standards:**
- Deep, focused coverage of book content
- Clear thematic organization
- Professional academic tone
- No references to source materials
- Pure instructional content"""),
                ("human", """Create a sophisticated lecture script for the book(s):

**Title:** {title}
**Book(s):** {book_list}
**Detail Level:** {detail_level}
**Curriculum Context:** {curriculum_name}

**Key Topics from Books:**
{topic_list}

**Book Content Preview:**
{content_preview}

Please generate a complete, professional lecture script that provides comprehensive, detailed coverage demonstrating deep understanding of the book content.""")
            ])
            
            chain = script_prompt | self.get_current_llm() | StrOutputParser()
            
            script_content = await chain.ainvoke({
                "title": title,
                "book_list": ", ".join(book_titles),
                "detail_level": detail_level,
                "curriculum_name": curriculum_name,
                "topic_list": "\n".join(f"- {topic}" for topic in unique_topics[:25]),
                "content_preview": content_preview
            })
            
            logger.info(f"✅ CASE 2 COMPLETE: Generated {len(script_content)} character script")
            
            return script_content
            
        except Exception as e:
            logger.error(f"❌ Error generating book script: {e}")
            raise e

    async def _extract_topics_from_book_toc(self, book_title: str) -> List[str]:
        """Extract topics from a book's table of contents"""
        try:
            logger.info(f"📖 Extracting topics from TOC for '{book_title}'")
            
            # Get book and curriculum info
            book_info = await self._get_book_curriculum_info(book_title)
            if not book_info:
                logger.warning(f"Book '{book_title}' not found")
                return []
            
            curriculum_name = book_info.get('curriculum_name', 'Unknown')
            book_id = book_info.get('id')
            
            # Search for TOC content (similar to exam service)
            toc_chunks = await self._search_for_toc_content(book_title, curriculum_name, book_id)
            
            if not toc_chunks:
                logger.warning(f"⚠️ No TOC found for '{book_title}'")
                return []
            
            # Get beginning chunks as fallback
            beginning_chunks = await self._get_beginning_chunks(book_title, curriculum_name, book_id, chunk_count=5)
            toc_chunks.extend(beginning_chunks)
            
            # Parse TOC using LLM
            topics = await self._parse_toc_topics(toc_chunks, book_title, curriculum_name)
            
            logger.info(f"✅ Extracted {len(topics)} topics from TOC")
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error extracting topics from book TOC: {e}")
            return []

    async def _search_for_toc_content(self, book_title: str, curriculum_name: str, book_id: int) -> List[Dict[str, Any]]:
        """Search for table of contents in book"""
        try:
            toc_queries = [
                "table of contents",
                "contents",
                "chapter",
                "section",
                "overview"
            ]
            
            all_chunks = []
            for query in toc_queries:
                chunks = await self._search_book_embeddings(book_title, curriculum_name, query, k=2)
                if chunks:
                    all_chunks.extend(chunks)
            
            # Deduplicate
            unique_chunks = []
            seen_content = set()
            for chunk in all_chunks:
                if isinstance(chunk, dict) and 'content' in chunk:
                    content_hash = hash(chunk['content'][:100])
                    if content_hash not in seen_content:
                        unique_chunks.append(chunk)
                        seen_content.add(content_hash)
            
            return unique_chunks
            
        except Exception as e:
            logger.error(f"❌ Error searching for TOC: {e}")
            return []

    async def _get_beginning_chunks(self, book_title: str, curriculum_name: str, book_id: int, chunk_count: int = 5) -> List[Dict[str, Any]]:
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
        """Parse TOC content to extract topics using LLM"""
        try:
            toc_content = "\n\n".join([chunk.get('content', '') for chunk in toc_chunks if chunk.get('content')])
            
            if not toc_content.strip():
                return []
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", """Extract topics and themes from this Table of Contents.
Focus on: chapter topics, main subjects, key concepts, themes.
Return ONLY a JSON array: ["topic1", "topic2", ...]
Maximum 15 topics."""),
                ("human", "Book: {book_title}\n\nTOC Content:\n\n{content}\n\nExtract topics:")
            ])
            
            chain = prompt | self.get_current_llm() | StrOutputParser()
            response = await chain.ainvoke({"book_title": book_title, "content": toc_content[:4000]})
            
            topics = self._parse_topics_from_llm_response(response)
            return topics
            
        except Exception as e:
            logger.error(f"❌ Error parsing TOC: {e}")
            return []

    async def _search_book_content(self, book_title: str, curriculum_name: str, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """Search for book content"""
        try:
            return await self._search_book_embeddings(book_title, curriculum_name, query, k)
        except Exception as e:
            logger.error(f"❌ Error searching book content: {e}")
            return []

    # ==================== CASE 3: TOPIC SCRIPT ====================
    
    async def _generate_topic_script(self, request: dict) -> str:
        """CASE 3: Topic-specific script generation"""
        try:
            curriculum_id = request['curriculum_id']
            book_ids = request.get('specific_books', [])
            topics = request.get('specific_topics', '')
            title = request.get('title', 'Focused Topic Analysis')
            detail_level = request.get('detail_level', 'detailed')
            
            if not topics.strip():
                raise ValueError("No specific topics provided")
            
            logger.info(f"🎯 CASE 3 START: Topic script for topics: {topics}")
            
            # Step 1: Parse and clean topics
            logger.info(f"📝 STEP 1: Parsing topics")
            topic_list = [topic.strip() for topic in topics.split(',') if topic.strip()]
            logger.info(f"✅ STEP 1 DONE: Parsed {len(topic_list)} topics")
            
            # Step 2: Get context from specified books or curriculum
            logger.info(f"📚 STEP 2: Getting context books")
            context_books = []
            if book_ids:
                for book_id in book_ids:
                    book_info = await self._get_book_info(book_id)
                    if book_info:
                        context_books.append(book_info['title'])
            else:
                curriculum_books = await self._get_curriculum_books(curriculum_id)
                context_books = [book['title'] for book in curriculum_books[:5]]
            
            logger.info(f"✅ STEP 2 DONE: Found {len(context_books)} context books")
            
            # Step 3: Search for topic-specific content
            logger.info(f"🔍 STEP 3: Searching for topic content")
            
            curriculum_info = await self.db.get_curriculum_by_id(int(curriculum_id))
            curriculum_name = curriculum_info['name'] if curriculum_info else "Unknown Curriculum"
            
            # Search for each topic
            all_content_chunks = []
            for topic in topic_list[:5]:  # Limit to first 5 topics
                chunks = await self._search_curriculum_embeddings(
                    curriculum_name,
                    topic,
                    k=3
                )
                all_content_chunks.extend(chunks)
            
            content_preview = "\n\n".join([chunk.get('content', '')[:600] for chunk in all_content_chunks[:4]])
            
            logger.info(f"✅ STEP 3 DONE: Retrieved {len(all_content_chunks)} content chunks")
            
            # Step 4: Generate topic-focused script
            logger.info(f"✍️ STEP 4: Generating topic-focused script")
            
            script_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are Professor A.I., an elite educational content creator specializing in focused, deep-dive lecture content.

**Your Mission:** Create a comprehensive lecture script focused exclusively on specific topics with depth and expertise.

**CRITICAL REQUIREMENTS:**
- Focus exclusively on the specified topics
- Provide deep, detailed analysis of each topic
- Show connections between related topics
- Include practical examples and applications
- DO NOT include any meta-commentary or references like "According to...", "The material states...", etc.
- Focus solely on delivering clean, professional instructional content

**Lecture Script Structure:**

```
# LECTURE SCRIPT: [Title]

**Topics:** [Topic list] | **Duration:** [Estimated time] | **Level:** [Detail Level]

## LECTURE OVERVIEW
- **Learning Objectives:** Specific goals for these topics
- **Topic Coverage:** Detailed scope
- **Prerequisites:** Background knowledge needed

## I. TOPIC OVERVIEW
[Introduction to the specific topics covered and their importance]

## II. DETAILED TOPIC ANALYSIS

### Topic 1: [Topic Name]
[Comprehensive, detailed coverage]
- Core Concepts
- Key Principles
- Detailed Explanations

### Topic 2: [Topic Name]
[Comprehensive, detailed coverage]
- Core Concepts
- Key Principles
- Detailed Explanations

[Continue for all topics]

## III. INTERCONNECTIONS
[How these topics relate to each other and integrate]

## IV. PRACTICAL APPLICATIONS
[Real-world uses, examples, and case studies]

## V. ADVANCED CONCEPTS
[Deeper insights, complex aspects, and expert perspectives]

## VI. SUMMARY & INTEGRATION
- **Key Takeaways:** Essential concepts from each topic
- **Synthesis:** How topics work together
- **Next Steps:** Future learning directions
```

**Quality Standards:**
- Focused, detailed coverage
- Expert-level depth on each topic
- Professional academic tone
- No references to source materials
- Pure instructional content"""),
                ("human", """Create a sophisticated lecture script focused on specific topics:

**Title:** {title}
**Target Topics:** {topic_list}
**Detail Level:** {detail_level}
**Context Books:** {context_books}
**Curriculum Context:** {curriculum_name}

**Topic Content Preview:**
{content_preview}

Please generate a complete, professional lecture script that provides focused, detailed coverage demonstrating expertise in the specified topics.""")
            ])
            
            chain = script_prompt | self.get_current_llm() | StrOutputParser()
            
            script_content = await chain.ainvoke({
                "title": title,
                "topic_list": ", ".join(topic_list),
                "detail_level": detail_level,
                "context_books": ", ".join(context_books),
                "curriculum_name": curriculum_name,
                "content_preview": content_preview
            })
            
            logger.info(f"✅ CASE 3 COMPLETE: Generated {len(script_content)} character script")
            
            return script_content
            
        except Exception as e:
            logger.error(f"❌ Error generating topic script: {e}")
            raise e

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
                
                chunks = []
                for row in results:
                    chunks.append({
                        'content': row['content'],
                        'metadata': row['metadata'] if row['metadata'] else {}
                    })
                
                return chunks
                
        except Exception as e:
            logger.error(f"❌ Error getting random chunks: {e}")
            return []

    async def _get_book_curriculum_info(self, book_title: str) -> Optional[Dict[str, Any]]:
        """Get book information including curriculum context"""
        try:
            query = """
                SELECT b.id, b.title, b.author, b.curriculum_id, c.name as curriculum_name
                FROM books b
                JOIN curriculum c ON b.curriculum_id = c.id
                WHERE b.title = $1
            """
            
            result = await self.db.execute_query(query, book_title)
            
            if result and len(result) > 0:
                row = result[0]
                return {
                    'id': row['id'],
                    'title': row['title'],
                    'author': row.get('author'),
                    'curriculum_id': row['curriculum_id'],
                    'curriculum_name': row['curriculum_name']
                }
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Error getting book curriculum info: {e}")
            return None

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
            logger.error(f"❌ Error getting book info for ID {book_id}: {e}")
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
            logger.error(f"❌ Error getting curriculum books for ID {curriculum_id}: {e}")
            return []

    # ==================== CRUD OPERATIONS ====================
    
    async def create_lecture_script(self, user_id: str, request: LectureScriptRequest) -> dict:
        """Create a new lecture script"""
        try:
            # ✅ CRITICAL: Validate user exists before creating script
            user_check_query = "SELECT id FROM users WHERE id = $1"
            user_check_result = await self.db.execute_query(user_check_query, user_id)
            
            if not user_check_result or len(user_check_result) == 0:
                logger.error(f"❌ User with ID {user_id} not found in database. User needs to log in again.")
                raise ValueError("User not found. Please log out and log in again to refresh your session.")
            
            logger.info(f"✅ User {user_id} validated successfully")
            
            query = """
                INSERT INTO lecture_scripts 
                (user_id, book_id, title, scope, specific_topics, detail_level, difficulty, duration, content)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id, user_id, book_id, title, scope, specific_topics,
                         detail_level, difficulty, duration, content, created_at, updated_at
            """
            
            book_id = getattr(request, 'book_id', None)
            specific_topics = getattr(request, 'specific_topics', None)
            
            result = await self.db.execute_query(
                query,
                user_id, book_id, request.title, request.scope,
                specific_topics, request.detail_level, 
                request.difficulty, request.duration, request.content
            )
            
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
            
        except ValueError as ve:
            # Re-raise validation errors
            raise ve
        except Exception as e:
            logger.error(f"❌ Error creating lecture script: {e}")
            raise e

    async def get_lecture_script(self, script_id: str, user_id: str) -> Optional[dict]:
        """Get a specific lecture script by ID"""
        try:
            query = """
                SELECT id, user_id, book_id, title, scope, specific_topics, 
                       detail_level, difficulty, duration, content, created_at, updated_at
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
            logger.error(f"❌ Error getting lecture script {script_id}: {e}")
            raise e

    async def get_user_scripts(self, user_id: str) -> List[dict]:
        """Get all lecture scripts for a user"""
        try:
            query = """
                SELECT ls.id, ls.user_id, ls.book_id, ls.title, ls.scope, 
                       ls.specific_topics, ls.detail_level, ls.difficulty, 
                       ls.duration, ls.content, ls.created_at, ls.updated_at,
                       b.title as book_title, b.curriculum_id, c.name as curriculum_name
                FROM lecture_scripts ls
                LEFT JOIN books b ON ls.book_id = b.id
                LEFT JOIN curriculum c ON b.curriculum_id = c.id
                WHERE ls.user_id = $1
                ORDER BY ls.created_at DESC
            """
            
            result = await self.db.execute_query(query, user_id)
            
            scripts = []
            if result:
                for row in result:
                    scripts.append({
                        "id": str(row["id"]),
                        "user_id": str(row["user_id"]),
                        "book_id": row["book_id"],
                        "curriculum_id": row.get("curriculum_id"),  # From books table
                        "title": row["title"],
                        "scope": row["scope"],
                        "specific_topics": row["specific_topics"],
                        "detail_level": row["detail_level"],
                        "difficulty": row["difficulty"],
                        "duration": row["duration"],
                        "content": row["content"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "book_title": row.get("book_title"),
                        "curriculum_name": row.get("curriculum_name")
                    })
            
            return scripts
            
        except Exception as e:
            logger.error(f"❌ Error getting user scripts: {e}")
            raise e

    async def update_lecture_script(self, script_id: str, user_id: str, request: LectureScriptUpdate) -> Optional[dict]:
        """Update a lecture script"""
        try:
            from datetime import datetime
            
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
                return await self.get_lecture_script(script_id, user_id)
            
            update_fields.append(f"updated_at = ${param_count}")
            values.append(datetime.utcnow())
            param_count += 1
            
            values.extend([script_id, user_id])
            
            query = f"""
                UPDATE lecture_scripts 
                SET {', '.join(update_fields)}
                WHERE id = ${param_count} AND user_id = ${param_count + 1}
                RETURNING id, user_id, book_id, title, scope, specific_topics, 
                         detail_level, difficulty, duration, content, created_at, updated_at
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
            logger.error(f"❌ Error updating lecture script {script_id}: {e}")
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
            logger.error(f"❌ Error deleting lecture script {script_id}: {e}")
            raise e
