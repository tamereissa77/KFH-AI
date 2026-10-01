import { apiClient, API_ENDPOINTS } from './api';
import type {
  Book,
  Curriculum,
  CurriculumCreateRequest,
  ChatRequest,
  ChatResponse,
  QuestionGenerationRequest,
  QuestionResponse,
  LectureRequest,
  LectureScript,
  LectureScriptRequest,
  LectureScriptUpdate,
  ChatSession,
  ChatMessage,
  SystemStatus,
  UploadProgress,
  Presentation,
  PresentationGenerateRequest,
  PresentationCreateRequest,
  PresentationUpdate
} from './types';

// Books Service
export class BooksService {
  static async uploadBook(
    file: File,
    curriculumId: number,
    onProgress?: (progress: UploadProgress) => void
  ): Promise<Book> {
    const formData = new FormData();
    formData.append('file', file);

    const endpoint = `${API_ENDPOINTS.UPLOAD_BOOK}?curriculum_id=${curriculumId}`;
    return apiClient.postFormData<Book>(endpoint, formData);
  }

  static async getBooks(options?: { curriculumId?: number }): Promise<Book[]> {
    let endpoint = API_ENDPOINTS.BOOKS;
    const params = new URLSearchParams();
    
    if (options?.curriculumId) {
      params.append('curriculum_id', options.curriculumId.toString());
    }
    
    if (params.size > 0) {
      endpoint += `?${params.toString()}`;
    }
    
    return apiClient.get<Book[]>(endpoint);
  }

  static async getBookById(id: number): Promise<Book> {
    return apiClient.get<Book>(API_ENDPOINTS.BOOK_BY_ID(id));
  }

  static async deleteBook(id: number): Promise<{ message: string }> {
    return apiClient.delete<{ message: string }>(API_ENDPOINTS.DELETE_BOOK(id));
  }
}

// Curriculum Service
export class CurriculumService {
  static async createCurriculum(curriculum: CurriculumCreateRequest): Promise<Curriculum> {
    return apiClient.post<Curriculum>(API_ENDPOINTS.CURRICULUMS, curriculum);
  }

  static async getCurriculums(): Promise<Curriculum[]> {
    return apiClient.get<Curriculum[]>(API_ENDPOINTS.CURRICULUMS);
  }

  static async getCurriculumById(id: number): Promise<Curriculum> {
    return apiClient.get<Curriculum>(API_ENDPOINTS.CURRICULUM_BY_ID(id));
  }

  static async updateCurriculum(id: number, curriculum: CurriculumCreateRequest): Promise<Curriculum> {
    return apiClient.put<Curriculum>(API_ENDPOINTS.CURRICULUM_BY_ID(id), curriculum);
  }

  static async deleteCurriculum(id: number): Promise<{ message: string }> {
    return apiClient.delete<{ message: string }>(API_ENDPOINTS.DELETE_CURRICULUM(id));
  }

  static async getCurriculumBooks(id: number): Promise<Book[]> {
    return apiClient.get<Book[]>(API_ENDPOINTS.CURRICULUM_BOOKS(id));
  }
}

// Chat Service
export class ChatService {
  static async sendMessage(request: ChatRequest): Promise<ChatResponse> {
    return apiClient.post<ChatResponse>(API_ENDPOINTS.CHAT, request);
  }

  static async generateQuestions(request: QuestionGenerationRequest): Promise<QuestionResponse> {
    return apiClient.post<QuestionResponse>(API_ENDPOINTS.GENERATE_QUESTIONS, request);
  }

  static async generateLecture(request: LectureRequest): Promise<{ lecture: string }> {
    return apiClient.post<{ lecture: string }>(API_ENDPOINTS.GENERATE_LECTURE, request);
  }

  static async generateCurriculumScript(userId: string, request: any): Promise<any> {
    // ✅ Use authenticated user ID passed as parameter
    const endpoint = `${API_ENDPOINTS.GENERATE_CURRICULUM_SCRIPT}?user_id=${userId}`;
    return apiClient.post<any>(endpoint, request);
  }
}

// Session Management Service
export class SessionService {
  static async createSession(
    userId: string,
    bookTitleOrCurriculum: string,
    sessionName?: string,
    isCurriculum: boolean = false
  ): Promise<ChatSession> {
    // Build query parameters to match FastAPI endpoint signature
    const params = new URLSearchParams();
    params.append('user_id', userId);
    
    if (isCurriculum) {
      params.append('curriculum_name', bookTitleOrCurriculum);
    } else {
      params.append('book_title', bookTitleOrCurriculum);
    }
    
    if (sessionName) {
      params.append('session_name', sessionName);
    }
    
    // Send as query parameters in URL
    const endpoint = `${API_ENDPOINTS.SESSIONS}?${params.toString()}`;
    return apiClient.post<ChatSession>(endpoint, {});
  }

  static async getSession(sessionId: string): Promise<ChatSession> {
    return apiClient.get<ChatSession>(API_ENDPOINTS.SESSION_BY_ID(sessionId));
  }

  static async getUserSessions(userId: string): Promise<ChatSession[]> {
    return apiClient.get<ChatSession[]>(API_ENDPOINTS.USER_SESSIONS(userId));
  }

  static async getChatHistory(sessionId: string, limit = 50): Promise<{ history: ChatMessage[] }> {
    const endpoint = `${API_ENDPOINTS.CHAT_HISTORY(sessionId)}?limit=${limit}`;
    return apiClient.get<{ history: ChatMessage[] }>(endpoint);
  }

  static async deleteSession(sessionId: string): Promise<{ message: string }> {
    return apiClient.delete<{ message: string }>(API_ENDPOINTS.DELETE_SESSION(sessionId));
  }
}

// System Service
export class SystemService {
  static async getHealth(): Promise<any> {
    return apiClient.get(API_ENDPOINTS.HEALTH);
  }

  static async getStatus(): Promise<SystemStatus> {
    return apiClient.get<SystemStatus>(API_ENDPOINTS.STATUS);
  }
}

// Scripts Service
export class ScriptsService {
  static async createScript(userId: string, request: LectureScriptRequest): Promise<LectureScript> {
    const endpoint = `${API_ENDPOINTS.SCRIPTS}?user_id=${userId}`;
    return apiClient.post<LectureScript>(endpoint, request);
  }

  static async getScript(scriptId: string, userId: string): Promise<LectureScript> {
    const endpoint = `${API_ENDPOINTS.SCRIPT_BY_ID(scriptId)}?user_id=${userId}`;
    return apiClient.get<LectureScript>(endpoint);
  }

  static async getUserScripts(userId: string): Promise<LectureScript[]> {
    return apiClient.get<LectureScript[]>(API_ENDPOINTS.USER_SCRIPTS(userId));
  }

  static async updateScript(scriptId: string, userId: string, request: LectureScriptUpdate): Promise<LectureScript> {
    const endpoint = `${API_ENDPOINTS.SCRIPT_BY_ID(scriptId)}?user_id=${userId}`;
    return apiClient.put<LectureScript>(endpoint, request);
  }

  static async deleteScript(scriptId: string, userId: string): Promise<{ message: string }> {
    const endpoint = `${API_ENDPOINTS.SCRIPT_BY_ID(scriptId)}?user_id=${userId}`;
    return apiClient.delete<{ message: string }>(endpoint);
  }
}

// Presentations Service
export class PresentationsService {
  static async generatePresentation(userId: string, request: PresentationGenerateRequest): Promise<any> {
    const endpoint = `${API_ENDPOINTS.GENERATE_PRESENTATION}?user_id=${userId}`;
    return apiClient.post<any>(endpoint, request);
  }

  static async createPresentation(userId: string, request: PresentationCreateRequest): Promise<Presentation> {
    const endpoint = `${API_ENDPOINTS.PRESENTATIONS}?user_id=${userId}`;
    return apiClient.post<Presentation>(endpoint, request);
  }

  static async getPresentation(presentationId: string, userId: string): Promise<Presentation> {
    const endpoint = `${API_ENDPOINTS.PRESENTATION_BY_ID(presentationId)}?user_id=${userId}`;
    return apiClient.get<Presentation>(endpoint);
  }

  static async getUserPresentations(userId: string): Promise<Presentation[]> {
    const response = await apiClient.get<{presentations: Presentation[], count: number}>(API_ENDPOINTS.USER_PRESENTATIONS(userId));
    return response.presentations;
  }

  static async updatePresentation(presentationId: string, userId: string, request: PresentationUpdate): Promise<Presentation> {
    const endpoint = `${API_ENDPOINTS.PRESENTATION_BY_ID(presentationId)}?user_id=${userId}`;
    return apiClient.put<Presentation>(endpoint, request);
  }

  static async deletePresentation(presentationId: string, userId: string): Promise<{ message: string }> {
    const endpoint = `${API_ENDPOINTS.PRESENTATION_BY_ID(presentationId)}?user_id=${userId}`;
    return apiClient.delete<{ message: string }>(endpoint);
  }
}

// Utility functions
export class Utils {
  static generateUserId(): string {
    // Generate a proper UUID for database compatibility
    let userId = localStorage.getItem('zakerly_user_id');
    
    // Check if existing userId is in old format and clear it
    if (userId && (userId.startsWith('user_') || userId.length < 32)) {
      localStorage.removeItem('zakerly_user_id');
      userId = null;
    }
    
    if (!userId) {
      // Generate a proper UUID v4
      userId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
      });
      localStorage.setItem('zakerly_user_id', userId);
    }
    return userId;
  }



  static formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  static getFileExtension(filename: string): string {
    return filename.slice((filename.lastIndexOf('.') - 1 >>> 0) + 2);
  }

  static validateFileType(file: File): { valid: boolean; error?: string } {
    const allowedTypes = ['application/pdf', 'text/plain', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
    const allowedExtensions = ['pdf', 'txt', 'docx'];
    
    const extension = this.getFileExtension(file.name).toLowerCase();
    
    if (!allowedTypes.includes(file.type) && !allowedExtensions.includes(extension)) {
      return {
        valid: false,
        error: 'Only PDF, TXT, and DOCX files are supported'
      };
    }
    
    const maxSize = 100 * 1024 * 1024; // 100MB
    if (file.size > maxSize) {
      return {
        valid: false,
        error: 'File size must be less than 100MB'
      };
    }
    
    return { valid: true };
  }
}
