// API configuration
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8007';

// API endpoints
export const API_ENDPOINTS = {
  // Books & Ingestion
  UPLOAD_BOOK: '/api/v1/upload',
  BOOKS: '/api/v1/books',
  BOOK_BY_ID: (id: number) => `/api/v1/books/${id}`,
  DELETE_BOOK: (id: number) => `/api/v1/books/${id}`,
  
  // Curriculums
  CURRICULUMS: '/api/v1/curriculums',
  CURRICULUM_BY_ID: (id: number) => `/api/v1/curriculums/${id}`,
  CURRICULUM_BOOKS: (id: number) => `/api/v1/curriculums/${id}/books`,
  DELETE_CURRICULUM: (id: number) => `/api/v1/curriculums/${id}`,
  
  // Chat
  CHAT: '/api/v1/chat',
  GENERATE_QUESTIONS: '/api/v1/generate-questions',
  GENERATE_LECTURE: '/api/v1/generate-lecture',
  GENERATE_CURRICULUM_SCRIPT: '/api/v1/curriculum-scripts/generate',
  
  // Sessions
  SESSIONS: '/api/v1/sessions',
  SESSION_BY_ID: (id: string) => `/api/v1/sessions/${id}`,
  USER_SESSIONS: (userId: string) => `/api/v1/users/${userId}/sessions`,
  CHAT_HISTORY: (sessionId: string) => `/api/v1/sessions/${sessionId}/history`,
  DELETE_SESSION: (sessionId: string) => `/api/v1/sessions/${sessionId}`,
  
  // Scripts
  SCRIPTS: '/api/v1/scripts',
  SCRIPT_BY_ID: (id: string) => `/api/v1/scripts/${id}`,
  USER_SCRIPTS: (userId: string) => `/api/v1/users/${userId}/scripts`,
  
  // Presentations
  GENERATE_PRESENTATION: '/api/v1/presentations/generate',
  PRESENTATIONS: '/api/v1/presentations',
  PRESENTATION_BY_ID: (id: string) => `/api/v1/presentations/${id}`,
  USER_PRESENTATIONS: (userId: string) => `/api/v1/users/${userId}/presentations`,
  
  // System
  HEALTH: '/health',
  STATUS: '/api/v1/status'
};

// Generic API client
class ApiClient {
  private baseURL: string;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }

  private async request<T>(
    endpoint: string, 
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;
    
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      
      // ✅ CRITICAL FIX: Handle 401 Unauthorized (expired/invalid user sessions)
      if (response.status === 401) {
        console.error('🔒 Session expired or invalid user. Clearing local storage and redirecting to login...');
        
        // Clear all cached data
        localStorage.clear();
        sessionStorage.clear();
        
        // Show user-friendly error
        const errorMessage = errorData.detail || 'Your session has expired. Please log in again.';
        
        // Redirect to signin after a brief delay
        setTimeout(() => {
          window.location.href = '/signin';
        }, 1000);
        
        throw new Error(errorMessage);
      }
      
      throw new Error(errorData.error || errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
    }

    return response.json();
  }

  async get<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'GET' });
  }

  async post<T>(endpoint: string, data?: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async postFormData<T>(endpoint: string, formData: FormData): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;
    
    const response = await fetch(url, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
    }

    return response.json();
  }

  async delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'DELETE' });
  }

  async put<T>(endpoint: string, data?: any): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }
}

export const apiClient = new ApiClient(API_BASE_URL);
