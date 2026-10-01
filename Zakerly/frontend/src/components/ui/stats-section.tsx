import React from 'react';
import { Card } from './card';
import { Users, BookOpen, Award, Clock } from 'lucide-react';

const stats = [
  {
    icon: Users,
    value: '10,000+',
    label: 'Active Students',
    description: 'Learning smarter every day'
  },
  {
    icon: BookOpen,
    value: '50,000+',
    label: 'Books Analyzed',
    description: 'Across all disciplines'
  },
  {
    icon: Award,
    value: '1M+',
    label: 'Exams Generated',
    description: 'Personalized assessments'
  },
  {
    icon: Clock,
    value: '75%',
    label: 'Time Saved',
    description: 'On study preparation'
  }
];

export function StatsSection() {
  return (
    <section className="py-16 bg-muted/30">
      <div className="container mx-auto px-4">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold mb-4">
            Trusted by Students and Educators Worldwide
          </h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Join thousands of learners who are already experiencing the power of AI-assisted learning
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {stats.map((stat, index) => (
            <Card 
              key={index}
              className="p-6 text-center interactive-card border-0 shadow-soft hover:shadow-medium"
            >
              <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-gradient-primary flex items-center justify-center">
                <stat.icon className="w-6 h-6 text-primary-foreground" />
              </div>
              <div className="text-2xl font-bold text-primary mb-1">
                {stat.value}
              </div>
              <div className="font-medium text-foreground mb-1">
                {stat.label}
              </div>
              <div className="text-sm text-muted-foreground">
                {stat.description}
              </div>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}