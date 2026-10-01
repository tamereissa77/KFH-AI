import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Header } from '@/components/ui/header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Send, FolderOpen, FileText, Download, Copy, Loader2, AlertCircle, Plus, MessageSquare, Target } from 'lucide-react';
import { cn, formatTitle } from '@/lib/utils';
import { BooksService, ChatService, SessionService, CurriculumService } from '@/lib/services';
import type { Book as BookType, ChatSession, ChatSource, Curriculum } from '@/lib/types';
import { useAuth } from '@/contexts/AuthContext';

interface Message {
  id: string;
  type: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  scope?: string;
  sources?: ChatSource[];
}

const ALL_DOCUMENTS = 'all';

function sourceLabel(source: ChatSource) {
  return source.page ? `${source.document}, p. ${source.page}` : source.document;
}

export default function Chat() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const curriculumParam = searchParams.get('curriculum');
  const documentParam = searchParams.get('document');
  const { user } = useAuth();

  const [curriculums, setCurriculums] = useState<Curriculum[]>([]);
  const [selectedCurriculum, setSelectedCurriculum] = useState<string>('');
  const [allBooks, setAllBooks] = useState<BookType[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<string>(ALL_DOCUMENTS);
  const [topic, setTopic] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentMessage, setCurrentMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingData, setIsLoadingData] = useState(true);
  const [error, setError] = useState('');
  const [currentSession, setCurrentSession] = useState<ChatSession | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const userId = user?.sub || '';

  const selectedCurriculumData = curriculums.find(curr => curr.id.toString() === selectedCurriculum);
  const documents = allBooks.filter(book => book.curriculum_id.toString() === selectedCurriculum);
  const selectedDocumentData = documents.find(book => book.id.toString() === selectedDocument);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    loadData();
  }, []);

  // Preselect a knowledge base from the URL (?curriculum=<name>)
  useEffect(() => {
    if (curriculumParam && curriculums.length > 0) {
      const curriculum = curriculums.find(c => c.name === decodeURIComponent(curriculumParam));
      if (curriculum) handleCurriculumChange(curriculum.id.toString());
    }
  }, [curriculumParam, curriculums]);

  // Preselect a document from the URL (?document=<id>), e.g. from a document card
  useEffect(() => {
    if (documentParam && allBooks.length > 0) {
      const doc = allBooks.find(b => b.id.toString() === documentParam);
      if (doc) {
        handleCurriculumChange(doc.curriculum_id.toString());
        setSelectedDocument(doc.id.toString());
      }
    }
  }, [documentParam, allBooks]);

  const loadData = async () => {
    try {
      setIsLoadingData(true);
      const [booksData, curriculumsData] = await Promise.all([
        BooksService.getBooks(),
        CurriculumService.getCurriculums()
      ]);
      setAllBooks(booksData);
      setCurriculums(curriculumsData);
    } catch (err) {
      console.error('Error loading data:', err);
      setError('Failed to load knowledge bases and documents');
    } finally {
      setIsLoadingData(false);
    }
  };

  const handleCurriculumChange = (curriculumId: string) => {
    setSelectedCurriculum(curriculumId);
    setSelectedDocument(ALL_DOCUMENTS);
    setMessages([]);
    setCurrentSession(null);
  };

  const describeScope = () => {
    const parts = [selectedDocumentData ? formatTitle(selectedDocumentData.title) : 'All documents'];
    if (topic.trim()) parts.push(`topic: ${topic.trim()}`);
    return parts.join(' · ');
  };

  const handleSendMessage = async () => {
    if (!currentMessage.trim() || !selectedCurriculumData || isLoading) return;
    const curriculum = selectedCurriculumData;

    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: currentMessage,
      timestamp: new Date(),
      scope: describeScope(),
    };

    setMessages(prev => [...prev, userMessage]);
    const messageToSend = currentMessage;
    setCurrentMessage('');
    setIsLoading(true);
    setError('');

    try {
      let sessionId = currentSession?.id || '';
      if (!currentSession) {
        const newSession = await SessionService.createSession(userId, curriculum.name, `Ask ${curriculum.name}`, true);
        setCurrentSession(newSession);
        sessionId = newSession.id;
      }

      const response = await ChatService.sendMessage({
        curriculum: curriculum.name,
        session_id: sessionId,
        user_message: messageToSend,
        intent: 'answer_question',
        book_id: selectedDocumentData ? selectedDocumentData.id : null,
        topic: topic.trim() || null,
      });

      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: response.response,
        timestamp: new Date(),
        sources: response.metadata?.sources || [],
      }]);
    } catch (err) {
      console.error('Error sending message:', err);
      setError(err instanceof Error ? err.message : 'Failed to send message');
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: 'Sorry, something went wrong while processing your question. Please try again.',
        timestamp: new Date(),
      }]);
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

  const transcript = () => messages.map(msg => {
    const who = msg.type === 'user' ? 'Question' : 'Answer';
    const sources = msg.sources?.length
      ? '\nSources:\n' + msg.sources.map(s => `[${s.n}] ${sourceLabel(s)}`).join('\n')
      : '';
    return `[${msg.timestamp.toLocaleTimeString()}] ${who}: ${msg.content}${sources}`;
  }).join('\n\n');

  const exportChat = () => {
    const blob = new Blob([transcript()], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `kfh-answers-${selectedCurriculumData?.name || 'conversation'}.txt`;
    a.click();
  };

  const handleNewChat = () => {
    setCurrentSession(null);
    setMessages([]);
    setError('');
  };

  if (isLoadingData) {
    return (
      <div className="min-h-screen bg-background">
        <Header />
        <div className="flex items-center justify-center h-64">
          <div className="text-center">
            <Loader2 className="w-8 h-8 animate-spin mx-auto mb-4 text-primary" />
            <p className="text-muted-foreground">Loading knowledge bases...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <Header />

      <div className="container mx-auto px-4 py-8">
        <div className="max-w-5xl mx-auto">
          <div className="mb-6">
            <h1 className="text-3xl font-bold mb-2">Ask the documents</h1>
            <p className="text-muted-foreground">
              Answers come only from the documents in the selected knowledge base, with sources cited.
            </p>
          </div>

          {curriculums.length === 0 || allBooks.length === 0 ? (
            <Card>
              <CardContent className="py-10 text-center">
                <FolderOpen className="w-14 h-14 text-muted-foreground mx-auto mb-4" />
                <h3 className="text-lg font-semibold mb-2">No documents yet</h3>
                <p className="text-muted-foreground mb-4">
                  Create a knowledge base and upload documents before asking questions.
                </p>
                <Button onClick={() => navigate('/books/add')}>Upload documents</Button>
              </CardContent>
            </Card>
          ) : (
            <div className="grid lg:grid-cols-[300px_1fr] gap-6">
              {/* Scope */}
              <Card className="h-fit">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">What to search</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <label className="text-sm font-medium mb-1.5 flex items-center gap-1.5">
                      <FolderOpen className="w-4 h-4 text-primary" /> Knowledge base
                    </label>
                    <Select value={selectedCurriculum} onValueChange={handleCurriculumChange}>
                      <SelectTrigger>
                        <SelectValue placeholder="Choose a knowledge base" />
                      </SelectTrigger>
                      <SelectContent>
                        {curriculums.map((curriculum) => (
                          <SelectItem key={curriculum.id} value={curriculum.id.toString()}>
                            {curriculum.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {selectedCurriculumData?.description && (
                      <p className="text-xs text-muted-foreground mt-1.5">{selectedCurriculumData.description}</p>
                    )}
                  </div>

                  {selectedCurriculumData && (
                    <>
                      <div>
                        <label className="text-sm font-medium mb-1.5 flex items-center gap-1.5">
                          <FileText className="w-4 h-4 text-primary" /> Document
                        </label>
                        <Select value={selectedDocument} onValueChange={setSelectedDocument}>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={ALL_DOCUMENTS}>All documents ({documents.length})</SelectItem>
                            {documents.map((doc) => (
                              <SelectItem key={doc.id} value={doc.id.toString()}>
                                {formatTitle(doc.title)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      <div>
                        <label htmlFor="topic" className="text-sm font-medium mb-1.5 flex items-center gap-1.5">
                          <Target className="w-4 h-4 text-primary" /> Specific point or topic
                          <span className="text-muted-foreground font-normal">(optional)</span>
                        </label>
                        <Input
                          id="topic"
                          value={topic}
                          onChange={(e) => setTopic(e.target.value)}
                          placeholder="e.g. Murabaha early settlement"
                          dir="auto"
                        />
                        <p className="text-xs text-muted-foreground mt-1.5">
                          Focuses the search on this point for every question you ask.
                        </p>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>

              {/* Conversation */}
              <Card className="flex flex-col h-[calc(100vh-14rem)] min-h-[480px]">
                <CardHeader className="border-b py-3 shrink-0">
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="text-base truncate">
                      {selectedCurriculumData ? selectedCurriculumData.name : 'Conversation'}
                    </CardTitle>
                    <div className="flex gap-2 shrink-0">
                      <Button variant="outline" size="sm" onClick={handleNewChat}>
                        <Plus className="w-4 h-4 mr-1" /> New
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => navigator.clipboard.writeText(transcript())} disabled={messages.length === 0}>
                        <Copy className="w-4 h-4" />
                      </Button>
                      <Button variant="outline" size="sm" onClick={exportChat} disabled={messages.length === 0}>
                        <Download className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="flex-1 flex flex-col p-0 min-h-0">
                  <ScrollArea className="flex-1">
                    <div className="p-5">
                      {!selectedCurriculumData ? (
                        <div className="flex flex-col items-center justify-center h-64 text-center text-muted-foreground">
                          <FolderOpen className="w-10 h-10 mb-3" />
                          Choose a knowledge base to start.
                        </div>
                      ) : messages.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-64 text-center">
                          <MessageSquare className="w-10 h-10 text-primary mb-3" />
                          <h3 className="text-lg font-semibold">Ask a question</h3>
                          <p className="text-muted-foreground max-w-md">
                            For example: "What is the approval limit for personal finance?" or
                            "ما هي المستندات المطلوبة لفتح حساب؟"
                          </p>
                        </div>
                      ) : (
                        <div className="space-y-5">
                          {messages.map((message) => (
                            <div key={message.id} className={cn('flex', message.type === 'user' ? 'justify-end' : 'justify-start')}>
                              <div className={cn(
                                'max-w-[88%] rounded-lg px-4 py-3 break-words',
                                message.type === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted border'
                              )}>
                                {message.type === 'user' ? (
                                  <>
                                    <p className="whitespace-pre-wrap" dir="auto">{message.content}</p>
                                    {message.scope && (
                                      <div className="text-xs opacity-75 mt-1.5">{message.scope}</div>
                                    )}
                                  </>
                                ) : (
                                  <>
                                    <div className="prose prose-sm max-w-none dark:prose-invert prose-p:my-1.5 prose-ul:my-1.5 prose-li:my-0.5" dir="auto">
                                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                                    </div>
                                    {message.sources && message.sources.length > 0 && (
                                      <div className="mt-3 pt-2 border-t space-y-1">
                                        <div className="text-xs font-medium text-muted-foreground">Sources</div>
                                        {message.sources.map((source) => (
                                          <details key={source.n} className="text-xs group">
                                            <summary className="cursor-pointer text-muted-foreground hover:text-foreground list-none">
                                              <Badge variant="outline" className="mr-1.5 px-1.5 py-0 text-[10px]">{source.n}</Badge>
                                              {sourceLabel(source)}
                                            </summary>
                                            <p className="mt-1 ml-7 text-muted-foreground italic" dir="auto">"{source.excerpt}…"</p>
                                          </details>
                                        ))}
                                      </div>
                                    )}
                                  </>
                                )}
                                <div className="text-[11px] opacity-50 mt-2">{message.timestamp.toLocaleTimeString()}</div>
                              </div>
                            </div>
                          ))}

                          {isLoading && (
                            <div className="flex">
                              <div className="rounded-lg px-4 py-3 bg-muted border flex items-center gap-2">
                                <Loader2 className="w-4 h-4 animate-spin text-primary" />
                                <span className="text-sm text-muted-foreground">Searching documents...</span>
                              </div>
                            </div>
                          )}
                          <div ref={messagesEndRef} />
                        </div>
                      )}
                    </div>
                  </ScrollArea>

                  {error && (
                    <Alert variant="destructive" className="mx-4 mb-2 w-auto">
                      <AlertCircle className="w-4 h-4" />
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}

                  <div className="border-t p-4 shrink-0">
                    <div className="flex gap-3">
                      <Textarea
                        value={currentMessage}
                        onChange={(e) => setCurrentMessage(e.target.value)}
                        onKeyDown={handleKeyPress}
                        placeholder={selectedCurriculumData ? `Ask about ${describeScope()}...` : 'Choose a knowledge base first'}
                        className="min-h-[56px] resize-none"
                        disabled={isLoading || !selectedCurriculumData}
                        dir="auto"
                      />
                      <Button onClick={handleSendMessage} disabled={!currentMessage.trim() || isLoading || !selectedCurriculumData} className="px-5 self-end h-[56px]">
                        {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
