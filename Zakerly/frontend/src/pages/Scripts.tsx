import React, { useState, useEffect } from 'react';
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
import { BookOpen, Settings, Loader2, GraduationCap, FileText, Presentation } from 'lucide-react';
import { CurriculumService, BooksService, ChatService } from '@/lib/services';
import { useAuth } from '@/contexts/AuthContext';
import type { Book as BookType, Curriculum } from '@/lib/types';

interface ScriptSetupConfig {
  curriculumId: string;
  bookTitle: string;
  duration: number;
  detailLevel: string;
  scriptStyle: string;
  targetAudience: string;
  scopeType: 'whole_curriculum' | 'whole_book' | 'specific_topics';
  specificTopics: string;
}

const detailLevelOptions = [
  { id: 'overview', label: 'Overview', description: 'High-level summary and key points' },
  { id: 'detailed', label: 'Detailed', description: 'In-depth coverage with examples' },
  { id: 'comprehensive', label: 'Comprehensive', description: 'Complete analysis with case studies' }
];

const scriptStyleOptions = [
  { id: 'lecture', label: 'Traditional Lecture', description: 'Structured presentation format' },
  { id: 'interactive', label: 'Interactive', description: 'Engaging with questions and activities' },
  { id: 'presentation', label: 'Presentation', description: 'Visual-heavy with key bullet points' }
];

const targetAudienceOptions = [
  { id: 'beginner', label: 'Beginner', description: 'Basic introduction to concepts' },
  { id: 'intermediate', label: 'Intermediate', description: 'Moderate complexity content' },
  { id: 'advanced', label: 'Advanced', description: 'Advanced analysis and applications' }
];

export default function Scripts() {
  const { bookTitle } = useParams<{ bookTitle: string }>();
  const navigate = useNavigate();
  const { user } = useAuth(); // ✅ Get authenticated user
  
  // State for curriculums and books
  const [curriculums, setCurriculums] = useState<Curriculum[]>([]);
  const [books, setBooks] = useState<BookType[]>([]);
  const [allBooks, setAllBooks] = useState<BookType[]>([]);
  const [isLoadingBooks, setIsLoadingBooks] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState('');
  
  const [scriptConfig, setScriptConfig] = useState<ScriptSetupConfig>({
    curriculumId: '',
    bookTitle: bookTitle || '',
    duration: 60,
    detailLevel: 'detailed',
    scriptStyle: 'lecture',
    targetAudience: 'intermediate',
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
      setError('Failed to load books and curriculums');
    } finally {
      setIsLoadingBooks(false);
    }
  };

  const handleCurriculumChange = (curriculumId: string) => {
    setScriptConfig(prev => ({ 
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
    setScriptConfig(prev => ({ ...prev, bookTitle }));
  };

  const handleDetailLevelChange = (detailLevel: string, checked: boolean) => {
    if (checked) {
      setScriptConfig(prev => ({ ...prev, detailLevel }));
    }
  };

  const handleScriptStyleChange = (style: string, checked: boolean) => {
    if (checked) {
      setScriptConfig(prev => ({ ...prev, scriptStyle: style }));
    }
  };

  const handleTargetAudienceChange = (audience: string, checked: boolean) => {
    if (checked) {
      setScriptConfig(prev => ({ ...prev, targetAudience: audience }));
    }
  };

  const handleScopeChange = (scope: 'whole_curriculum' | 'whole_book' | 'specific_topics') => {
    setScriptConfig(prev => ({
      ...prev,
      scopeType: scope,
      bookTitle: scope === 'whole_curriculum' ? '' : prev.bookTitle,
      specificTopics: (scope === 'whole_curriculum' || scope === 'whole_book') ? '' : prev.specificTopics
    }));
  };

  const handleGenerateScript = async () => {
    // Validate required fields
    if (!scriptConfig.curriculumId) {
      setError('Please select a curriculum');
      return;
    }
    
    if (scriptConfig.scopeType !== 'whole_curriculum' && !scriptConfig.bookTitle) {
      setError('Please select a book');
      return;
    }

    if (scriptConfig.scopeType === 'specific_topics' && !scriptConfig.specificTopics.trim()) {
      setError('Please specify topics for the script');
      return;
    }

    setError('');
    setIsGenerating(true);

    try {
      // Create the script generation request - match backend CurriculumScriptRequest model exactly
      let specificBooks: number[] | null = null;
      
      // Convert book titles to book IDs if whole_book scope
      if (scriptConfig.scopeType === 'whole_book' && scriptConfig.bookTitle) {
        const selectedBook = books.find(book => book.title === scriptConfig.bookTitle);
        if (selectedBook) {
          specificBooks = [selectedBook.id];
        } else {
          throw new Error('Selected book not found');
        }
      }

      const scriptRequest = {
        curriculum_id: parseInt(scriptConfig.curriculumId),
        title: `${selectedCurriculum?.name || 'Curriculum'} - ${scriptConfig.scopeType.replace('_', ' ')} Script`,
        scope: scriptConfig.scopeType, // Must be: 'whole_curriculum', 'whole_book', 'specific_topics'
        specific_books: specificBooks,
        specific_topics: scriptConfig.scopeType === 'specific_topics' ? scriptConfig.specificTopics : null,
        detail_level: scriptConfig.detailLevel,
        difficulty: scriptConfig.targetAudience,
        duration: scriptConfig.duration
      };

      console.log('🚀 Sending script request:', scriptRequest);

      const userId = user?.sub || ''; // ✅ Use authenticated user's ID
      const response = await ChatService.generateCurriculumScript(userId, scriptRequest);

      if (response && response.script_content) {
        console.log('✅ Script generated successfully:', response);
        setError('');
        
        // Save the script to the database
        try {
          
          const scriptToSave = {
            title: scriptRequest.title,
            curriculum_id: scriptRequest.curriculum_id,
            book_id: scriptRequest.specific_books?.[0] || null,
            scope: scriptRequest.scope,
            specific_topics: scriptRequest.specific_topics,
            specific_books: scriptRequest.specific_books,
            detail_level: scriptRequest.detail_level,
            difficulty: scriptRequest.difficulty,
            duration: scriptRequest.duration,
            content: response.script_content,
            script_style: 'lecture', // Default style
            target_audience: scriptRequest.difficulty,
            include_examples: true,
            include_exercises: false,
            include_visual_aids: true
          };

          // Import ScriptsService
          const { ScriptsService } = await import('@/lib/services');
          await ScriptsService.createScript(userId, scriptToSave);
          
          console.log('✅ Script saved to database successfully');
        } catch (saveError) {
          console.error('❌ Error saving script to database:', saveError);
          // Don't block the user flow if saving fails
        }
        
        // Show success message
        alert(`Script generated successfully! Title: ${response.title || scriptRequest.title}`);
        
        // Navigate back to dashboard
        navigate('/scripts');
      } else {
        throw new Error('No script content received from server');
      }
    } catch (err: any) {
      console.error('❌ Error generating script:', err);
      setError(err.message || 'Failed to generate script. Please try again.');
    } finally {
      setIsGenerating(false);
    }
  };

  const selectedCurriculum = curriculums.find(c => c.id.toString() === scriptConfig.curriculumId);

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <div className="container mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Presentation className="text-primary" size={32} />
            <div>
              <h1 className="text-3xl font-bold text-gray-900">Script Setup</h1>
              <p className="text-gray-600">
                Choose a curriculum and configure your script settings
              </p>
            </div>
          </div>
          <Button 
            variant="outline" 
            onClick={() => navigate('/scripts')}
            className="flex items-center gap-2"
          >
            ← Back to Dashboard
          </Button>
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
              Step 1: Select Curriculum
            </CardTitle>
            <CardDescription>
              Choose the curriculum that contains the content for your script
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Curriculum</Label>
                <Select 
                  value={scriptConfig.curriculumId} 
                  onValueChange={handleCurriculumChange}
                  disabled={isLoadingBooks}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a curriculum" />
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
                    {selectedCurriculum.description || 'Selected curriculum'}
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

        {/* Step 2: Script Scope Selection - Only show after curriculum is selected */}
        {scriptConfig.curriculumId && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Settings className="w-5 h-5" />
                Step 2: Choose Script Scope
              </CardTitle>
              <CardDescription>
                Decide what content to include in your script from the selected curriculum
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <RadioGroup 
                  value={scriptConfig.scopeType} 
                  onValueChange={handleScopeChange}
                  className="space-y-4"
                >
                  {/* Whole Curriculum Option */}
                  <div className="flex items-start space-x-3 p-4 border-2 rounded-lg hover:bg-gray-50 transition-colors">
                    <RadioGroupItem value="whole_curriculum" id="whole_curriculum" className="mt-1" />
                    <Label htmlFor="whole_curriculum" className="cursor-pointer flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <GraduationCap className="w-5 h-5 text-primary" />
                        <div className="font-semibold text-lg">Whole Curriculum Script</div>
                      </div>
                      <div className="text-sm text-gray-600 mb-2">
                        Generate a comprehensive script covering all {books.length} books in the curriculum
                      </div>
                      <div className="text-xs text-primary font-medium">
                        ✓ Recommended for comprehensive overview across multiple subject areas
                      </div>
                    </Label>
                  </div>
                  
                  {/* Single Book Option */}
                  <div className="flex items-start space-x-3 p-4 border-2 rounded-lg hover:bg-gray-50 transition-colors">
                    <RadioGroupItem value="whole_book" id="whole_book" className="mt-1" />
                    <Label htmlFor="whole_book" className="cursor-pointer flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <BookOpen className="w-5 h-5 text-green-600" />
                        <div className="font-semibold text-lg">Single Book Script</div>
                      </div>
                      <div className="text-sm text-gray-600 mb-2">
                        Generate script focused on one specific book from the curriculum
                      </div>
                      <div className="text-xs text-green-600 font-medium">
                        ✓ Perfect for detailed coverage of specific topics or subject areas
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
                        Focus on particular topics, chapters, or concepts you specify
                      </div>
                      <div className="text-xs text-accent font-medium">
                        ✓ Ideal for targeted coverage of specific learning objectives
                      </div>
                    </Label>
                  </div>
                </RadioGroup>

                {/* Book Selection - Only show for single book and specific topics */}
                {(scriptConfig.scopeType === 'whole_book' || scriptConfig.scopeType === 'specific_topics') && (
                  <div className="space-y-2 mt-4">
                    <Label>Select Book</Label>
                    <Select 
                      value={scriptConfig.bookTitle} 
                      onValueChange={handleBookChange}
                      disabled={!scriptConfig.curriculumId || isLoadingBooks}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Choose a book from the curriculum" />
                      </SelectTrigger>
                      <SelectContent>
                        {books.map((book) => (
                          <SelectItem key={book.id} value={book.title}>
                            <div className="flex items-center gap-2">
                              <BookOpen className="w-4 h-4" />
                              {book.title}
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {/* Topics Input - Only show for specific topics */}
                {scriptConfig.scopeType === 'specific_topics' && (
                  <div className="space-y-2 mt-4">
                    <Label htmlFor="topics">Specify Topics</Label>
                    <Textarea
                      id="topics"
                      placeholder="Enter specific topics, chapters, or concepts you want to focus on..."
                      value={scriptConfig.specificTopics}
                      onChange={(e) => setScriptConfig(prev => ({ ...prev, specificTopics: e.target.value }))}
                      className="min-h-[100px]"
                    />
                    <p className="text-sm text-gray-500">
                      List the topics, chapters, or concepts you want the script to focus on
                    </p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 3: Script Configuration - Only show after scope is selected */}
        {scriptConfig.curriculumId && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Basic Configuration */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Settings size={20} />
                  Step 3: Basic Settings
                </CardTitle>
                <CardDescription>
                  Configure the fundamental parameters for your script
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Duration */}
                <div className="space-y-2">
                  <Label htmlFor="duration">Duration (minutes)</Label>
                  <Input
                    id="duration"
                    type="number"
                    min="15"
                    max="240"
                    value={scriptConfig.duration}
                    onChange={(e) => setScriptConfig(prev => ({ ...prev, duration: parseInt(e.target.value) || 60 }))}
                    className="w-full"
                  />
                  <p className="text-sm text-gray-500">Set duration between 15-240 minutes</p>
                </div>

                {/* Detail Level */}
                <div className="space-y-3">
                  <Label>Detail Level</Label>
                  <div className="space-y-3">
                    {detailLevelOptions.map((option) => (
                      <div key={option.id} className="flex items-start space-x-3">
                        <Checkbox
                          id={option.id}
                          checked={scriptConfig.detailLevel === option.id}
                          onCheckedChange={(checked) => handleDetailLevelChange(option.id, checked as boolean)}
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

            {/* Advanced Options */}
            <Card>
              <CardHeader>
                <CardTitle>Advanced Options</CardTitle>
                <CardDescription>
                  Customize script style and target audience
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Script Style */}
                <div className="space-y-3">
                  <Label>Script Style</Label>
                  <div className="space-y-3">
                    {scriptStyleOptions.map((option) => (
                      <div key={option.id} className="flex items-start space-x-3">
                        <Checkbox
                          id={option.id}
                          checked={scriptConfig.scriptStyle === option.id}
                          onCheckedChange={(checked) => handleScriptStyleChange(option.id, checked as boolean)}
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

                {/* Target Audience */}
                <div className="space-y-3">
                  <Label>Target Audience</Label>
                  <div className="space-y-3">
                    {targetAudienceOptions.map((option) => (
                      <div key={option.id} className="flex items-start space-x-3">
                        <Checkbox
                          id={option.id}
                          checked={scriptConfig.targetAudience === option.id}
                          onCheckedChange={(checked) => handleTargetAudienceChange(option.id, checked as boolean)}
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
        {scriptConfig.curriculumId && (
          <Card>
            <CardContent className="pt-6">
              <div className="space-y-4">
                {/* Script Summary */}
                <div className="p-4 bg-gray-50 rounded-lg">
                  <h4 className="font-semibold mb-3">Script Summary</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                    <div>
                      <span className="font-medium">Curriculum:</span> {selectedCurriculum?.name}
                    </div>
                    <div>
                      <span className="font-medium">Scope:</span> {
                        scriptConfig.scopeType === 'whole_curriculum' ? 'Whole Curriculum' :
                        scriptConfig.scopeType === 'whole_book' ? `Book: ${scriptConfig.bookTitle}` :
                        'Specific Topics'
                      }
                    </div>
                    <div>
                      <span className="font-medium">Duration:</span> {scriptConfig.duration} minutes
                    </div>
                    <div>
                      <span className="font-medium">Detail Level:</span> {scriptConfig.detailLevel}
                    </div>
                    <div>
                      <span className="font-medium">Style:</span> {scriptConfig.scriptStyle}
                    </div>
                    <div>
                      <span className="font-medium">Audience:</span> {scriptConfig.targetAudience}
                    </div>
                  </div>
                </div>

                {/* Generate Button */}
                <div className="flex justify-center pt-4">
                  <Button 
                    onClick={handleGenerateScript}
                    disabled={
                      isGenerating || 
                      !scriptConfig.curriculumId || 
                      (scriptConfig.scopeType !== 'whole_curriculum' && !scriptConfig.bookTitle) ||
                      (scriptConfig.scopeType === 'specific_topics' && !scriptConfig.specificTopics.trim())
                    }
                    className="px-8 py-3 text-lg"
                  >
                    {isGenerating ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Generating Script...
                      </>
                    ) : (
                      <>
                        <Presentation className="w-4 h-4 mr-2" />
                        Generate Script
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