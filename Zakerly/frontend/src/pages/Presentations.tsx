import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Header } from '../components/ui/header';
import { PresentationsService, CurriculumService, BooksService, Utils } from '../lib/services';
import type { Presentation, Curriculum, Book, PresentationGenerateRequest } from '../lib/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
import { Loader2, Presentation as PresentationIcon, Trash2, Eye, Plus, Sparkles } from 'lucide-react';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Switch } from '../components/ui/switch';
import { useAuth } from '../contexts/AuthContext';

export default function Presentations() {
  const navigate = useNavigate();
  const { user } = useAuth(); // ✅ Get authenticated user
  const [presentations, setPresentations] = useState<Presentation[]>([]);
  const [curriculums, setCurriculums] = useState<Curriculum[]>([]);
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Form state
  const [formData, setFormData] = useState<PresentationGenerateRequest>({
    title: '',
    scope: 'whole_curriculum',
    detail_level: 'overview',
    difficulty: 'intermediate',
    slides_count: 15,
    slide_style: 'professional',
    include_diagrams: true,
    include_code_examples: false,
  });

  const userId = user?.sub || ''; // ✅ Use authenticated user's ID

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [presentationsData, curriculumsData, booksData] = await Promise.all([
        PresentationsService.getUserPresentations(userId),
        CurriculumService.getCurriculums(),
        BooksService.getBooks(),
      ]);
      setPresentations(presentationsData);
      setCurriculums(curriculumsData);
      setBooks(booksData);
    } catch (err: any) {
      setError(err.message || 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    try {
      setGenerating(true);
      setError(null);
      setSuccess(null);

      // Validate required fields
      if (!formData.title.trim()) {
        setError('Please enter a title');
        return;
      }

      if (formData.scope === 'whole_curriculum' && !formData.curriculum_id) {
        setError('Please select a curriculum');
        return;
      }

      if (formData.scope === 'whole_book' && !formData.book_id) {
        setError('Please select a book');
        return;
      }

      if (formData.scope === 'specific_topics' && !formData.specific_topics?.trim()) {
        setError('Please enter specific topics');
        return;
      }

      // Generate presentation
      const result = await PresentationsService.generatePresentation(userId, formData);

      // Save the generated presentation
      const saveRequest = {
        book_id: formData.book_id || null,
        title: formData.title,
        scope: formData.scope,
        specific_topics: formData.specific_topics,
        detail_level: formData.detail_level,
        difficulty: formData.difficulty,
        slides_count: formData.slides_count,
        slide_style: formData.slide_style,
        include_diagrams: formData.include_diagrams,
        include_code_examples: formData.include_code_examples,
        content: result,
      };

      const savedPresentation = await PresentationsService.createPresentation(userId, saveRequest);
      
      setSuccess('Presentation generated successfully!');
      await loadData();
      
      // Navigate to view the presentation
      setTimeout(() => {
        navigate(`/presentations/${savedPresentation.id}`);
      }, 1000);

    } catch (err: any) {
      setError(err.message || 'Failed to generate presentation');
    } finally {
      setGenerating(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this presentation?')) return;
    
    try {
      await PresentationsService.deletePresentation(id, userId);
      setSuccess('Presentation deleted successfully');
      await loadData();
    } catch (err: any) {
      setError(err.message || 'Failed to delete presentation');
    }
  };

  const handleView = (id: string) => {
    navigate(`/presentations/${id}`);
  };

  const getScopeBadgeColor = (scope: string) => {
    switch (scope) {
      case 'whole_curriculum': return 'bg-accent';
      case 'whole_book': return 'bg-primary';
      case 'specific_topics': return 'bg-green-500';
      default: return 'bg-gray-500';
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
        <Header />
        <div className="flex items-center justify-center min-h-screen">
          <Loader2 className="h-8 w-8 animate-spin" />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
      <Header />
      
      <div className="container mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-4xl font-bold mb-2">Presentations</h1>
        <p className="text-muted-foreground">
          Generate professional presentations from your curriculum content
        </p>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {success && (
        <Alert className="mb-6 bg-green-50 text-green-900 border-green-200">
          <AlertDescription>{success}</AlertDescription>
        </Alert>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Generation Form */}
        <div className="lg:col-span-1">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-5 w-5" />
                Generate Presentation
              </CardTitle>
              <CardDescription>
                Create a new presentation from your curriculum
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="title">Title *</Label>
                <Input
                  id="title"
                  placeholder="e.g., Introduction to Machine Learning"
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="scope">Scope *</Label>
                <Select
                  value={formData.scope}
                  onValueChange={(value: any) => setFormData({ ...formData, scope: value })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="whole_curriculum">Whole Curriculum</SelectItem>
                    <SelectItem value="whole_book">Whole Book</SelectItem>
                    <SelectItem value="specific_topics">Specific Topics</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {formData.scope === 'whole_curriculum' && (
                <div className="space-y-2">
                  <Label htmlFor="curriculum">Curriculum *</Label>
                  <Select
                    value={formData.curriculum_id?.toString()}
                    onValueChange={(value) => setFormData({ ...formData, curriculum_id: parseInt(value) })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select curriculum" />
                    </SelectTrigger>
                    <SelectContent>
                      {curriculums.map((curr) => (
                        <SelectItem key={curr.id} value={curr.id.toString()}>
                          {curr.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {formData.scope === 'whole_book' && (
                <div className="space-y-2">
                  <Label htmlFor="book">Book *</Label>
                  <Select
                    value={formData.book_id?.toString()}
                    onValueChange={(value) => setFormData({ ...formData, book_id: parseInt(value) })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select book" />
                    </SelectTrigger>
                    <SelectContent>
                      {books.map((book) => (
                        <SelectItem key={book.id} value={book.id.toString()}>
                          {book.title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {formData.scope === 'specific_topics' && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="book">Book (Optional)</Label>
                    <Select
                      value={formData.book_id?.toString() || ''}
                      onValueChange={(value) => setFormData({ ...formData, book_id: value ? parseInt(value) : undefined })}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select book (optional)" />
                      </SelectTrigger>
                      <SelectContent>
                        {books.map((book) => (
                          <SelectItem key={book.id} value={book.id.toString()}>
                            {book.title}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="topics">Specific Topics *</Label>
                    <Textarea
                      id="topics"
                      placeholder="e.g., Neural Networks, Backpropagation, Gradient Descent"
                      value={formData.specific_topics || ''}
                      onChange={(e) => setFormData({ ...formData, specific_topics: e.target.value })}
                      rows={3}
                    />
                  </div>
                </>
              )}

              <div className="space-y-2">
                <Label htmlFor="detail_level">Detail Level</Label>
                <Select
                  value={formData.detail_level}
                  onValueChange={(value: any) => setFormData({ ...formData, detail_level: value })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="overview">Overview</SelectItem>
                    <SelectItem value="detailed">Detailed</SelectItem>
                    <SelectItem value="comprehensive">Comprehensive</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="difficulty">Difficulty</Label>
                <Select
                  value={formData.difficulty}
                  onValueChange={(value: any) => setFormData({ ...formData, difficulty: value })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="beginner">Beginner</SelectItem>
                    <SelectItem value="intermediate">Intermediate</SelectItem>
                    <SelectItem value="advanced">Advanced</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="slides_count">Number of Slides</Label>
                <Input
                  id="slides_count"
                  type="number"
                  min="5"
                  max="50"
                  value={formData.slides_count}
                  onChange={(e) => setFormData({ ...formData, slides_count: parseInt(e.target.value) })}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="slide_style">Slide Style</Label>
                <Select
                  value={formData.slide_style}
                  onValueChange={(value: any) => setFormData({ ...formData, slide_style: value })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="professional">Professional</SelectItem>
                    <SelectItem value="creative">Creative</SelectItem>
                    <SelectItem value="minimal">Minimal</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-center justify-between">
                <Label htmlFor="diagrams">Include Diagrams</Label>
                <Switch
                  id="diagrams"
                  checked={formData.include_diagrams}
                  onCheckedChange={(checked) => setFormData({ ...formData, include_diagrams: checked })}
                />
              </div>

              <div className="flex items-center justify-between">
                <Label htmlFor="code">Include Code Examples</Label>
                <Switch
                  id="code"
                  checked={formData.include_code_examples}
                  onCheckedChange={(checked) => setFormData({ ...formData, include_code_examples: checked })}
                />
              </div>

              <Button
                onClick={handleGenerate}
                disabled={generating}
                className="w-full"
              >
                {generating ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Plus className="mr-2 h-4 w-4" />
                    Generate Presentation
                  </>
                )}
              </Button>
            </CardContent>
          </Card>
        </div>

        {/* Presentations List */}
        <div className="lg:col-span-2">
          <div className="mb-4">
            <h2 className="text-2xl font-bold">Your Presentations</h2>
            <p className="text-sm text-muted-foreground">
              {presentations.length} presentation{presentations.length !== 1 ? 's' : ''} total
            </p>
          </div>

          {presentations.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <PresentationIcon className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
                <h3 className="text-lg font-semibold mb-2">No presentations yet</h3>
                <p className="text-muted-foreground">
                  Generate your first presentation to get started
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {presentations.map((presentation) => (
                <Card key={presentation.id} className="hover:shadow-md transition-shadow">
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          <h3 className="text-lg font-semibold">{presentation.title}</h3>
                          <Badge className={getScopeBadgeColor(presentation.scope)}>
                            {presentation.scope.replace('_', ' ')}
                          </Badge>
                          <Badge variant="outline">{presentation.content.total_slides} slides</Badge>
                        </div>
                        <div className="text-sm text-muted-foreground space-y-1">
                          <p>
                            <span className="font-medium">Detail:</span> {presentation.detail_level} | 
                            <span className="font-medium"> Difficulty:</span> {presentation.difficulty} |
                            <span className="font-medium"> Style:</span> {presentation.slide_style}
                          </p>
                          <p>
                            <span className="font-medium">Duration:</span> ~{presentation.content.estimated_duration} min |
                            <span className="font-medium"> Created:</span> {new Date(presentation.created_at).toLocaleDateString()}
                          </p>
                          {presentation.specific_topics && (
                            <p>
                              <span className="font-medium">Topics:</span> {presentation.specific_topics}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-2 ml-4">
                        <Button
                          size="sm"
                          variant="default"
                          onClick={() => handleView(presentation.id)}
                        >
                          <Eye className="h-4 w-4 mr-1" />
                          View
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleDelete(presentation.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}
