import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Header } from '@/components/ui/header';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Clock, CheckCircle, XCircle, RotateCcw, Home, Loader2, AlertCircle } from 'lucide-react';
import { ChatService } from '@/lib/services';
import type { Question as QuestionType, QuestionGenerationRequest } from '@/lib/types';

interface ExamQuestion extends QuestionType {
  id: string;
  userAnswer?: string;
  points: number;
}

interface ExamData {
  id: string;
  title: string;
  book: string;
  difficulty: string;
  timeLimit: number;
  questions: ExamQuestion[];
}

export default function Exam() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  
  // Get exam configuration from URL params
  const bookTitle = searchParams.get('book');
  const questionCount = parseInt(searchParams.get('questionCount') || '10');
  const timeLimit = parseInt(searchParams.get('timeLimit') || '30');
  const questionTypes = searchParams.get('questionTypes')?.split(',') || ['multiple_choice_single_answer'];
  const difficulty = searchParams.get('difficulty')?.split(',') || ['medium'];

  const [examData, setExamData] = useState<ExamData | null>(null);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [timeRemaining, setTimeRemaining] = useState(timeLimit * 60);
  const [isCompleted, setIsCompleted] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const [isLoadingQuestions, setIsLoadingQuestions] = useState(true);
  const [error, setError] = useState('');

  const currentQuestion = examData?.questions[currentQuestionIndex];
  const progress = examData ? ((currentQuestionIndex + 1) / examData.questions.length) * 100 : 0;

  // Generate questions on component mount
  useEffect(() => {
    if (!bookTitle) {
      setError('No book selected for exam');
      setIsLoadingQuestions(false);
      return;
    }
    generateExamQuestions();
  }, [bookTitle]);

  // Timer effect
  useEffect(() => {
    if (timeRemaining > 0 && !isCompleted && examData) {
      const timer = setTimeout(() => setTimeRemaining(timeRemaining - 1), 1000);
      return () => clearTimeout(timer);
    } else if (timeRemaining === 0 && examData) {
      handleSubmitExam();
    }
  }, [timeRemaining, isCompleted, examData]);

  const generateExamQuestions = async () => {
    if (!bookTitle) return;

    try {
      setIsLoadingQuestions(true);
      setError('');

      const request: QuestionGenerationRequest = {
        book_title: decodeURIComponent(bookTitle),
        user_message: `Generate ${questionCount} exam questions with various difficulty levels and types`,
        count: questionCount,
        difficulty: difficulty,
        question_types: questionTypes
      };

      const response = await ChatService.generateQuestions(request);
      
      // Convert API questions to exam format
      const examQuestions: ExamQuestion[] = response.questions_generated.map((q, index) => ({
        id: `q${index + 1}`,
        difficulty: q.difficulty,
        type: q.type,
        question_text: q.question_text,
        options: q.options,
        answer: q.answer,
        points: getPointsForType(q.type, q.difficulty)
      }));

      const exam: ExamData = {
        id: `exam_${Date.now()}`,
        title: `${decodeURIComponent(bookTitle)} Exam`,
        book: decodeURIComponent(bookTitle),
        difficulty: difficulty.join(', '),
        timeLimit: timeLimit,
        questions: examQuestions
      };

      setExamData(exam);
    } catch (err) {
      console.error('Error generating questions:', err);
      setError(err instanceof Error ? err.message : 'Failed to generate exam questions');
    } finally {
      setIsLoadingQuestions(false);
    }
  };

  const getPointsForType = (type: string, difficulty: string): number => {
    const basePoints = {
      'multiple_choice_single_answer': 3,
      'true_false': 2,
      'open_ended_question': 5
    };
    
    const multiplier = {
      'easy': 1,
      'medium': 1.5,
      'hard': 2
    };

    return Math.round((basePoints[type as keyof typeof basePoints] || 3) * (multiplier[difficulty as keyof typeof multiplier] || 1));
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const handleAnswerChange = (value: string) => {
    if (!currentQuestion) return;
    setAnswers(prev => ({
      ...prev,
      [currentQuestion.id]: value
    }));
  };

  const handleNext = () => {
    if (!examData) return;
    if (currentQuestionIndex < examData.questions.length - 1) {
      setCurrentQuestionIndex(currentQuestionIndex + 1);
    } else {
      handleSubmitExam();
    }
  };

  const handlePrevious = () => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex(currentQuestionIndex - 1);
    }
  };

  const handleSubmitExam = () => {
    setIsCompleted(true);
    setShowResults(true);
  };

  const calculateScore = () => {
    if (!examData) return { earned: 0, total: 0 };

    let totalPoints = 0;
    let earnedPoints = 0;

    examData.questions.forEach(question => {
      totalPoints += question.points;
      const userAnswer = answers[question.id];
      
      if (question.type === 'multiple_choice_single_answer' || question.type === 'true_false') {
        if (userAnswer === question.answer) {
          earnedPoints += question.points;
        }
      } else {
        // For open-ended questions, give partial credit for demo
        if (userAnswer && userAnswer.length > 10) {
          earnedPoints += Math.floor(question.points * 0.8);
        }
      }
    });

    return { earned: earnedPoints, total: totalPoints };
  };

  const retryExam = () => {
    setCurrentQuestionIndex(0);
    setAnswers({});
    setTimeRemaining(timeLimit * 60);
    setIsCompleted(false);
    setShowResults(false);
    generateExamQuestions();
  };

  // Loading state
  if (isLoadingQuestions) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
        <Header />
        <div className="container mx-auto px-4 py-8">
          <div className="max-w-4xl mx-auto">
            <Card className="text-center">
              <CardContent className="pt-6">
                <Loader2 className="w-12 h-12 animate-spin mx-auto mb-4" />
                <h2 className="text-xl font-semibold mb-2">Generating Your Exam</h2>
                <p className="text-muted-foreground">Please wait while we create your personalized questions...</p>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    );
  }

  // Error state
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
              <Button onClick={() => navigate('/exam-setup')}>
                Return to Exam Setup
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (showResults) {
    const score = calculateScore();
    const percentage = Math.round((score.earned / score.total) * 100);

    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
        <Header />
        
        <div className="container mx-auto px-4 py-8">
          <div className="max-w-4xl mx-auto">
            <Card className="text-center">
              <CardHeader>
                <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-gradient-to-br from-primary to-secondary flex items-center justify-center">
                  <CheckCircle className="w-10 h-10 text-white" />
                </div>
                <CardTitle className="text-2xl">Exam Completed!</CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="p-4 bg-primary/5 rounded-lg">
                    <div className="text-2xl font-bold text-primary">{score.earned}/{score.total}</div>
                    <div className="text-sm text-muted-foreground">Points Earned</div>
                  </div>
                  <div className="p-4 bg-secondary/5 rounded-lg">
                    <div className="text-2xl font-bold text-secondary">{percentage}%</div>
                    <div className="text-sm text-muted-foreground">Overall Score</div>
                  </div>
                  <div className="p-4 bg-accent/5 rounded-lg">
                    <div className="text-2xl font-bold text-accent">{formatTime(examData.timeLimit * 60 - timeRemaining)}</div>
                    <div className="text-sm text-muted-foreground">Time Taken</div>
                  </div>
                </div>

                <div className="space-y-4">
                  <h3 className="text-lg font-semibold">Review Your Answers</h3>
                  {examData.questions.map((question, index) => (
                    <div key={question.id} className="text-left p-4 border rounded-lg">
                      <div className="flex items-start justify-between mb-2">
                        <h4 className="font-medium">Question {index + 1}</h4>
                        <Badge variant={answers[question.id] === question.answer ? "default" : "destructive"}>
                          {question.points} pts
                        </Badge>
                      </div>
                      <p className="mb-3 text-sm">{question.question_text}</p>
                      <div className="space-y-2 text-sm">
                        <div>
                          <span className="font-medium">Your answer: </span>
                          <span className={answers[question.id] === question.answer ? "text-green-600" : "text-red-600"}>
                            {answers[question.id] || "No answer provided"}
                          </span>
                        </div>
                        {(question.type === 'multiple_choice_single_answer' || question.type === 'true_false') && (
                          <div>
                            <span className="font-medium">Correct answer: </span>
                            <span className="text-green-600">{question.answer}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex gap-4 justify-center">
                  <Button onClick={retryExam} variant="outline">
                    <RotateCcw className="w-4 h-4 mr-2" />
                    Try Again
                  </Button>
                  <Button onClick={() => navigate('/')}>
                    <Home className="w-4 h-4 mr-2" />
                    Return to Dashboard
                  </Button>
                </div>
              </CardContent>
            </Card>
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
          {/* Exam Header */}
          <Card className="mb-6">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>{examData.title}</CardTitle>
                  <p className="text-muted-foreground">Book: {examData.book}</p>
                </div>
                <div className="flex items-center gap-4">
                  <Badge variant="secondary">{examData.difficulty}</Badge>
                  <div className="flex items-center gap-2 text-sm">
                    <Clock className="w-4 h-4" />
                    <span className={timeRemaining < 300 ? "text-red-500 font-bold" : ""}>
                      {formatTime(timeRemaining)}
                    </span>
                  </div>
                </div>
              </div>
              <div className="mt-4">
                <div className="flex items-center justify-between text-sm mb-2">
                  <span>Question {currentQuestionIndex + 1} of {examData.questions.length}</span>
                  <span>{Math.round(progress)}% Complete</span>
                </div>
                <Progress value={progress} className="h-2" />
              </div>
            </CardHeader>
          </Card>

          {/* Question Card */}
          {currentQuestion && (
            <Card className="mb-6">
              <CardHeader>
                <CardTitle className="text-lg">
                  Question {currentQuestionIndex + 1}
                  <Badge variant="outline" className="ml-2">{currentQuestion.points} points</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                <p className="text-lg">{currentQuestion.question_text}</p>

                {/* Answer Input Based on Question Type */}
                {currentQuestion.type === 'multiple_choice_single_answer' && (
                  <RadioGroup
                    value={answers[currentQuestion.id] || ''}
                    onValueChange={handleAnswerChange}
                  >
                    {currentQuestion.options?.map((option, index) => (
                      <div key={index} className="flex items-center space-x-2">
                        <RadioGroupItem value={option} id={`option-${index}`} />
                        <Label htmlFor={`option-${index}`} className="cursor-pointer">
                          {option}
                        </Label>
                      </div>
                    ))}
                  </RadioGroup>
                )}

                {currentQuestion.type === 'true_false' && (
                  <RadioGroup
                    value={answers[currentQuestion.id] || ''}
                    onValueChange={handleAnswerChange}
                  >
                    <div className="flex items-center space-x-2">
                      <RadioGroupItem value="True" id="true" />
                      <Label htmlFor="true" className="cursor-pointer">True</Label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <RadioGroupItem value="False" id="false" />
                      <Label htmlFor="false" className="cursor-pointer">False</Label>
                    </div>
                  </RadioGroup>
                )}

                {currentQuestion.type === 'open_ended_question' && (
                  <Textarea
                    value={answers[currentQuestion.id] || ''}
                    onChange={(e) => handleAnswerChange(e.target.value)}
                    placeholder="Type your answer here..."
                    className="min-h-[120px]"
                  />
                )}

                {/* Navigation Buttons */}
                <div className="flex justify-between pt-4">
                  <Button
                    variant="outline"
                    onClick={handlePrevious}
                    disabled={currentQuestionIndex === 0}
                  >
                    Previous
                  </Button>
                  
                  <div className="flex gap-2">
                    {currentQuestionIndex === examData.questions.length - 1 ? (
                      <Button onClick={handleSubmitExam} className="bg-green-600 hover:bg-green-700">
                        Submit Exam
                      </Button>
                    ) : (
                      <Button onClick={handleNext}>
                        Next Question
                      </Button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}