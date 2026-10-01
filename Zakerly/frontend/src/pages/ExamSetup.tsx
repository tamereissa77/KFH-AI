import React, { useState, useEffect } from 'react';
import { formatTitle } from '@/lib/utils';
import { useParams, useNavigate } from 'react-router-dom';
import { Header } from '@/components/ui/header';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { BookOpen, Settings, Loader2, GraduationCap, FileText } from 'lucide-react';
import { BooksService, CurriculumService } from '@/lib/services';
import type { Book as BookType, Curriculum } from '@/lib/types';

interface ExamSetupConfig {
  curriculumId: string;
  bookTitle: string;
  questionCount: number;
  timeLimit: number;
  difficulty: string[];
  questionTypes: string[];
  scopeType: 'whole_curriculum' | 'whole_book' | 'specific_topics';
  specificTopics: string;
}

const difficultyOptions = [
  { id: 'easy', label: 'Easy', description: 'Basic understanding questions' },
  { id: 'medium', label: 'Medium', description: 'Moderate complexity questions' },
  { id: 'hard', label: 'Hard', description: 'Advanced analysis questions' }
];

const questionTypeOptions = [
  { id: 'multiple_choice_single_answer', label: 'Multiple Choice', description: 'Questions with 4 options' },
  { id: 'true_false', label: 'True/False', description: 'Binary choice questions' },
  { id: 'open_ended_question', label: 'Open Ended', description: 'Detailed written answers' }
];

export default function ExamSetup() {
  const { bookTitle } = useParams<{ bookTitle: string }>();
  const navigate = useNavigate();
  
  // State for curriculums and books
  const [curriculums, setCurriculums] = useState<Curriculum[]>([]);
  const [books, setBooks] = useState<BookType[]>([]);
  const [allBooks, setAllBooks] = useState<BookType[]>([]);
  const [isLoadingBooks, setIsLoadingBooks] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState('');
  
  const [examConfig, setExamConfig] = useState<ExamSetupConfig>({
    curriculumId: '',
    bookTitle: bookTitle || '',
    questionCount: 10,
    timeLimit: 30,
    difficulty: ['medium'],
    questionTypes: ['multiple_choice_single_answer'],
    scopeType: 'whole_curriculum',
    specificTopics: ''
  });

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setIsLoadingBooks(true);
      const [booksData, curriculumsData] = await Promise.all([
        BooksService.getBooks(),
        CurriculumService.getCurriculums()
      ]);
      setAllBooks(booksData);
      setBooks(booksData);
      setCurriculums(curriculumsData);
    } catch (err) {
      console.error('Error loading data:', err);
      setError('Failed to load documents and knowledge bases');
    } finally {
      setIsLoadingBooks(false);
    }
  };

  const handleCurriculumChange = (curriculumId: string) => {
    setExamConfig(prev => ({ 
      ...prev, 
      curriculumId, 
      bookTitle: '',
      scopeType: 'whole_curriculum' // Reset to curriculum by default
    }));
    
    if (curriculumId) {
      const filteredBooks = allBooks.filter(book => book.curriculum_id.toString() === curriculumId);
      setBooks(filteredBooks);
    } else {
      setBooks(allBooks);
    }
  };

  const handleBookChange = (bookTitle: string) => {
    setExamConfig(prev => ({ ...prev, bookTitle }));
  };

  const handleDifficultyChange = (difficulty: string, checked: boolean) => {
    setExamConfig(prev => ({
      ...prev,
      difficulty: checked 
        ? [...prev.difficulty, difficulty]
        : prev.difficulty.filter(d => d !== difficulty)
    }));
  };

  const handleQuestionTypeChange = (type: string, checked: boolean) => {
    setExamConfig(prev => ({
      ...prev,
      questionTypes: checked
        ? [...prev.questionTypes, type]
        : prev.questionTypes.filter(t => t !== type)
    }));
  };

  const handleScopeChange = (scope: 'whole_curriculum' | 'whole_book' | 'specific_topics') => {
    setExamConfig(prev => ({
      ...prev,
      scopeType: scope,
      bookTitle: scope === 'whole_curriculum' ? '' : prev.bookTitle,
      specificTopics: (scope === 'whole_curriculum' || scope === 'whole_book') ? '' : prev.specificTopics
    }));
  };

  const handleGenerateExam = () => {
    // Validate required fields
    if (!examConfig.curriculumId) {
      setError('Please select a knowledge base');
      return;
    }
    
    if (examConfig.scopeType !== 'whole_curriculum' && !examConfig.bookTitle) {
      setError('Please select a document');
      return;
    }
    
    if (examConfig.difficulty.length === 0) {
      setError('Please select at least one difficulty level');
      return;
    }
    
    if (examConfig.questionTypes.length === 0) {
      setError('Please select at least one question type');
      return;
    }

    if (examConfig.scopeType === 'specific_topics' && !examConfig.specificTopics.trim()) {
      setError('Please specify topics for the quiz');
      return;
    }

    setError('');
    setIsGenerating(true);

    // Navigate to ExamView with parameters
    const params = new URLSearchParams({
      curriculumId: examConfig.curriculumId,
      book: examConfig.bookTitle || 'Whole Knowledge Base',
      questionCount: examConfig.questionCount.toString(),
      timeLimit: examConfig.timeLimit.toString(),
      difficulty: examConfig.difficulty.join(','),
      questionTypes: examConfig.questionTypes.join(','),
      scopeType: examConfig.scopeType,
      topics: examConfig.specificTopics
    });

    navigate(`/exam-view?${params.toString()}`);
  };

  const selectedCurriculum = curriculums.find(c => c.id.toString() === examConfig.curriculumId);

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <div className="container mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3">
            <GraduationCap className="text-primary" size={32} />
            <div>
              <h1 className="text-3xl font-bold text-gray-900">Quiz Setup</h1>
              <p className="text-gray-600">
                Choose a knowledge base and configure your quiz settings
              </p>
            </div>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
            {error}
          </div>
        )}

        {/* Step 1: Curriculum Selection */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <GraduationCap className="w-5 h-5" />
              Step 1: Select Knowledge Base
            </CardTitle>
            <CardDescription>
              Choose the knowledge base that contains the content for your quiz
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Knowledge Base</Label>
                <Select 
                  value={examConfig.curriculumId} 
                  onValueChange={handleCurriculumChange}
                  disabled={isLoadingBooks}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a knowledge base" />
                  </SelectTrigger>
                  <SelectContent>
                    {curriculums.map((curriculum) => (
                      <SelectItem key={curriculum.id} value={curriculum.id.toString()}>
                        <div className="flex items-center gap-2">
                          <GraduationCap className="w-4 h-4" />
                          {curriculum.name}
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {selectedCurriculum && (
                <div className="p-4 bg-primary/5 rounded-lg border border-primary/20">
                  <div className="flex items-center gap-2 mb-2">
                    <GraduationCap className="w-5 h-5 text-primary" />
                    <h4 className="font-semibold text-primary-dark">{selectedCurriculum.name}</h4>
                  </div>
                  <p className="text-primary-dark text-sm mb-2">
                    {selectedCurriculum.description || 'Selected knowledge base'}
                  </p>
                  <div className="flex items-center gap-4 text-sm text-primary">
                    <span className="flex items-center gap-1">
                      <BookOpen className="w-4 h-4" />
                      {books.length} books available
                    </span>
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Step 2: Exam Scope Selection - Only show after curriculum is selected */}
        {examConfig.curriculumId && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Settings className="w-5 h-5" />
                Step 2: Choose Quiz Scope
              </CardTitle>
              <CardDescription>
                Decide what content to include in your quiz from the selected knowledge base
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <RadioGroup 
                  value={examConfig.scopeType} 
                  onValueChange={handleScopeChange}
                  className="space-y-4"
                >
                  {/* Whole Curriculum Option */}
                  <div className="flex items-start space-x-3 p-4 border-2 rounded-lg hover:bg-gray-50 transition-colors">
                    <RadioGroupItem value="whole_curriculum" id="whole_curriculum" className="mt-1" />
                    <Label htmlFor="whole_curriculum" className="cursor-pointer flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <GraduationCap className="w-5 h-5 text-primary" />
                        <div className="font-semibold text-lg">Whole Knowledge Base Quiz</div>
                      </div>
                      <div className="text-sm text-gray-600 mb-2">
                        Generate a comprehensive exam covering all {books.length} books in the curriculum
                      </div>
                      <div className="text-xs text-primary font-medium">
                        ✓ Recommended for comprehensive assessment across multiple subject areas
                      </div>
                    </Label>
                  </div>
                  
                  {/* Single Book Option */}
                  <div className="flex items-start space-x-3 p-4 border-2 rounded-lg hover:bg-gray-50 transition-colors">
                    <RadioGroupItem value="whole_book" id="whole_book" className="mt-1" />
                    <Label htmlFor="whole_book" className="cursor-pointer flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <BookOpen className="w-5 h-5 text-green-600" />
                        <div className="font-semibold text-lg">Single Document Quiz</div>
                      </div>
                      <div className="text-sm text-gray-600 mb-2">
                        Generate quiz focused on one specific document from the knowledge base
                      </div>
                      <div className="text-xs text-green-600 font-medium">
                        ✓ Perfect for testing knowledge of specific topics or subject areas
                      </div>
                    </Label>
                  </div>
                  
                  {/* Specific Topics Option */}
                  <div className="flex items-start space-x-3 p-4 border-2 rounded-lg hover:bg-gray-50 transition-colors">
                    <RadioGroupItem value="specific_topics" id="specific_topics" className="mt-1" />
                    <Label htmlFor="specific_topics" className="cursor-pointer flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <FileText className="w-5 h-5 text-accent" />
                        <div className="font-semibold text-lg">Specific Topics</div>
                      </div>
                      <div className="text-sm text-gray-600 mb-2">
                        Focus on particular topics, sections, or policies you specify
                      </div>
                      <div className="text-xs text-accent font-medium">
                        ✓ Ideal for targeted assessment of specific learning objectives
                      </div>
                    </Label>
                  </div>
                </RadioGroup>

                {/* Book Selection - Only show for single book and specific topics */}
                {(examConfig.scopeType === 'whole_book' || examConfig.scopeType === 'specific_topics') && (
                  <div className="space-y-2 mt-4">
                    <Label>Select Document</Label>
                    <Select 
                      value={examConfig.bookTitle} 
                      onValueChange={handleBookChange}
                      disabled={!examConfig.curriculumId || isLoadingBooks}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Choose a document from the knowledge base" />
                      </SelectTrigger>
                      <SelectContent>
                        {books.map((book) => (
                          <SelectItem key={book.id} value={book.title}>
                            <div className="flex items-center gap-2">
                              <BookOpen className="w-4 h-4" />
                              {formatTitle(book.title)}
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {/* Topics Input - Only show for specific topics */}
                {examConfig.scopeType === 'specific_topics' && (
                  <div className="space-y-2 mt-4">
                    <Label htmlFor="topics">Specify Topics</Label>
                    <Textarea
                      id="topics"
                      placeholder="Enter specific topics, sections, or policies you want to focus on..."
                      value={examConfig.specificTopics}
                      onChange={(e) => setExamConfig(prev => ({ ...prev, specificTopics: e.target.value }))}
                      className="min-h-[100px]"
                    />
                    <p className="text-sm text-gray-500">
                      List the topics, sections, or policies you want the quiz to focus on
                    </p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 3: Exam Configuration - Only show after scope is selected */}
        {examConfig.curriculumId && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Basic Configuration */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Settings size={20} />
                  Step 3: Basic Settings
                </CardTitle>
                <CardDescription>
                  Configure the fundamental parameters for your quiz
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Question Count */}
                <div className="space-y-2">
                  <Label htmlFor="questionCount">Number of Questions</Label>
                  <Input
                    id="questionCount"
                    type="number"
                    min="1"
                    max="50"
                    value={examConfig.questionCount}
                    onChange={(e) => setExamConfig(prev => ({ ...prev, questionCount: parseInt(e.target.value) || 1 }))}
                    className="w-full"
                  />
                  <p className="text-sm text-gray-500">Choose between 1-50 questions</p>
                </div>

                {/* Time Limit */}
                <div className="space-y-2">
                  <Label htmlFor="timeLimit">Time Limit (minutes)</Label>
                  <Input
                    id="timeLimit"
                    type="number"
                    min="5"
                    max="180"
                    value={examConfig.timeLimit}
                    onChange={(e) => setExamConfig(prev => ({ ...prev, timeLimit: parseInt(e.target.value) || 5 }))}
                    className="w-full"
                  />
                  <p className="text-sm text-gray-500">Set time limit between 5-180 minutes</p>
                </div>
              </CardContent>
            </Card>

            {/* Advanced Options */}
            <Card>
              <CardHeader>
                <CardTitle>Advanced Options</CardTitle>
                <CardDescription>
                  Customize difficulty levels and question types
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Difficulty Levels */}
                <div className="space-y-3">
                  <Label>Difficulty Levels</Label>
                  <div className="space-y-3">
                    {difficultyOptions.map((option) => (
                      <div key={option.id} className="flex items-start space-x-3">
                        <Checkbox
                          id={option.id}
                          checked={examConfig.difficulty.includes(option.id)}
                          onCheckedChange={(checked) => handleDifficultyChange(option.id, checked as boolean)}
                        />
                        <div className="space-y-1">
                          <Label htmlFor={option.id} className="cursor-pointer font-medium">
                            {option.label}
                          </Label>
                          <p className="text-sm text-gray-500">{option.description}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Question Types */}
                <div className="space-y-3">
                  <Label>Question Types</Label>
                  <div className="space-y-3">
                    {questionTypeOptions.map((option) => (
                      <div key={option.id} className="flex items-start space-x-3">
                        <Checkbox
                          id={option.id}
                          checked={examConfig.questionTypes.includes(option.id)}
                          onCheckedChange={(checked) => handleQuestionTypeChange(option.id, checked as boolean)}
                        />
                        <div className="space-y-1">
                          <Label htmlFor={option.id} className="cursor-pointer font-medium">
                            {option.label}
                          </Label>
                          <p className="text-sm text-gray-500">{option.description}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Summary and Generate Button */}
        {examConfig.curriculumId && (
          <Card>
            <CardContent className="pt-6">
              <div className="space-y-4">
                {/* Exam Summary */}
                <div className="p-4 bg-gray-50 rounded-lg">
                  <h4 className="font-semibold mb-3">Quiz Summary</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                    <div>
                      <span className="font-medium">Knowledge Base:</span> {selectedCurriculum?.name}
                    </div>
                    <div>
                      <span className="font-medium">Scope:</span> {
                        examConfig.scopeType === 'whole_curriculum' ? 'Whole Knowledge Base' :
                        examConfig.scopeType === 'whole_book' ? `Document: ${formatTitle(examConfig.bookTitle)}` :
                        'Specific Topics'
                      }
                    </div>
                    <div>
                      <span className="font-medium">Questions:</span> {examConfig.questionCount}
                    </div>
                    <div>
                      <span className="font-medium">Time Limit:</span> {examConfig.timeLimit} minutes
                    </div>
                    <div>
                      <span className="font-medium">Difficulty:</span> {examConfig.difficulty.join(', ')}
                    </div>
                    <div>
                      <span className="font-medium">Question Types:</span> {examConfig.questionTypes.length} selected
                    </div>
                  </div>
                </div>

                {/* Generate Button */}
                <div className="flex justify-center pt-4">
                  <Button 
                    onClick={handleGenerateExam}
                    disabled={
                      isGenerating || 
                      !examConfig.curriculumId || 
                      (examConfig.scopeType !== 'whole_curriculum' && !examConfig.bookTitle) ||
                      (examConfig.scopeType === 'specific_topics' && !examConfig.specificTopics.trim())
                    }
                    size="lg"
                    className="px-8 py-3 text-lg"
                  >
                    {isGenerating ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Generating Preview...
                      </>
                    ) : (
                      <>
                        <GraduationCap className="w-4 h-4 mr-2" />
                        Generate Quiz Preview
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
