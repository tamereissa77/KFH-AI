import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Header } from '@/components/ui/header';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { 
  MessageSquare, 
  GraduationCap, 
  Presentation, 
  FileText,
  BookOpen,
  Search,
  Target,
  Clock,
  Users,
  Zap,
  Shield,
  Download,
  ArrowRight,
  CheckCircle,
  Star,
  Sparkles
} from 'lucide-react';

const features = [
  {
    icon: MessageSquare,
    title: 'AI Chat with Books',
    description: 'Transform your reading experience with intelligent conversations about your academic materials.',
    gradient: 'from-primary to-primary-light',
    benefits: [
      'Natural language queries for easy interaction',
      'Source citations for academic credibility',
      'Context-aware responses that understand nuance',
      'Multi-book cross-referencing capabilities',
      'Instant answers to complex questions'
    ],
    useCases: [
      'Clarify difficult concepts while studying',
      'Find specific information quickly',
      'Connect ideas across different chapters',
      'Prepare for discussions and debates'
    ],
    detailedFeatures: [
      {
        title: 'Smart Context Understanding',
        description: 'Our AI understands the broader context of your questions, providing relevant answers that consider the entire book content.'
      },
      {
        title: 'Citation Tracking',
        description: 'Every answer includes precise citations so you can verify information and use it in your academic work.'
      },
      {
        title: 'Follow-up Questions',
        description: 'Build on previous conversations with intelligent follow-up capabilities that remember your learning journey.'
      }
    ]
  },
  {
    icon: GraduationCap,
    title: 'Smart Exam Generator',
    description: 'Create personalized assessments that adapt to your learning style and academic requirements.',
    gradient: 'from-accent to-accent-light',
    benefits: [
      'Multiple question types (MC, T/F, Essay, Short Answer)',
      'Adjustable difficulty levels for progressive learning',
      'Instant generation saves preparation time',
      'Curriculum-aligned content',
      'Unlimited exam variations'
    ],
    useCases: [
      'Self-assessment before major exams',
      'Practice tests for certification prep',
      'Quick knowledge checks during study sessions',
      'Group study session materials'
    ],
    detailedFeatures: [
      {
        title: 'Adaptive Difficulty',
        description: 'Questions automatically adjust based on your performance, ensuring optimal challenge levels.'
      },
      {
        title: 'Question Bank Intelligence',
        description: 'Our AI generates unique questions each time, preventing memorization and encouraging true understanding.'
      },
      {
        title: 'Performance Analytics',
        description: 'Detailed insights into your strengths and areas for improvement with actionable recommendations.'
      }
    ]
  },
  {
    icon: Presentation,
    title: 'Interactive Rehearsal',
    description: 'Practice in a supportive environment that provides immediate feedback and learning insights.',
    gradient: 'from-primary-dark to-primary',
    benefits: [
      'Real-time feedback for immediate learning',
      'Progress tracking across all attempts',
      'Detailed explanations for every answer',
      'Mistake analysis and improvement suggestions',
      'Confidence building through practice'
    ],
    useCases: [
      'Final exam preparation',
      'Concept reinforcement',
      'Identifying knowledge gaps',
      'Building test-taking confidence'
    ],
    detailedFeatures: [
      {
        title: 'Immediate Feedback Loop',
        description: 'Get instant explanations for both correct and incorrect answers to accelerate learning.'
      },
      {
        title: 'Progress Visualization',
        description: 'Track your improvement over time with detailed charts and performance metrics.'
      },
      {
        title: 'Adaptive Review',
        description: 'Focus on areas where you need the most practice with intelligent review recommendations.'
      }
    ]
  },
  {
    icon: FileText,
    title: 'Lecture Scripts',
    description: 'Generate comprehensive presentation materials and teaching resources from your academic content.',
    gradient: 'from-orange-500 to-red-500',
    benefits: [
      'Structured content organization',
      'Multiple export formats (PDF, Word, TXT)',
      'Customizable depth and detail levels',
      'Professional presentation formatting',
      'Time-saving automation'
    ],
    useCases: [
      'Class presentations and seminars',
      'Study group leadership',
      'Teaching assistance materials',
      'Conference presentation prep'
    ],
    detailedFeatures: [
      {
        title: 'Content Structuring',
        description: 'Automatically organize information into logical presentation flow with clear sections and transitions.'
      },
      {
        title: 'Depth Control',
        description: 'Choose from overview, detailed, or in-depth coverage based on your audience and time constraints.'
      },
      {
        title: 'Export Flexibility',
        description: 'Generate scripts in multiple formats optimized for different presentation platforms and tools.'
      }
    ]
  }
];

const additionalFeatures = [
  {
    icon: BookOpen,
    title: 'Smart Book Management',
    description: 'Organize and track your entire academic library with intelligent categorization.'
  },
  {
    icon: Search,
    title: 'Advanced Search',
    description: 'Find information across all your books with powerful semantic search capabilities.'
  },
  {
    icon: Target,
    title: 'Learning Goals',
    description: 'Set and track personalized learning objectives with progress monitoring.'
  },
  {
    icon: Clock,
    title: 'Study Scheduling',
    description: 'Optimize your study time with AI-powered scheduling recommendations.'
  },
  {
    icon: Users,
    title: 'Collaboration Tools',
    description: 'Share resources and collaborate with classmates and study groups.'
  },
  {
    icon: Shield,
    title: 'Privacy & Security',
    description: 'Your academic data is protected with enterprise-grade security measures.'
  }
];

export default function Features() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
      <Header />
      
      <div className="container mx-auto px-4 py-8">
        <div className="max-w-6xl mx-auto">
          {/* Header Section */}
          <div className="text-center mb-16">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary text-sm font-medium mb-4">
              <Sparkles className="w-4 h-4" />
              Detailed Features
            </div>
            <h1 className="text-4xl md:text-5xl font-bold mb-6">
              Everything You Need to
              <span className="bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent"> Excel</span>
            </h1>
            <p className="text-xl text-muted-foreground max-w-3xl mx-auto mb-8">
              Discover how Zakerly's AI-powered features transform your learning experience with intelligent tools designed for academic success.
            </p>
            <Button onClick={() => navigate('/')} variant="outline">
              ← Back to Home
            </Button>
          </div>

          {/* Core Features */}
          <div className="space-y-16 mb-20">
            {features.map((feature, index) => (
              <div key={index} className="relative">
                <Card className="overflow-hidden border-0 shadow-lg">
                  {/* Gradient background */}
                  <div className={`absolute inset-0 bg-gradient-to-br ${feature.gradient} opacity-5`} />
                  
                  <CardContent className="relative p-8 md:p-12">
                    <div className="grid lg:grid-cols-2 gap-12 items-start">
                      {/* Feature Overview */}
                      <div className="space-y-6">
                        <div className={`w-16 h-16 rounded-xl bg-gradient-to-br ${feature.gradient} flex items-center justify-center mb-6`}>
                          <feature.icon className="w-8 h-8 text-white" />
                        </div>
                        
                        <div>
                          <h2 className="text-3xl font-bold mb-4">{feature.title}</h2>
                          <p className="text-lg text-muted-foreground mb-6">
                            {feature.description}
                          </p>
                        </div>

                        <div>
                          <h3 className="text-lg font-semibold mb-4">Key Benefits</h3>
                          <ul className="space-y-3">
                            {feature.benefits.map((benefit, idx) => (
                              <li key={idx} className="flex items-start gap-3">
                                <CheckCircle className="w-5 h-5 text-green-500 mt-0.5 flex-shrink-0" />
                                <span>{benefit}</span>
                              </li>
                            ))}
                          </ul>
                        </div>

                        <div className="flex gap-3">
                          <Button 
                            onClick={() => {
                              if (feature.title.includes('Chat')) navigate('/chat');
                              else if (feature.title.includes('Exam')) navigate('/exams');
                              else if (feature.title.includes('Rehearsal')) navigate('/exam');
                              else if (feature.title.includes('Scripts')) navigate('/scripts');
                            }}
                          >
                            Try {feature.title}
                            <ArrowRight className="w-4 h-4 ml-2" />
                          </Button>
                        </div>
                      </div>

                      {/* Detailed Features */}
                      <div className="space-y-8">
                        <div>
                          <h3 className="text-lg font-semibold mb-4">How It Works</h3>
                          <div className="space-y-4">
                            {feature.detailedFeatures.map((detail, idx) => (
                              <Card key={idx} className="p-4 bg-background/50">
                                <h4 className="font-medium mb-2">{detail.title}</h4>
                                <p className="text-sm text-muted-foreground">{detail.description}</p>
                              </Card>
                            ))}
                          </div>
                        </div>

                        <div>
                          <h3 className="text-lg font-semibold mb-4">Use Cases</h3>
                          <div className="grid gap-3">
                            {feature.useCases.map((useCase, idx) => (
                              <div key={idx} className="flex items-center gap-3 p-3 rounded-lg bg-primary/5">
                                <Star className="w-4 h-4 text-primary flex-shrink-0" />
                                <span className="text-sm">{useCase}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            ))}
          </div>

          {/* Additional Features */}
          <div className="mb-16">
            <div className="text-center mb-12">
              <h2 className="text-3xl font-bold mb-4">Additional Features</h2>
              <p className="text-lg text-muted-foreground">
                More tools to enhance your learning experience
              </p>
            </div>

            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
              {additionalFeatures.map((feature, index) => (
                <Card key={index} className="p-6 hover:shadow-lg transition-shadow duration-200">
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-primary to-secondary flex items-center justify-center flex-shrink-0">
                      <feature.icon className="w-5 h-5 text-white" />
                    </div>
                    <div>
                      <h3 className="font-semibold mb-2">{feature.title}</h3>
                      <p className="text-sm text-muted-foreground">{feature.description}</p>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </div>

          {/* Technology Highlights */}
          <Card className="p-8 bg-gradient-to-br from-primary/5 to-secondary/5 border-0">
            <div className="text-center mb-8">
              <h2 className="text-2xl font-bold mb-4">Powered by Advanced AI</h2>
              <p className="text-muted-foreground max-w-2xl mx-auto">
                Zakerly leverages cutting-edge artificial intelligence to provide accurate, contextual, and personalized learning experiences.
              </p>
            </div>

            <div className="grid md:grid-cols-3 gap-6">
              <div className="text-center">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-primary to-accent flex items-center justify-center mx-auto mb-4">
                  <Zap className="w-6 h-6 text-white" />
                </div>
                <h3 className="font-semibold mb-2">Natural Language Processing</h3>
                <p className="text-sm text-muted-foreground">
                  Advanced NLP models understand context and nuance in academic content
                </p>
              </div>
              
              <div className="text-center">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-primary-dark to-accent flex items-center justify-center mx-auto mb-4">
                  <Target className="w-6 h-6 text-white" />
                </div>
                <h3 className="font-semibold mb-2">Adaptive Learning</h3>
                <p className="text-sm text-muted-foreground">
                  Personalized recommendations based on your learning patterns and progress
                </p>
              </div>
              
              <div className="text-center">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-orange-500 to-red-500 flex items-center justify-center mx-auto mb-4">
                  <Shield className="w-6 h-6 text-white" />
                </div>
                <h3 className="font-semibold mb-2">Secure & Private</h3>
                <p className="text-sm text-muted-foreground">
                  Your academic data is protected with enterprise-grade security measures
                </p>
              </div>
            </div>
          </Card>

          {/* CTA Section */}
          <div className="text-center mt-16">
            <h2 className="text-2xl font-bold mb-4">Ready to Transform Your Learning?</h2>
            <p className="text-muted-foreground mb-6 max-w-2xl mx-auto">
              Join thousands of students and researchers who are already using Zakerly to enhance their academic success.
            </p>
            <div className="flex gap-4 justify-center">
              <Button onClick={() => navigate('/books')} className="bg-gradient-primary">
                Get Started
                <ArrowRight className="w-4 h-4 ml-2" />
              </Button>
              <Button onClick={() => navigate('/')} variant="outline">
                Learn More
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}