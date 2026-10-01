import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Header } from '@/components/ui/header';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Clock, BookOpen, Play, Download, Printer, Copy, AlertCircle, Loader2 } from 'lucide-react';
import { ChatService } from '@/lib/services';
import type { QuestionGenerationRequest, Question, QuestionResponse } from '@/lib/types';

interface ExamQuestion {
  id: string;
  type: string;
  question_text: string;
  options?: string[];
  answer: string;
  points: number;
}

interface ExamData {
  id: string;
  title: string;
  book: string;
  difficulty: string;
  timeLimit: number;
  totalQuestions: number;
  totalPoints: number;
  questions: ExamQuestion[];
  createdAt: Date;
}

export default function ExamView() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [examData, setExamData] = useState<ExamData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  
  // Get exam parameters from URL with memoization to prevent re-renders
  const curriculumId = searchParams.get('curriculumId');
  const bookTitle = searchParams.get('book');
  const questionCount = parseInt(searchParams.get('questionCount') || '10');
  const timeLimit = parseInt(searchParams.get('timeLimit') || '30');
  const scopeType = searchParams.get('scopeType') || 'whole_book';
  const specificTopics = searchParams.get('topics') || '';
  
  // Memoize arrays to prevent dependency changes on every render
  const difficulty = useMemo(() => 
    searchParams.get('difficulty')?.split(',') || ['medium'], 
    [searchParams.get('difficulty')]
  );
  
  const questionTypes = useMemo(() => 
    searchParams.get('questionTypes')?.split(',') || ['multiple_choice_single_answer'], 
    [searchParams.get('questionTypes')]
  );

  const generateExamPreview = useCallback(async () => {
    try {
      setIsLoading(true);
      setError('');

      // Build comprehensive user message based on all parameters
      let userMessage = `Generate ${questionCount} exam questions`;
      
      if (difficulty.length > 0) {
        userMessage += ` with ${difficulty.join(', ')} difficulty level${difficulty.length > 1 ? 's' : ''}`;
      }
      
      if (timeLimit) {
        userMessage += ` for a ${timeLimit}-minute exam`;
      }
      
      if (scopeType === 'whole_curriculum') {
        userMessage += ` covering the entire curriculum content`;
      } else if (scopeType === 'specific_topics' && specificTopics) {
        userMessage += ` focusing specifically on: ${specificTopics}`;
      } else {
        userMessage += ` covering the entire book content`;
      }

      const request: QuestionGenerationRequest = {
        book_title: bookTitle || '',
        curriculum_id: curriculumId || '',
        user_message: userMessage,
        count: questionCount,
        difficulty: difficulty,
        question_types: questionTypes,
        // Additional parameters for enhanced generation
        scope_type: scopeType as 'whole_curriculum' | 'whole_book' | 'specific_topics',
        specific_topics: specificTopics,
        time_limit: timeLimit
      };

      console.log('Generating exam with comprehensive parameters:', request);
      
      const response = await ChatService.generateQuestions(request);
      
      if (!response.questions_generated || response.questions_generated.length === 0) {
        throw new Error('No questions were generated');
      }

      // Transform API questions to exam format
      const examQuestions: ExamQuestion[] = response.questions_generated.map((q: Question, index: number) => ({
        id: `q_${index + 1}`,
        type: q.type,
        question_text: q.question_text,
        options: q.options,
        answer: q.answer,
        points: getPointsForQuestionType(q.type)
      }));

      const totalPoints = examQuestions.reduce((sum, q) => sum + q.points, 0);

      const exam: ExamData = {
        id: `exam_${Date.now()}`,
        title: `${bookTitle} - ${difficulty.join('/')} Level Exam`,
        book: bookTitle!,
        difficulty: difficulty.join(', '),
        timeLimit: timeLimit,
        totalQuestions: examQuestions.length,
        totalPoints: totalPoints,
        questions: examQuestions,
        createdAt: new Date()
      };

      setExamData(exam);
      console.log('Generated exam:', exam);
      
    } catch (err) {
      console.error('Error generating exam preview:', err);
      setError(err instanceof Error ? err.message : 'Failed to generate exam preview');
    } finally {
      setIsLoading(false);
    }
  }, [bookTitle, questionCount, timeLimit, difficulty, questionTypes, scopeType, specificTopics]);

  useEffect(() => {
    if (bookTitle) {
      generateExamPreview();
    } else {
      setError('No book selected for exam generation');
      setIsLoading(false);
    }
  }, [bookTitle, generateExamPreview]);

  const getPointsForQuestionType = (type: string): number => {
    switch (type) {
      case 'multiple_choice_single_answer': return 2;
      case 'true_false': return 1;
      case 'open_ended_question': return 5;
      default: return 2;
    }
  };

  const getDifficultyColor = (difficulty: string) => {
    switch (difficulty.toLowerCase()) {
      case 'easy': return 'bg-green-100 text-green-800';
      case 'medium': return 'bg-yellow-100 text-yellow-800';
      case 'hard': return 'bg-red-100 text-red-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getQuestionTypeLabel = (type: string) => {
    switch (type) {
      case 'multiple_choice_single_answer': return 'Multiple Choice';
      case 'true_false': return 'True/False';
      case 'open_ended_question': return 'Open Ended';
      default: return type;
    }
  };

  const handleTakeExam = () => {
    if (!examData) return;
    
    const examParams = new URLSearchParams({
      book: encodeURIComponent(examData.book),
      questionCount: examData.totalQuestions.toString(),
      timeLimit: examData.timeLimit.toString(),
      questionTypes: questionTypes.join(','),
      difficulty: difficulty.join(',')
    });
    
    navigate(`/exam?${examParams.toString()}`);
  };

  const handlePrintExam = () => {
    if (!examData) return;
    
    const printContent = `
      ${examData.title}
      
      Instructions:
      - Time Limit: ${examData.timeLimit} minutes
      - Total Questions: ${examData.totalQuestions}
      - Total Points: ${examData.totalPoints}
      
      Questions:
      ${examData.questions.map((q, i) => 
        `${i + 1}. ${q.question_text}${q.options ? '\n' + q.options.map((opt, j) => `   ${String.fromCharCode(97 + j)}) ${opt}`).join('\n') : ''}\n`
      ).join('\n')}
    `;
    
    const printWindow = window.open('', '_blank');
    if (printWindow) {
      printWindow.document.write(`
        <html>
          <head><title>${examData.title}</title></head>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; padding: 20px;">
            <pre style="white-space: pre-wrap;">${printContent}</pre>
          </body>
        </html>
      `);
      printWindow.document.close();
      printWindow.print();
    }
  };

  const handleDownloadExam = () => {
    if (!examData) return;
    
    const examContent = `
      ${examData.title}
      Generated: ${examData.createdAt.toLocaleString()}
      
      Book: ${examData.book}
      Difficulty: ${examData.difficulty}
      Time Limit: ${examData.timeLimit} minutes
      Total Questions: ${examData.totalQuestions}
      Total Points: ${examData.totalPoints}
      
      QUESTIONS:
      ${examData.questions.map((q, i) => `
        Question ${i + 1} [${q.points} points] - ${getQuestionTypeLabel(q.type)}
        ${q.question_text}
        ${q.options ? q.options.map((opt, j) => `${String.fromCharCode(65 + j)}. ${opt}`).join('\n') : ''}
        Answer: ${q.answer}
      `).join('\n\n')}
    `;
    
    const blob = new Blob([examContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${examData.title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
        <Header />
        <div className="container mx-auto px-4 py-8">
          <div className="max-w-4xl mx-auto">
            <Card className="text-center">
              <CardContent className="pt-6">
                <Loader2 className="w-12 h-12 animate-spin mx-auto mb-4" />
                <h2 className="text-xl font-semibold mb-2">Generating Exam Preview</h2>
                <p className="text-muted-foreground">Please wait while we prepare your exam...</p>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    );
  }

  if (error || !examData) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
        <Header />
        <div className="container mx-auto px-4 py-8">
          <div className="max-w-4xl mx-auto">
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error || 'Failed to load exam data'}</AlertDescription>
            </Alert>
            <div className="text-center mt-6">
              <Button onClick={() => navigate('/exams')}>
                Return to Exam Generator
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
      <Header />
      
      <div className="container mx-auto px-4 py-8">
        <div className="max-w-4xl mx-auto">
          {/* Back Button */}
          <div className="mb-6">
            <Button 
              variant="outline" 
              onClick={() => navigate('/exams')}
              className="flex items-center gap-2"
            >
              ← Back to Exam Generator
            </Button>
          </div>

          {/* Exam Header */}
          <Card className="mb-6">
            <CardHeader>
              <div className="flex items-start justify-between">
                <div className="space-y-2">
                  <CardTitle className="text-2xl">{examData.title}</CardTitle>
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <BookOpen className="w-4 h-4" />
                    <span>{examData.book}</span>
                  </div>
                </div>
                <div className="text-right space-y-2">
                  <Badge className={getDifficultyColor(examData.difficulty)}>
                    {examData.difficulty}
                  </Badge>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Clock className="w-4 h-4" />
                    <span>{examData.timeLimit} minutes</span>
                  </div>
                </div>
              </div>
              
              <Separator className="my-4" />
              
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                <div>
                  <div className="text-2xl font-bold text-primary">{examData.totalQuestions}</div>
                  <div className="text-sm text-muted-foreground">Questions</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-accent">{examData.totalPoints}</div>
                  <div className="text-sm text-muted-foreground">Total Points</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-secondary">{examData.timeLimit}m</div>
                  <div className="text-sm text-muted-foreground">Time Limit</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-success">
                    {Math.round(examData.timeLimit / examData.totalQuestions)}m
                  </div>
                  <div className="text-sm text-muted-foreground">Per Question</div>
                </div>
              </div>
            </CardHeader>
          </Card>

          {/* Action Buttons */}
          <Card className="mb-6">
            <CardContent className="pt-6">
              <div className="grid md:grid-cols-4 gap-4">
                <Button 
                  onClick={handleTakeExam}
                  className="flex flex-col items-center gap-2 h-auto p-4"
                >
                  <Play className="w-6 h-6" />
                  <span>Take Exam</span>
                </Button>
                
                <Button 
                  variant="outline"
                  onClick={handlePrintExam}
                  className="flex flex-col items-center gap-2 h-auto p-4"
                >
                  <Printer className="w-6 h-6" />
                  <span>Print</span>
                </Button>
                
                <Button 
                  variant="outline"
                  onClick={handleDownloadExam}
                  className="flex flex-col items-center gap-2 h-auto p-4"
                >
                  <Download className="w-6 h-6" />
                  <span>Download</span>
                </Button>
                
                <Button 
                  variant="outline"
                  onClick={() => navigator.clipboard.writeText(examData.title)}
                  className="flex flex-col items-center gap-2 h-auto p-4"
                >
                  <Copy className="w-6 h-6" />
                  <span>Copy Link</span>
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Questions Preview */}
          <Card>
            <CardHeader>
              <CardTitle>Questions Preview</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {examData.questions.map((question, index) => (
                <div key={question.id} className="p-4 border rounded-lg">
                  <div className="flex items-start justify-between mb-3">
                    <h3 className="font-semibold">Question {index + 1}</h3>
                    <div className="flex gap-2">
                      <Badge variant="outline">
                        {getQuestionTypeLabel(question.type)}
                      </Badge>
                      <Badge variant="secondary">
                        {question.points} points
                      </Badge>
                    </div>
                  </div>
                  
                  <p className="text-base leading-relaxed mb-4">{question.question_text}</p>
                  
                  {question.options && question.options.length > 0 && (
                    <div className="space-y-2">
                      {question.options.map((option, optIndex) => (
                        <div key={optIndex} className="flex items-center gap-2 p-2 bg-muted/30 rounded">
                          <span className="font-medium text-sm">
                            {String.fromCharCode(65 + optIndex)}.
                          </span>
                          <span>{option}</span>
                          {option === question.answer && (
                            <Badge variant="default" className="ml-auto">
                              Correct
                            </Badge>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  
                  {question.type === 'true_false' && (
                    <div className="mt-3">
                      <div className="inline-flex items-center gap-2 px-3 py-1 bg-muted/30 rounded">
                        <span className="font-medium">Answer:</span>
                        <Badge variant="default">{question.answer}</Badge>
                      </div>
                    </div>
                  )}
                  
                  {question.type === 'open_ended_question' && (
                    <div className="mt-3 p-3 bg-muted/30 rounded">
                      <div className="font-medium text-sm mb-1">Sample Answer:</div>
                      <p className="text-sm text-muted-foreground">{question.answer}</p>
                    </div>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

