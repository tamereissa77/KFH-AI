import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Header } from '@/components/ui/header';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Send, BookOpen, Download, Copy, ExternalLink, Loader2, AlertCircle, ArrowLeft, Plus, GraduationCap } from 'lucide-react';
import { cn } from '@/lib/utils';
import { BooksService, ChatService, SessionService, Utils, CurriculumService } from '@/lib/services';
import type { Book as BookType, ChatMessage, ChatSession, ChatResponse, Curriculum, QuestionGenerationRequest } from '@/lib/types';
import { useAuth } from '@/contexts/AuthContext';

interface Message {
  id: string;
  type: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  metadata?: any;
}

export default function Chat() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const curriculumParam = searchParams.get('curriculum');
  const { user } = useAuth(); // ✅ Get authenticated user from AuthContext
  
  const [curriculums, setCurriculums] = useState<Curriculum[]>([]);
  const [selectedCurriculum, setSelectedCurriculum] = useState<string>('');
  const [books, setBooks] = useState<BookType[]>([]);
  const [allBooks, setAllBooks] = useState<BookType[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentMessage, setCurrentMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingData, setIsLoadingData] = useState(true);
  const [error, setError] = useState('');
  const [currentSession, setCurrentSession] = useState<ChatSession | null>(null);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const userId = user?.sub || ''; // ✅ Use authenticated user's ID from JWT token

  const selectedCurriculumData = curriculums.find(curr => curr.id.toString() === selectedCurriculum);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Load books and categories on component mount
  useEffect(() => {
    loadData();
  }, []);

  // Set selected curriculum from URL param
  useEffect(() => {
    if (curriculumParam && allBooks.length > 0 && curriculums.length > 0) {
      const decodedCurriculum = decodeURIComponent(curriculumParam);
      const curriculum = curriculums.find(c => c.name === decodedCurriculum);
      if (curriculum) {
        setSelectedCurriculum(curriculum.id.toString());
        handleCurriculumChange(curriculum.id.toString());
      }
    }
  }, [curriculumParam, allBooks, curriculums]);

  const loadData = async () => {
    try {
      setIsLoadingData(true);
      const [booksData, curriculumsData] = await Promise.all([
        BooksService.getBooks(),
        CurriculumService.getCurriculums()
      ]);
      setAllBooks(booksData);
      setBooks(booksData);
      setCurriculums(curriculumsData);
    } catch (err) {
      console.error('Error loading data:', err);
      setError('Failed to load books and curriculums');
    } finally {
      setIsLoadingData(false);
    }
  };

  const handleCurriculumChange = (curriculumId: string) => {
    setSelectedCurriculum(curriculumId);
    setMessages([]);
    setCurrentSession(null);
    
    if (curriculumId === 'all') {
      setBooks(allBooks);
    } else {
      const filteredBooks = allBooks.filter(book => book.curriculum_id === parseInt(curriculumId));
      setBooks(filteredBooks);
    }
  };

  const loadChatSession = async (curriculumName: string) => {
    try {
      // Try to get existing sessions for this user and curriculum
      const sessions = await SessionService.getUserSessions(userId);
      const existingSession = sessions.find(session => 
        session.session_name?.includes(curriculumName)
      );

      if (existingSession) {
        setCurrentSession(existingSession);
        const history = await SessionService.getChatHistory(existingSession.id);
        const formattedMessages: Message[] = history.history.map(msg => ({
          id: msg.id.toString(),
          type: msg.message_type,
          content: msg.content,
          timestamp: new Date(msg.created_at),
          metadata: msg.metadata
        }));
        setMessages(formattedMessages);
      }
    } catch (err) {
      console.error('Error loading chat session:', err);
      // Continue without existing session
    }
  };

  const handleSendMessage = async () => {
    if (!currentMessage.trim() || !selectedCurriculum || isLoading) return;

    const curriculum = selectedCurriculumData;
    if (!curriculum) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: currentMessage,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    const messageToSend = currentMessage;
    setCurrentMessage('');
    setIsLoading(true);
    setError('');

    try {
      // Create session if needed
      let sessionId = currentSession?.id || '';
      if (!currentSession) {
        // Create session for curriculum-based chat
        const newSession = await SessionService.createSession(
          userId,
          curriculum.name,
          `Chat with ${curriculum.name} Curriculum`,
          true // isCurriculum = true
        );
        setCurrentSession(newSession);
        sessionId = newSession.id;
      }

      // Send curriculum-based chat request (book_title required by current API)
      const chatRequest = {
        curriculum: curriculum.name,
        book_title: books.length > 0 ? books[0].title : 'Curriculum Books',
        session_id: sessionId,
        user_message: messageToSend,
        intent: 'answer_question'
      };

      const response = await ChatService.sendMessage(chatRequest);

      const aiMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: response.response,
        timestamp: new Date(),
        metadata: response.metadata
      };

      setMessages(prev => [...prev, aiMessage]);

    } catch (err) {
      console.error('Error sending message:', err);
      let errorMessage = 'Failed to send message';
      
      if (err instanceof Error) {
        errorMessage = err.message;
      } else if (typeof err === 'object' && err !== null) {
        // Fix: Properly stringify error objects
        errorMessage = JSON.stringify(err);
      }
      
      setError(errorMessage);
      
      // Add error message to chat
      const errorChatMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: 'I apologize, but I encountered an error processing your message. Please try again.',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errorChatMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const exportChat = () => {
    const chatContent = messages.map(msg => 
      `[${msg.timestamp.toLocaleTimeString()}] ${msg.type === 'user' ? 'You' : 'AI'}: ${msg.content}`
    ).join('\n\n');
    
    const blob = new Blob([chatContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat-${selectedCurriculumData?.name || 'conversation'}.txt`;
    a.click();
  };

  const handleNewChat = async () => {
    try {
      // Clear current session and messages
      setCurrentSession(null);
      setMessages([]);
      setError('');
      
      // If there's a selected curriculum, create a new session immediately
      if (selectedCurriculum && selectedCurriculumData) {
        const newSession = await SessionService.createSession(
          userId,
          selectedCurriculumData.name,
          `Chat with ${selectedCurriculumData.name} Curriculum`,
          true // isCurriculum = true
        );
        setCurrentSession(newSession);
      }
    } catch (err) {
      console.error('Error creating new chat session:', err);
      setError('Failed to create new chat session');
    }
  };

  const copyToClipboard = () => {
    const chatContent = messages.map(msg => 
      `${msg.type === 'user' ? 'You' : 'AI'}: ${msg.content}`
    ).join('\n\n');
    
    navigator.clipboard.writeText(chatContent);
  };

  if (isLoadingData) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
        <Header />
        <div className="container mx-auto px-4 py-8">
          <div className="flex items-center justify-center h-64">
            <div className="text-center">
              <Loader2 className="w-8 h-8 animate-spin mx-auto mb-4 text-primary" />
              <p className="text-muted-foreground">Loading curriculums and books...</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
      <Header />
      
      <div className="container mx-auto px-4 py-8 h-screen flex flex-col">
        <div className="max-w-4xl mx-auto flex-1 flex flex-col">
          {/* Header Section */}
          <div className="flex items-center gap-4 mb-8">
            <Button 
              variant="outline" 
              onClick={() => navigate('/books')}
              className="flex items-center gap-2"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Library
            </Button>
            <div>
              <h1 className="text-3xl font-bold text-gradient-primary mb-2">
                Chat with Your Books
              </h1>
              <p className="text-muted-foreground">
                Ask questions and get AI-powered insights from your academic materials
              </p>
            </div>
          </div>

          {allBooks.length === 0 ? (
            <Card>
              <CardContent className="pt-8 pb-8">
                <div className="text-center">
                  <BookOpen className="w-16 h-16 text-muted-foreground mx-auto mb-4" />
                  <h3 className="text-lg font-semibold mb-2">No books available</h3>
                  <p className="text-muted-foreground mb-4">
                    Add some books to your library first to start chatting with them.
                  </p>
                  <Button onClick={() => navigate('/books/add')} className="bg-gradient-primary">
                    Add Your First Book
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <>
              {/* Curriculum Selection */}
              <Card className="mb-6">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <GraduationCap className="w-5 h-5 text-primary" />
                    Select a Curriculum
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Curriculum Selection */}
                  <div>
                    <label className="text-sm font-medium mb-2 block">Curriculum</label>
                    <Select value={selectedCurriculum} onValueChange={handleCurriculumChange}>
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Choose a curriculum to chat with..." />
                      </SelectTrigger>
                      <SelectContent>
                        {curriculums.map((curriculum) => (
                          <SelectItem key={curriculum.id} value={curriculum.id.toString()}>
                            <div className="flex flex-col">
                              <span className="font-medium">{curriculum.name}</span>
                              {curriculum.description && (
                                <span className="text-sm text-muted-foreground">
                                  {curriculum.description}
                                </span>
                              )}
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  
                  {selectedCurriculumData && (
                    <div className="mt-4 p-4 bg-primary/5 rounded-lg border border-primary/20">
                      <div className="flex items-center gap-3">
                        <div className="w-12 h-16 bg-gradient-to-br from-primary to-secondary rounded shadow-sm flex items-center justify-center">
                          <GraduationCap className="w-6 h-6 text-white" />
                        </div>
                        <div>
                          <h3 className="font-semibold">{selectedCurriculumData.name}</h3>
                          <p className="text-sm text-muted-foreground">
                            {selectedCurriculumData.description || 'Curriculum description'}
                          </p>
                          <div className="flex gap-2 mt-2">
                            <Badge variant="secondary">
                              {books.length} {books.length === 1 ? 'Book' : 'Books'}
                            </Badge>
                            <Badge variant="outline" className="text-xs">
                              <GraduationCap className="w-3 h-3 mr-1" />
                              AI Enhanced
                            </Badge>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Error Alert */}
              {error && (
                <Alert variant="destructive" className="mb-6">
                  <AlertCircle className="w-4 h-4" />
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              {/* Chat Interface */}
              {selectedCurriculum && (
                <Card className="flex-1 flex flex-col bg-white shadow-lg">
                  <CardHeader className="border-b shrink-0">
                    <div className="flex items-center justify-between">
                      <CardTitle>Chat Session</CardTitle>
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleNewChat}
                          className="flex items-center gap-2"
                        >
                          <Plus className="w-4 h-4" />
                          NEW CHAT
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={copyToClipboard}
                          disabled={messages.length === 0}
                        >
                          <Copy className="w-4 h-4 mr-2" />
                          Copy
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={exportChat}
                          disabled={messages.length === 0}
                        >
                          <Download className="w-4 h-4 mr-2" />
                          Export
                        </Button>
                      </div>
                    </div>
                  </CardHeader>
                  
                  <CardContent className="flex-1 flex flex-col p-0 min-h-0">
                    {/* Messages Area */}
                    <div className="flex-1 overflow-hidden">
                      <ScrollArea className="h-full">
                        <div className="p-6">
                          {messages.length === 0 ? (
                            <div className="flex items-center justify-center h-64 text-center">
                              <div className="space-y-3">
                                <div className="w-16 h-16 bg-gradient-to-br from-primary to-secondary rounded-full flex items-center justify-center mx-auto">
                                  <BookOpen className="w-8 h-8 text-white" />
                                </div>
                                <h3 className="text-lg font-semibold">Start Your Conversation</h3>
                                <p className="text-muted-foreground max-w-md">
                                  Ask questions about the "{selectedCurriculumData?.name}" curriculum, request explanations, or explore specific topics from all books in this curriculum.
                                </p>
                              </div>
                            </div>
                          ) : (
                            <div className="space-y-6">
                              {messages.map((message) => (
                                <div
                                  key={message.id}
                                  className={cn(
                                    'flex gap-3',
                                    message.type === 'user' ? 'justify-end' : 'justify-start'
                                  )}
                                >
                                  <div
                                    className={cn(
                                      'max-w-[85%] rounded-lg px-4 py-3 break-words',
                                      message.type === 'user'
                                        ? 'bg-primary text-primary-foreground'
                                        : 'bg-muted border'
                                    )}
                                  >
                                    <p className="whitespace-pre-wrap break-words overflow-wrap-anywhere">{message.content}</p>
                                    {message.metadata && (
                                      <div className="mt-2 flex items-center gap-1 text-xs opacity-75">
                                        <ExternalLink className="w-3 h-3" />
                                        <span>Contains external information</span>
                                      </div>
                                    )}
                                    <div className="text-xs opacity-50 mt-2">
                                      {message.timestamp.toLocaleTimeString()}
                                    </div>
                                  </div>
                                </div>
                              ))}
                              
                              {isLoading && (
                                <div className="flex gap-3">
                                  <div className="max-w-[85%] rounded-lg px-4 py-3 bg-muted border">
                                    <div className="flex items-center gap-2">
                                      <div className="flex gap-1">
                                        <div className="w-2 h-2 bg-primary rounded-full animate-pulse"></div>
                                        <div className="w-2 h-2 bg-primary rounded-full animate-pulse delay-75"></div>
                                        <div className="w-2 h-2 bg-primary rounded-full animate-pulse delay-150"></div>
                                      </div>
                                      <span className="text-sm text-muted-foreground">AI is thinking...</span>
                                    </div>
                                  </div>
                                </div>
                              )}
                              
                              <div ref={messagesEndRef} />
                            </div>
                          )}
                        </div>
                      </ScrollArea>
                    </div>
                    
                    {/* Input Area */}
                    <div className="border-t p-4 shrink-0">
                      
                      <div className="flex gap-3">
                        <Textarea
                          ref={textareaRef}
                          value={currentMessage}
                          onChange={(e) => setCurrentMessage(e.target.value)}
                          onKeyDown={handleKeyPress}
                          placeholder="Ask a question about the book..."
                          className="min-h-[60px] resize-none"
                          disabled={isLoading}
                        />
                        <Button
                          onClick={handleSendMessage}
                          disabled={!currentMessage.trim() || isLoading}
                          className="px-6"
                        >
                          {isLoading ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Send className="w-4 h-4" />
                          )}
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
