import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './card';
import { Button } from './button';
import { MessageSquare, FolderOpen, ClipboardCheck, ArrowRight } from 'lucide-react';

const features = [
  {
    icon: MessageSquare,
    title: 'Ask the documents',
    description: 'Ask a question in Arabic or English. Narrow it to one document or a specific point or topic.',
    benefits: ['Answers only from KFH documents', 'Document and page cited', 'Says so when a topic is not covered'],
    to: '/chat',
    action: 'Ask a question',
  },
  {
    icon: FolderOpen,
    title: 'Knowledge bases',
    description: 'Documents are grouped into knowledge bases such as Retail Banking, Compliance or HR policies.',
    benefits: ['PDF, Word and text files', 'One place per department or topic', 'Searchable by meaning, not just keywords'],
    to: '/books',
    action: 'Browse knowledge bases',
  },
  {
    icon: ClipboardCheck,
    title: 'Policy quizzes',
    description: 'Generate short quizzes from any document to check that staff know the latest policies and procedures.',
    benefits: ['Built from the document itself', 'Multiple choice and true/false', 'Useful for onboarding and compliance'],
    to: '/exams',
    action: 'Create a quiz',
  },
];

export function FeaturesSection() {
  const navigate = useNavigate();
  return (
    <section className="py-16 bg-muted/30">
      <div className="container mx-auto px-4">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold mb-3">What you can do</h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            One place to find what KFH documents say, without searching through files.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-6">
          {features.map(({ icon: Icon, title, description, benefits, to, action }) => (
            <Card key={title} className="interactive-card flex flex-col" onClick={() => navigate(to)}>
              <CardHeader>
                <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-3">
                  <Icon className="w-6 h-6 text-primary" />
                </div>
                <CardTitle className="text-xl">{title}</CardTitle>
                <CardDescription className="text-base">{description}</CardDescription>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-between gap-6">
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {benefits.map((benefit) => (
                    <li key={benefit} className="flex items-start gap-2">
                      <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
                      {benefit}
                    </li>
                  ))}
                </ul>
                <Button variant="outline" className="w-full justify-between">
                  {action}
                  <ArrowRight className="w-4 h-4" />
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
