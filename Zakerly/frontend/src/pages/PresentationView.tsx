import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { PresentationsService, Utils } from '../lib/services';
import type { Presentation } from '../lib/types';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { 
  Loader2, 
  ArrowLeft, 
  ChevronLeft, 
  ChevronRight, 
  Presentation as PresentationIcon,
  Download,
  Maximize2,
  Eye,
  Lightbulb
} from 'lucide-react';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Separator } from '../components/ui/separator';
import { useAuth } from '../contexts/AuthContext';

export default function PresentationView() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth(); // ✅ Get authenticated user
  const [presentation, setPresentation] = useState<Presentation | null>(null);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [showSpeakerNotes, setShowSpeakerNotes] = useState(true);

  const userId = user?.sub || ''; // ✅ Use authenticated user's ID

  useEffect(() => {
    if (id) {
      loadPresentation();
    }
  }, [id]);

  const loadPresentation = async () => {
    try {
      setLoading(true);
      const data = await PresentationsService.getPresentation(id!, userId);
      setPresentation(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load presentation');
    } finally {
      setLoading(false);
    }
  };

  const handlePrevious = () => {
    setCurrentSlide((prev) => Math.max(0, prev - 1));
  };

  const handleNext = () => {
    if (presentation) {
      setCurrentSlide((prev) => Math.min(presentation.content.slides.length - 1, prev + 1));
    }
  };

  const handleKeyPress = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') handlePrevious();
    if (e.key === 'ArrowRight') handleNext();
    if (e.key === 'Escape') setFullscreen(false);
  };

  useEffect(() => {
    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [presentation]);

  const downloadAsText = () => {
    if (!presentation) return;

    const content = presentation.content.slides
      .map((slide, idx) => {
        let text = `\n${'='.repeat(80)}\nSlide ${idx + 1}: ${slide.title}\n${'='.repeat(80)}\n\n`;
        text += slide.content.map(item => `• ${item}`).join('\n');
        
        if (slide.visual_suggestions && slide.visual_suggestions.length > 0) {
          text += '\n\nVisual Suggestions:\n';
          text += slide.visual_suggestions.map(v => `  - ${v}`).join('\n');
        }
        
        if (slide.speaker_notes) {
          text += '\n\nSpeaker Notes:\n';
          text += slide.speaker_notes;
        }
        
        return text;
      })
      .join('\n\n');

    const blob = new Blob([`${presentation.title}\n${'='.repeat(presentation.title.length)}\n${content}`], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${presentation.title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (error || !presentation) {
    return (
      <div className="container mx-auto px-4 py-8">
        <Alert variant="destructive">
          <AlertDescription>{error || 'Presentation not found'}</AlertDescription>
        </Alert>
        <Button onClick={() => navigate('/presentations')} className="mt-4">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Presentations
        </Button>
      </div>
    );
  }

  const slide = presentation.content.slides[currentSlide];
  const progress = ((currentSlide + 1) / presentation.content.slides.length) * 100;

  return (
    <div className={`${fullscreen ? 'fixed inset-0 z-50 bg-background' : 'container mx-auto px-4 py-8'}`}>
      {/* Header */}
      {!fullscreen && (
        <div className="mb-6">
          <Button
            variant="ghost"
            onClick={() => navigate('/presentations')}
            className="mb-4"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Presentations
          </Button>
          
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold mb-2">{presentation.title}</h1>
              <div className="flex items-center gap-2 flex-wrap">
                <Badge>{presentation.scope.replace('_', ' ')}</Badge>
                <Badge variant="outline">{presentation.detail_level}</Badge>
                <Badge variant="outline">{presentation.difficulty}</Badge>
                <Badge variant="outline">{presentation.slide_style}</Badge>
                <span className="text-sm text-muted-foreground">
                  {presentation.content.total_slides} slides • ~{presentation.content.estimated_duration} min
                </span>
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setShowSpeakerNotes(!showSpeakerNotes)}>
                <Eye className="mr-2 h-4 w-4" />
                {showSpeakerNotes ? 'Hide' : 'Show'} Notes
              </Button>
              <Button variant="outline" onClick={downloadAsText}>
                <Download className="mr-2 h-4 w-4" />
                Download
              </Button>
              <Button onClick={() => setFullscreen(true)}>
                <Maximize2 className="mr-2 h-4 w-4" />
                Fullscreen
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Progress Bar */}
      <div className="w-full bg-gray-200 rounded-full h-2 mb-4">
        <div
          className="bg-primary h-2 rounded-full transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Slide Content */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* Main Slide */}
        <div className={`${fullscreen ? 'col-span-full' : 'lg:col-span-2'}`}>
          <Card className={`${fullscreen ? 'h-[calc(100vh-12rem)]' : 'min-h-[500px]'}`}>
            <CardContent className="p-8 h-full flex flex-col">
              <div className="flex-1">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-3xl font-bold">{slide.title}</h2>
                  <span className="text-sm text-muted-foreground">
                    {currentSlide + 1} / {presentation.content.slides.length}
                  </span>
                </div>
                
                <Separator className="mb-6" />
                
                <div className="space-y-4">
                  {slide.content.map((item, idx) => (
                    <div key={idx} className="flex items-start gap-3">
                      <div className="w-2 h-2 rounded-full bg-primary mt-2 flex-shrink-0" />
                      <p className="text-lg leading-relaxed">{item}</p>
                    </div>
                  ))}
                </div>

                {/* Visual Suggestions */}
                {slide.visual_suggestions && slide.visual_suggestions.length > 0 && (
                  <div className="mt-8 p-4 bg-primary/5 dark:bg-primary-dark/20 rounded-lg">
                    <div className="flex items-center gap-2 mb-2">
                      <Lightbulb className="h-4 w-4 text-primary" />
                      <h4 className="font-semibold text-primary-dark dark:text-primary-light">Visual Suggestions</h4>
                    </div>
                    <ul className="space-y-1 text-sm text-primary-dark dark:text-primary-light">
                      {slide.visual_suggestions.map((visual, idx) => (
                        <li key={idx}>• {visual}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Navigation */}
              <div className="flex items-center justify-between mt-8 pt-4 border-t">
                <Button
                  variant="outline"
                  onClick={handlePrevious}
                  disabled={currentSlide === 0}
                >
                  <ChevronLeft className="mr-2 h-4 w-4" />
                  Previous
                </Button>
                
                <div className="flex gap-1">
                  {presentation.content.slides.map((_, idx) => (
                    <button
                      key={idx}
                      onClick={() => setCurrentSlide(idx)}
                      className={`w-2 h-2 rounded-full transition-colors ${
                        idx === currentSlide ? 'bg-primary' : 'bg-gray-300'
                      }`}
                      aria-label={`Go to slide ${idx + 1}`}
                    />
                  ))}
                </div>

                <Button
                  variant="outline"
                  onClick={handleNext}
                  disabled={currentSlide === presentation.content.slides.length - 1}
                >
                  Next
                  <ChevronRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Speaker Notes */}
        {!fullscreen && showSpeakerNotes && (
          <div className="lg:col-span-1">
            <Card className="min-h-[500px]">
              <CardContent className="p-6">
                <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <PresentationIcon className="h-5 w-5" />
                  Speaker Notes
                </h3>
                {slide.speaker_notes ? (
                  <div className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">
                    {slide.speaker_notes}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground italic">
                    No speaker notes for this slide
                  </p>
                )}

                <Separator className="my-6" />

                <div className="space-y-4">
                  <div>
                    <h4 className="text-sm font-semibold mb-2">Presentation Info</h4>
                    <div className="text-xs text-muted-foreground space-y-1">
                      <p><span className="font-medium">Total Slides:</span> {presentation.content.total_slides}</p>
                      <p><span className="font-medium">Estimated Duration:</span> {presentation.content.estimated_duration} min</p>
                      <p><span className="font-medium">Current Slide:</span> {currentSlide + 1}</p>
                      <p><span className="font-medium">Remaining:</span> {presentation.content.slides.length - currentSlide - 1} slides</p>
                    </div>
                  </div>

                  <div>
                    <h4 className="text-sm font-semibold mb-2">Keyboard Shortcuts</h4>
                    <div className="text-xs text-muted-foreground space-y-1">
                      <p><kbd className="px-2 py-1 bg-gray-100 rounded">←</kbd> Previous slide</p>
                      <p><kbd className="px-2 py-1 bg-gray-100 rounded">→</kbd> Next slide</p>
                      <p><kbd className="px-2 py-1 bg-gray-100 rounded">Esc</kbd> Exit fullscreen</p>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>

      {/* Fullscreen Exit Button */}
      {fullscreen && (
        <div className="fixed top-4 right-4 z-10">
          <Button onClick={() => setFullscreen(false)} variant="outline">
            Exit Fullscreen
          </Button>
        </div>
      )}
    </div>
  );
}
