from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import uuid

class CurriculumModel(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_by: str = 'system'
    created_at: datetime
    updated_at: datetime

class BookModel(BaseModel):
    id: Optional[int] = None
    curriculum_id: int
    title: str
    author: Optional[str] = None
    publication_year: Optional[int] = None
    file_hash: str
    file_name: str
    created_at: Optional[datetime] = None

class BookMetadata(BaseModel):
    curriculum_id: int
    curriculum_name: str
    title: str
    author: Optional[str] = None
    publication_year: Optional[int] = None
    file_hash: str
    file_name: str

class MessageType(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"

class ChatSessionModel(BaseModel):
    id: Optional[str] = None
    user_id: str
    book_id: Optional[int] = None
    session_name: Optional[str] = None
    session_type: Optional[str] = None
    curriculum_name: Optional[str] = None
    book_title: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @validator('id', pre=True)
    @classmethod
    def convert_uuid_to_string(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

class ChatMessageModel(BaseModel):
    id: Optional[int] = None
    session_id: str
    message_type: MessageType
    content: str
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

class ChatRequest(BaseModel):
    curriculum: str = Field(..., description="Curriculum name (required)")
    session_id: Optional[str] = Field(default="", description="Chat session ID - empty string for new sessions")
    user_message: str = Field(..., description="User's message")
    intent: Optional[str] = Field(default="answer_question", description="Chat intent")

class ChatResponse(BaseModel):
    response: str
    session_id: str
    intent: str
    metadata: Optional[Dict[str, Any]] = None

class QuestionGenerationRequest(BaseModel):
    curriculum: Optional[str] = Field(None, description="Curriculum name")
    book_title: Optional[str] = Field(None, description="Specific book title")
    curriculum_id: Optional[str] = Field(None, description="Curriculum ID")
    user_message: str
    topics: Optional[List[str]] = None
    count: Optional[int] = 5
    difficulty: Optional[List[str]] = None
    question_types: Optional[List[str]] = None
    scope_type: Optional[str] = "whole_book"  # 'whole_curriculum', 'whole_book' or 'specific_topics'
    specific_topics: Optional[str] = None
    time_limit: Optional[int] = None  # in minutes

class Question(BaseModel):
    difficulty: str
    type: str
    question_text: str
    options: List[str]
    answer: str

class QuestionResponse(BaseModel):
    chapter: str
    questions_generated: List[Question]

class LectureRequest(BaseModel):
    curriculum: str = Field(..., description="Curriculum name (required)")
    user_message: str
    title: Optional[str] = None
    scope: Optional[str] = "whole_book"  # 'whole_book' or 'specific_topics'
    specific_topics: Optional[str] = None
    detail_level: Optional[str] = "overview"  # 'overview', 'detailed', 'in-depth'

class LectureScript(BaseModel):
    id: Optional[str] = None
    user_id: str
    book_id: int
    title: str
    scope: str = Field(..., description="Scope: whole_book or specific_topics")
    specific_topics: Optional[str] = None
    detail_level: str = Field(..., description="Detail level: overview, detailed, or in-depth")
    difficulty: str = Field(..., description="Difficulty: beginner, intermediate, or advanced")
    duration: int = Field(..., description="Duration in minutes")
    content: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @validator('id', pre=True)
    @classmethod
    def convert_uuid_to_string(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v
    
    @validator('user_id', pre=True)
    @classmethod
    def convert_user_id_to_string(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

class LectureScriptRequest(BaseModel):
    book_id: Optional[int] = None  # Optional: null for curriculum-wide scripts
    title: str
    scope: str = Field(..., description="Scope: whole_curriculum, whole_book or specific_topics")
    specific_topics: Optional[str] = None
    detail_level: str = Field(..., description="Detail level: overview, detailed, or in-depth")
    difficulty: str = Field(..., description="Difficulty: beginner, intermediate, or advanced")
    duration: int = Field(..., description="Duration in minutes")
    content: str

class LectureScriptUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    scope: Optional[str] = None
    specific_topics: Optional[str] = None
    detail_level: Optional[str] = None
    difficulty: Optional[str] = None
    duration: Optional[int] = None

# Curriculum-specific models
class CurriculumCreateRequest(BaseModel):
    name: str = Field(..., description="Curriculum name")
    description: Optional[str] = Field(None, description="Curriculum description")
    created_by: str = Field('user', description="Who created this curriculum")

class HealthCheck(BaseModel):
    status: str
    timestamp: datetime
    service: str
    version: str

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    timestamp: datetime

class CurriculumScriptRequest(BaseModel):
    curriculum_id: int
    title: str
    scope: str = Field(..., description="Scope: whole_curriculum, whole_book, or specific_topics")
    specific_books: Optional[List[int]] = None
    specific_topics: Optional[str] = None
    detail_level: str = Field(..., description="Detail level: overview, detailed, or in-depth")
    difficulty: str = Field(..., description="Difficulty: beginner, intermediate, or advanced")
    duration: int = Field(..., description="Duration in minutes")

# User Activity and Progress Tracking Models
class UserActivityModel(BaseModel):
    id: Optional[int] = None
    user_id: str
    activity_type: str  # "login", "dashboard_view", "book_added", "script_created", "chat_started", etc.
    activity_date: Optional[datetime] = None
    metadata: Optional[str] = None  # JSON string for additional data

class UserCourseProgressModel(BaseModel):
    id: Optional[int] = None
    user_id: str
    course_id: Optional[int] = None
    book_id: Optional[int] = None
    progress_percentage: Optional[float] = 0.0
    completed: Optional[bool] = False
    last_accessed: Optional[datetime] = None
    enrolled_at: Optional[datetime] = None

class UserStatsModel(BaseModel):
    totalBooks: int
    totalScripts: int
    totalSessions: int
    totalChats: int
    learningHours: float
    streak: int
    lastActivity: str

class RecentActivityModel(BaseModel):
    courseName: str
    lastAccessed: str
    progress: float
    activityType: str