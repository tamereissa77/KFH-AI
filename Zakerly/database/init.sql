-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create users table for authentication
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for users table
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Categories table removed - using curriculum-only system

-- Create curriculum table (new enhanced system)
CREATE TABLE IF NOT EXISTS curriculum (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    created_by VARCHAR(255) DEFAULT 'system',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create books table (curriculum-only system)
CREATE TABLE IF NOT EXISTS books (
    id SERIAL PRIMARY KEY,
    curriculum_id INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    author VARCHAR(255),
    publication_year INTEGER,
    file_hash VARCHAR(255) NOT NULL UNIQUE,
    file_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_curriculum
        FOREIGN KEY (curriculum_id)
        REFERENCES curriculum(id),
    CONSTRAINT check_curriculum_required 
        CHECK (curriculum_id IS NOT NULL)
);

-- Create chat sessions table
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    book_id INTEGER,
    session_name VARCHAR(255),
    session_type VARCHAR(50) CHECK (session_type IN ('book', 'curriculum')),
    curriculum_name VARCHAR(255),
    book_title VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user
        FOREIGN KEY (user_id)
        REFERENCES users(id),
    CONSTRAINT fk_book
        FOREIGN KEY (book_id)
        REFERENCES books(id)
);

-- Create chat messages table
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    message_type VARCHAR(50) NOT NULL CHECK (message_type IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_session
        FOREIGN KEY (session_id)
        REFERENCES chat_sessions(id) ON DELETE CASCADE
);

-- Create chat_history table for LangChain compatibility
CREATE TABLE IF NOT EXISTS chat_history (
    id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    message TEXT NOT NULL,
    message_type VARCHAR(50) NOT NULL CHECK (message_type IN ('human', 'ai', 'system', 'user', 'assistant')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_chat_history_session
        FOREIGN KEY (session_id)
        REFERENCES chat_sessions(id) ON DELETE CASCADE
);

-- Create session memory table for enhanced agent memory features
CREATE TABLE IF NOT EXISTS session_memory (
    id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    memory_type VARCHAR(50) NOT NULL,
    key VARCHAR(255) NOT NULL,
    value JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    UNIQUE(session_id, memory_type, key),
    CONSTRAINT fk_session_memory
        FOREIGN KEY (session_id)
        REFERENCES chat_sessions(id) ON DELETE CASCADE
);

-- Create lecture scripts table
CREATE TABLE IF NOT EXISTS lecture_scripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    book_id INTEGER,
    title VARCHAR(255) NOT NULL,
    scope VARCHAR(50) NOT NULL CHECK (scope IN ('whole_curriculum', 'whole_book', 'specific_topics')),
    specific_topics TEXT,
    detail_level VARCHAR(50) NOT NULL CHECK (detail_level IN ('overview', 'detailed', 'in-depth')),
    difficulty VARCHAR(50) NOT NULL CHECK (difficulty IN ('beginner', 'intermediate', 'advanced')),
    duration INTEGER NOT NULL, -- duration in minutes
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_script_user
        FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_script_book
        FOREIGN KEY (book_id)
        REFERENCES books(id) ON DELETE CASCADE
);

-- Create presentations table
CREATE TABLE IF NOT EXISTS presentations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    book_id INTEGER,
    title TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('whole_curriculum', 'whole_book', 'specific_topics')),
    specific_topics TEXT,
    detail_level TEXT NOT NULL CHECK (detail_level IN ('overview', 'detailed', 'comprehensive')),
    difficulty TEXT NOT NULL CHECK (difficulty IN ('beginner', 'intermediate', 'advanced')),
    slides_count INTEGER NOT NULL DEFAULT 15 CHECK (slides_count >= 5 AND slides_count <= 50),
    slide_style TEXT NOT NULL DEFAULT 'professional' CHECK (slide_style IN ('professional', 'creative', 'minimal')),
    include_diagrams BOOLEAN DEFAULT true,
    include_code_examples BOOLEAN DEFAULT false,
    content JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_presentation_user
        FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_presentation_book
        FOREIGN KEY (book_id)
        REFERENCES books(id) ON DELETE SET NULL
);

-- Create user activities table for tracking user engagement
CREATE TABLE IF NOT EXISTS user_activities (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    activity_type VARCHAR(100) NOT NULL, -- 'login', 'dashboard_view', 'book_added', 'script_created', 'chat_started', etc.
    activity_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}', -- Additional data like book_id, script_id, etc.
    CONSTRAINT fk_activity_user
        FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE
);

-- Create user progress table for tracking learning progress
CREATE TABLE IF NOT EXISTS user_progress (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    book_id INTEGER,
    curriculum_id INTEGER,
    progress_percentage DECIMAL(5,2) DEFAULT 0.0 CHECK (progress_percentage >= 0 AND progress_percentage <= 100),
    completed BOOLEAN DEFAULT FALSE,
    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, book_id),
    CONSTRAINT fk_progress_user
        FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_progress_book
        FOREIGN KEY (book_id)
        REFERENCES books(id) ON DELETE CASCADE,
    CONSTRAINT fk_progress_curriculum
        FOREIGN KEY (curriculum_id)
        REFERENCES curriculum(id) ON DELETE CASCADE
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_books_curriculum_id ON books(curriculum_id);
CREATE INDEX IF NOT EXISTS idx_books_file_hash ON books(file_hash);
CREATE INDEX IF NOT EXISTS idx_curriculum_name ON curriculum(name);
CREATE INDEX IF NOT EXISTS idx_curriculum_created_by ON curriculum(created_by);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_book_id ON chat_sessions(book_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_chat_history_session_id ON chat_history(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_created_at ON chat_history(created_at);
CREATE INDEX IF NOT EXISTS idx_session_memory_session_type ON session_memory(session_id, memory_type);
CREATE INDEX IF NOT EXISTS idx_session_memory_expires ON session_memory(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lecture_scripts_user_id ON lecture_scripts(user_id);
CREATE INDEX IF NOT EXISTS idx_lecture_scripts_book_id ON lecture_scripts(book_id);
CREATE INDEX IF NOT EXISTS idx_presentations_user_id ON presentations(user_id);
CREATE INDEX IF NOT EXISTS idx_presentations_book_id ON presentations(book_id);
CREATE INDEX IF NOT EXISTS idx_presentations_created_at ON presentations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_presentations_scope ON presentations(scope);
CREATE INDEX IF NOT EXISTS idx_user_activities_user_id ON user_activities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_activities_type ON user_activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_user_activities_date ON user_activities(activity_date DESC);
CREATE INDEX IF NOT EXISTS idx_user_progress_user_id ON user_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_user_progress_book_id ON user_progress(book_id);
CREATE INDEX IF NOT EXISTS idx_user_progress_curriculum_id ON user_progress(curriculum_id);
CREATE INDEX IF NOT EXISTS idx_user_progress_last_accessed ON user_progress(last_accessed DESC);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger for users
CREATE TRIGGER update_users_updated_at 
    BEFORE UPDATE ON users 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create trigger for chat_sessions
CREATE TRIGGER update_chat_sessions_updated_at 
    BEFORE UPDATE ON chat_sessions 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create trigger for session_memory
CREATE TRIGGER update_session_memory_updated_at 
    BEFORE UPDATE ON session_memory 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create trigger for curriculum
CREATE TRIGGER update_curriculum_updated_at 
    BEFORE UPDATE ON curriculum 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create trigger for lecture_scripts
CREATE TRIGGER update_lecture_scripts_updated_at 
    BEFORE UPDATE ON lecture_scripts 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create trigger for presentations
CREATE TRIGGER update_presentations_updated_at 
    BEFORE UPDATE ON presentations 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create functions for curriculum embedding tables
CREATE OR REPLACE FUNCTION create_curriculum_embedding_table(curriculum_name TEXT, embedding_dimension INTEGER DEFAULT 1536)
RETURNS TEXT AS $$
DECLARE
    table_name TEXT;
    safe_name TEXT;
BEGIN
    -- Create safe table name from curriculum name
    safe_name := regexp_replace(lower(curriculum_name), '[^a-z0-9_]', '_', 'g');
    safe_name := regexp_replace(safe_name, '_+', '_', 'g');
    safe_name := trim(safe_name, '_');
    table_name := 'curriculum_embeddings_' || safe_name;
    
    -- Create the table with dynamic embedding dimension
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I (
            id SERIAL PRIMARY KEY,
            curriculum_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB,
            embedding vector(%s),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_%I_curriculum
                FOREIGN KEY (curriculum_id)
                REFERENCES curriculum(id) ON DELETE CASCADE,
            CONSTRAINT fk_%I_book
                FOREIGN KEY (book_id)
                REFERENCES books(id) ON DELETE CASCADE
        )', table_name, embedding_dimension, table_name, table_name);
    
    -- Create indexes
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%I_curriculum_id ON %I(curriculum_id)', table_name, table_name);
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%I_book_id ON %I(book_id)', table_name, table_name);
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%I_embedding ON %I USING ivfflat (embedding vector_cosine_ops)', table_name, table_name);
    
    RETURN table_name;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_curriculum_embedding_table_name(curriculum_name TEXT)
RETURNS TEXT AS $$
DECLARE
    safe_name TEXT;
BEGIN
    safe_name := regexp_replace(lower(curriculum_name), '[^a-z0-9_]', '_', 'g');
    safe_name := regexp_replace(safe_name, '_+', '_', 'g');
    safe_name := trim(safe_name, '_');
    RETURN 'curriculum_embeddings_' || safe_name;
END;
$$ LANGUAGE plpgsql;

-- Create default embedding tables for initial curriculums
DO $$
DECLARE
    curr RECORD;
BEGIN
    FOR curr IN SELECT name FROM curriculum LOOP
        PERFORM create_curriculum_embedding_table(curr.name, 1536);
    END LOOP;
END $$;

-- Add table comments
COMMENT ON TABLE presentations IS 'Stores generated presentations with slide content in JSON format';
COMMENT ON COLUMN presentations.content IS 'JSON structure containing slides array with title, content, visual_suggestions, and speaker_notes';
COMMENT ON COLUMN presentations.scope IS 'Determines the generation scope: whole_curriculum, whole_book, or specific_topics';
COMMENT ON COLUMN presentations.slide_style IS 'Visual style of presentation: professional, creative, or minimal';
