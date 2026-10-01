import React from 'react';
import { Header } from '@/components/ui/header';
import { HeroSection } from '@/components/ui/hero-section';
import { StatsSection } from '@/components/ui/stats-section';
import { FeaturesSection } from '@/components/ui/features-section';

const Index = () => {
  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main>
        <HeroSection />
        <StatsSection />
        <FeaturesSection />
      </main>
    </div>
  );
};

export default Index;
