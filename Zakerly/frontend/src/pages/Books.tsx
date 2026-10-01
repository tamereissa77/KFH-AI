import React, { useState, useEffect } from 'react';
import { formatTitle } from '@/lib/utils';
import { Header } from '@/components/ui/header';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { BookOpen, Plus, Search, MessageSquare, GraduationCap, Loader2, AlertCircle, Sparkles, FolderOpen, ClipboardCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { BooksService, CurriculumService, Utils } from '@/lib/services';
import type { Book as BookType, Curriculum } from '@/lib/types';

export default function Books() {
  const navigate = useNavigate();
  const [books, setBooks] = useState<BookType[]>([]);
  const [curriculums, setCurriculums] = useState<Curriculum[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterCurriculum, setFilterCurriculum] = useState('all');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  // Load books and categories on component mount
  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setIsLoading(true);
      setError('');
      
      const [booksData, curriculumsData] = await Promise.all([
        BooksService.getBooks(),
        CurriculumService.getCurriculums()
      ]);
      
      setBooks(booksData);
      setCurriculums(curriculumsData);
    } catch (err) {
      console.error('Error loading data:', err);
      setError(err instanceof Error ? err.message : 'Failed to load books');
    } finally {
      setIsLoading(false);
    }
  };

  const filteredBooks = books.filter(book => {
    const matchesSearch = book.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
                         (book.author && book.author.toLowerCase().includes(searchTerm.toLowerCase()));
    
    const matchesFilter = filterCurriculum === 'all' || book.curriculum_id === parseInt(filterCurriculum);
    
    return matchesSearch && matchesFilter;
  });

  const getCurriculumName = (curriculumId: number): string => {
    const curriculum = curriculums.find(curr => curr.id === curriculumId);
    return curriculum ? curriculum.name : 'Unknown knowledge base';
  };

  const formatDate = (dateString: string): string => {
    return new Date(dateString).toLocaleDateString();
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
        <Header />
        <div className="container mx-auto px-4 py-8">
          <div className="flex items-center justify-center h-64">
            <div className="text-center">
              <Loader2 className="w-8 h-8 animate-spin mx-auto mb-4 text-primary" />
              <p className="text-muted-foreground">Loading documents...</p>
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
        <div className="max-w-6xl mx-auto">
          {/* Header Section */}
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-3xl font-bold text-gradient-primary mb-2">
                Knowledge Bases
              </h1>
              <p className="text-muted-foreground">
                Internal documents grouped by knowledge base. Ask questions or create quizzes from any document.
              </p>
            </div>
            <Button 
              onClick={() => navigate('/books/add')}
              className="bg-gradient-primary"
            >
              <Plus className="w-4 h-4 mr-2" />
              Upload Documents
            </Button>
          </div>

          {/* Error Alert */}
          {error && (
            <Alert variant="destructive" className="mb-6">
              <AlertCircle className="w-4 h-4" />
              <AlertDescription>
                {error}
                <Button 
                  variant="outline" 
                  size="sm" 
                  onClick={loadData}
                  className="ml-4"
                >
                  Retry
                </Button>
              </AlertDescription>
            </Alert>
          )}

          {/* Filters and Search */}
          <Card className="mb-6">
            <CardContent className="pt-6">
              <div className="flex flex-col gap-4">
                <div className="flex flex-col md:flex-row gap-4">
                  <div className="flex-1 relative">
                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <Input
                      placeholder="Search documents by title..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="pl-10"
                    />
                  </div>
                  
                </div>

                {/* Curriculum Filter */}
                <div className="flex justify-end">
                  <Select value={filterCurriculum} onValueChange={setFilterCurriculum}>
                    <SelectTrigger className="w-full md:w-64">
                      <SelectValue placeholder="Filter by knowledge base" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All knowledge bases</SelectItem>
                      {curriculums.map(curriculum => (
                        <SelectItem key={curriculum.id} value={curriculum.id.toString()}>
                          <div className="flex flex-col">
                            <span>{curriculum.name}</span>
                            {curriculum.description && (
                              <span className="text-xs text-muted-foreground">
                                {curriculum.description.length > 50 
                                  ? curriculum.description.substring(0, 50) + '...'
                                  : curriculum.description
                                }
                              </span>
                            )}
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Stats Cards */}
          <div className="grid grid-cols-2 gap-4 mb-8">
            <Card>
              <CardContent className="pt-6">
                <div className="text-center">
                  <div className="text-2xl font-bold text-primary">{books.length}</div>
                  <div className="text-sm text-muted-foreground">Documents</div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-center">
                  <div className="text-2xl font-bold text-accent">{curriculums.length}</div>
                  <div className="text-sm text-muted-foreground">Knowledge bases</div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Books Grid */}
          {filteredBooks.length === 0 ? (
            <Card>
              <CardContent className="pt-8 pb-8">
                <div className="text-center">
                  <BookOpen className="w-16 h-16 text-muted-foreground mx-auto mb-4" />
                  <h3 className="text-lg font-semibold mb-2">
                    {books.length === 0 ? 'No documents yet' : 'No documents found'}
                  </h3>
                  <p className="text-muted-foreground mb-4">
                    {books.length === 0 
                      ? 'Upload documents to a knowledge base so staff can ask questions about them' 
                      : 'Try adjusting your search or filters'}
                  </p>
                  {books.length === 0 && (
                    <Button onClick={() => navigate('/books/add')} className="bg-gradient-primary">
                      <Plus className="w-4 h-4 mr-2" />
                      Upload Documents
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredBooks.map((book) => (
                <Card key={book.id} className="hover:shadow-lg transition-shadow duration-200">
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <CardTitle className="text-lg leading-tight mb-1 break-words">{formatTitle(book.title)}</CardTitle>
                        {book.author && (
                          <p className="text-sm text-muted-foreground truncate">Issued by {book.author}</p>
                        )}
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex items-center justify-between text-sm">
                      <div className="flex flex-wrap gap-1">
                        {book.curriculum_id && (
                          <Badge variant="default" className="bg-primary text-white">
                            <FolderOpen className="w-3 h-3 mr-1" />
                            {getCurriculumName(book.curriculum_id)}
                          </Badge>
                        )}
                      </div>
                      <div className="flex items-center gap-1 text-muted-foreground">
                        <Sparkles className="w-3 h-3" />
                        <span className="text-xs">AI Enhanced</span>
                      </div>
                    </div>
                    
                    <div className="space-y-2 text-xs text-muted-foreground">
                      {book.publication_year && (
                        <div className="flex justify-between">
                          <span>Published:</span>
                          <span>{book.publication_year}</span>
                        </div>
                      )}
                      <div className="flex justify-between">
                        <span>Added:</span>
                        <span>{formatDate(book.created_at)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>File:</span>
                        <span className="truncate ml-2" title={book.file_name}>
                          {book.file_name}
                        </span>
                      </div>
                    </div>
                    
                    <div className="flex gap-2 pt-2">
                      <Button 
                        variant="outline" 
                        size="sm" 
                        className="flex-1"
                        onClick={() => navigate(`/chat?document=${book.id}`)}
                      >
                        <MessageSquare className="w-3 h-3 mr-2" />
                        Ask
                      </Button>
                      <Button 
                        variant="outline" 
                        size="sm" 
                        className="flex-1"
                        onClick={() => navigate(`/exam-setup/${encodeURIComponent(book.title)}`)}
                      >
                        <ClipboardCheck className="w-3 h-3 mr-2" />
                        Quiz
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
