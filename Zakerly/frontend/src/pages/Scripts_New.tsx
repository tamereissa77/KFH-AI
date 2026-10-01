import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Header } from '@/components/ui/header';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { CurriculumService, ChatService } from '@/lib/services';
import { useAuth } from '@/contexts/AuthContext';
import { Curriculum, BookInCurriculum } from '@/lib/types';
import { 
  Presentation, 
  Plus, 
  Search, 
  Download, 
  Copy, 
  Eye,
  Clock,
  Sparkles,
  Edit,
  Trash2,
  Loader2,
  CheckCircle,
  X,
  BookOpen,
  Target,
  FileText,
  ArrowRight,
  BarChart3,
  GraduationCap,
  User,
  Settings,
  Filter
} from 'lucide-react';

interface ScriptGenerationParams {
  curriculumId: string;
  scope: 'whole_curriculum' | 'specific_topics';
  specificBooks?: string[];
  specificTopics?: string;
  detailLevel: 'high_level' | 'detailed' | 'comprehensive';
  duration: number; // in minutes
  scriptStyle: 'lecture' | 'interactive' | 'presentation' | 'workshop';
  targetAudience: 'beginner' | 'intermediate' | 'advanced';
  includeExamples: boolean;
  includeExercises: boolean;
  includeVisualAids: boolean;
}

interface GeneratedScript {
  id?: string;
  title: string;
  content: string;
  scope: string;
  duration: number;
  style: string;
  targetAudience: string;
  createdAt: string;
  analytics?: {
    wordCount: number;
    estimatedReadingTime: number;
    complexityScore: number;
    keyTopics: string[];
  };
}

const Scripts: React.FC = () => {
  const { token, user } = useAuth(); // ✅ Get authenticated user
  const navigate = useNavigate();
  
  // State Management
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  
  // Generated Scripts
  const [generatedScripts, setGeneratedScripts] = useState<GeneratedScript[]>([]);
  const [selectedScript, setSelectedScript] = useState<GeneratedScript | null>(null);
  const [viewMode, setViewMode] = useState<'list' | 'details'>('list');
  
  // UI State
  const [searchTerm, setSearchTerm] = useState('');

  // Load user scripts on component mount
  useEffect(() => {
    loadUserScripts();
  }, []);

  const loadUserScripts = async () => {
    try {
      setLoading(true);
      const userId = user?.sub; // ✅ Use authenticated user's ID
      
      if (!userId) {
        setError('User not authenticated. Please log in again.');
        setLoading(false);
        return;
      }
      
      // Import ScriptsService dynamically
      const { ScriptsService } = await import('@/lib/services');
      const scripts = await ScriptsService.getUserScripts(userId);
      
      // Convert backend script format to frontend format
      const convertedScripts = scripts.map((script: any) => ({
        id: script.id,
        title: script.title,
        content: script.content,
        scope: script.scope === 'whole_curriculum' ? 'Complete Curriculum' : script.scope === 'whole_book' ? 'Single Book' : 'Selected Topics',
        duration: script.duration,
        style: script.script_style || 'lecture',
        targetAudience: script.target_audience || script.difficulty,
        createdAt: script.created_at,
        analytics: {
          wordCount: script.content?.split(' ').length || 0,
          estimatedReadingTime: Math.ceil((script.content?.split(' ').length || 0) / 200),
          complexityScore: 75, // Default complexity score
          keyTopics: []
        }
      }));
      
      setGeneratedScripts(convertedScripts);
    } catch (err) {
      console.error('Error loading user scripts:', err);
      setError('Failed to load scripts');
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setSuccess('Script copied to clipboard!');
  };

  const downloadScript = (script: GeneratedScript) => {
    const element = document.createElement('a');
    const file = new Blob([script.content], { type: 'text/plain' });
    element.href = URL.createObjectURL(file);
    element.download = `${script.title.replace(/[^a-zA-Z0-9]/g, '_')}.txt`;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  const getStyleIcon = (style: string) => {
    switch (style) {
      case 'lecture': return <Presentation className="w-4 h-4" />;
      case 'interactive': return <Target className="w-4 h-4" />;
      case 'presentation': return <FileText className="w-4 h-4" />;
      case 'workshop': return <Settings className="w-4 h-4" />;
      default: return <FileText className="w-4 h-4" />;
    }
  };

  const getAudienceColor = (audience: string) => {
    switch (audience) {
      case 'beginner': return 'bg-green-100 text-green-800';
      case 'intermediate': return 'bg-yellow-100 text-yellow-800';
      case 'advanced': return 'bg-red-100 text-red-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const clearAlerts = () => {
    setError(null);
    setSuccess(null);
  };

  if (viewMode === 'details' && selectedScript) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
        <Header />
        
        <div className="container mx-auto px-4 py-8">
          {/* Header */}
          <div className="flex items-center justify-between mb-8">
            <div className="flex items-center gap-4">
              <Button
                variant="outline"
                onClick={() => setViewMode('list')}
                className="flex items-center gap-2"
              >
                <ArrowRight className="w-4 h-4 rotate-180" />
                Back to Scripts
              </Button>
              <div className="flex items-center gap-2">
                <Presentation className="w-6 h-6 text-primary" />
                <h1 className="text-2xl font-bold">Script Details</h1>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                onClick={() => copyToClipboard(selectedScript.content)}
                className="flex items-center gap-2"
              >
                <Copy className="w-4 h-4" />
                Copy
              </Button>
              <Button
                onClick={() => downloadScript(selectedScript)}
                className="flex items-center gap-2"
              >
                <Download className="w-4 h-4" />
                Download
              </Button>
            </div>
          </div>

          {/* Alerts */}
          {error && (
            <Alert className="mb-6 border-red-200 bg-red-50">
              <X className="h-4 w-4 text-red-600" />
              <AlertDescription className="text-red-800">
                {error}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearAlerts}
                  className="ml-2 h-auto p-0 text-red-600 hover:text-red-800"
                >
                  <X className="w-3 h-3" />
                </Button>
              </AlertDescription>
            </Alert>
          )}

          {success && (
            <Alert className="mb-6 border-green-200 bg-green-50">
              <CheckCircle className="h-4 w-4 text-green-600" />
              <AlertDescription className="text-green-800">
                {success}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearAlerts}
                  className="ml-2 h-auto p-0 text-green-600 hover:text-green-800"
                >
                  <X className="w-3 h-3" />
                </Button>
              </AlertDescription>
            </Alert>
          )}

          {/* Script Details */}
          <div className="grid lg:grid-cols-4 gap-6">
            {/* Script Metadata */}
            <div className="lg:col-span-1">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <BarChart3 className="w-5 h-5" />
                    Script Information
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <label className="text-sm font-medium text-muted-foreground">Style</label>
                    <div className="flex items-center gap-2 mt-1">
                      {getStyleIcon(selectedScript.style)}
                      <span className="capitalize">{selectedScript.style}</span>
                    </div>
                  </div>
                  
                  <div>
                    <label className="text-sm font-medium text-muted-foreground">Target Audience</label>
                    <Badge className={`mt-1 ${getAudienceColor(selectedScript.targetAudience)}`}>
                      {selectedScript.targetAudience}
                    </Badge>
                  </div>
                  
                  <div>
                    <label className="text-sm font-medium text-muted-foreground">Duration</label>
                    <div className="flex items-center gap-2 mt-1">
                      <Clock className="w-4 h-4" />
                      <span>{selectedScript.duration} minutes</span>
                    </div>
                  </div>
                  
                  <div>
                    <label className="text-sm font-medium text-muted-foreground">Scope</label>
                    <p className="mt-1">{selectedScript.scope}</p>
                  </div>
                  
                  {selectedScript.analytics && (
                    <>
                      <div>
                        <label className="text-sm font-medium text-muted-foreground">Word Count</label>
                        <p className="mt-1">{selectedScript.analytics.wordCount}</p>
                      </div>
                      
                      <div>
                        <label className="text-sm font-medium text-muted-foreground">Reading Time</label>
                        <p className="mt-1">{selectedScript.analytics.estimatedReadingTime} min</p>
                      </div>
                      
                      <div>
                        <label className="text-sm font-medium text-muted-foreground">Complexity Score</label>
                        <p className="mt-1">{selectedScript.analytics.complexityScore}/100</p>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Script Content */}
            <div className="lg:col-span-3">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <FileText className="w-5 h-5" />
                    {selectedScript.title}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="prose max-w-none">
                    <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                      {selectedScript.content}
                    </pre>
                  </div>
                </CardContent>
              </Card>
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
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-2">
            <Presentation className="w-6 h-6 text-primary" />
            <h1 className="text-2xl font-bold">Lecture Scripts</h1>
          </div>
          
          <Button
            onClick={() => navigate('/scripts/create')}
            className="flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            Generate New Script
          </Button>
        </div>

        {/* Alerts */}
        {error && (
          <Alert className="mb-6 border-red-200 bg-red-50">
            <X className="h-4 w-4 text-red-600" />
            <AlertDescription className="text-red-800">
              {error}
              <Button
                variant="ghost"
                size="sm"
                onClick={clearAlerts}
                className="ml-2 h-auto p-0 text-red-600 hover:text-red-800"
              >
                <X className="w-3 h-3" />
              </Button>
            </AlertDescription>
          </Alert>
        )}

        {success && (
          <Alert className="mb-6 border-green-200 bg-green-50">
            <CheckCircle className="h-4 w-4 text-green-600" />
            <AlertDescription className="text-green-800">
              {success}
              <Button
                variant="ghost"
                size="sm"
                onClick={clearAlerts}
                className="ml-2 h-auto p-0 text-green-600 hover:text-green-800"
              >
                <X className="w-3 h-3" />
              </Button>
            </AlertDescription>
          </Alert>
        )}

        {/* Generated Scripts List */}
        {generatedScripts.length > 0 && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold">Generated Scripts</h2>
              <div className="flex items-center gap-2">
                <Input
                  placeholder="Search scripts..."
                  className="w-64"
                />
                <Button variant="outline" size="sm">
                  <Filter className="w-4 h-4" />
                </Button>
              </div>
            </div>

            <div className="grid gap-4">
              {generatedScripts.map((script) => (
                <Card
                  key={script.id}
                  className="cursor-pointer hover:shadow-md transition-shadow"
                  onClick={() => setSelectedScript(script)}
                >
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          {getStyleIcon(script.style)}
                          <h3 className="font-semibold">{script.title}</h3>
                        </div>
                        
                        <div className="flex items-center gap-4 text-sm text-muted-foreground mb-3">
                          <div className="flex items-center gap-1">
                            <Clock className="w-4 h-4" />
                            {script.duration} min
                          </div>
                          <Badge className={getAudienceColor(script.targetAudience)}>
                            {script.targetAudience}
                          </Badge>
                          <Badge variant="outline">
                            {script.scope}
                          </Badge>
                        </div>
                        
                        {script.analytics && (
                          <div className="flex items-center gap-4 text-sm text-muted-foreground">
                            <span>{script.analytics.wordCount} words</span>
                            <span>{script.analytics.estimatedReadingTime} min read</span>
                            <span>Complexity: {script.analytics.complexityScore}/100</span>
                          </div>
                        )}
                      </div>
                      
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            copyToClipboard(script.content);
                          }}
                        >
                          <Copy className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            downloadScript(script);
                          }}
                        >
                          <Download className="w-4 h-4" />
                        </Button>
                        <Button
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedScript(script);
                            setViewMode('details');
                          }}
                        >
                          <Eye className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* Empty State */}
        {generatedScripts.length === 0 && !loading && (
          <div className="text-center py-12">
            <Presentation className="w-16 h-16 mx-auto text-muted-foreground mb-4" />
            <h3 className="text-xl font-semibold mb-2">No Scripts Generated Yet</h3>
            <p className="text-muted-foreground mb-6">
              Create your first lecture script by selecting a curriculum and configuring your preferences.
            </p>
            <Button
              onClick={() => navigate('/scripts/create')}
              className="flex items-center gap-2"
            >
              <Plus className="w-4 h-4" />
              Generate Your First Script
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};

export default Scripts;
