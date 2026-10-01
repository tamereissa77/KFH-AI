import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from './button';
import { MessageSquare, FolderOpen, ShieldCheck, FileSearch, ArrowRight } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import heroImage from '@/assets/kfh-hero.jpg';

export function HeroSection() {
  const navigate = useNavigate();
  const { user } = useAuth();

  return (
    <section className="relative overflow-hidden bg-[#062130] min-h-[620px] lg:min-h-[calc(100vh-4rem)] lg:max-h-[860px] flex items-end">
      <img
        src={heroImage}
        alt="KFH Egypt operations floor with document and compliance analytics"
        className="absolute inset-0 w-full h-full object-cover object-[22%_top] lg:object-[30%_center]"
      />
      {/* Navy fade at the bottom so the text stays readable; the top of the image stays clear */}
      <div className="absolute inset-0 bg-gradient-to-t from-[#062130] from-10% via-[#062130]/75 via-40% to-transparent to-70%" />

      <div className="container mx-auto px-4 relative pb-10 lg:pb-14 pt-80 lg:pt-64">
        <div className="grid lg:grid-cols-2 gap-6 lg:gap-12 items-end text-white animate-fade-in">
          <div className="space-y-4">
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/20 border border-primary/40 text-primary-light text-sm font-medium backdrop-blur-sm">
              <ShieldCheck className="w-4 h-4" />
              Internal tool for KFH employees
            </span>
            <h1 className="text-4xl lg:text-6xl font-bold leading-tight">
              Get answers from
              <span className="block text-primary-light">KFH documents</span>
            </h1>
          </div>

          <div className="space-y-6">
            <p className="text-lg text-white/85 leading-relaxed">
              Ask about policies, procedures, product terms and circulars in plain language.
              Every answer comes only from approved internal documents, with the exact
              document and page cited.
            </p>

            <div className="flex flex-col sm:flex-row gap-4">
              {user ? (
                <>
                  <Button size="lg" className="text-base px-8 py-6" onClick={() => navigate('/chat')}>
                    <MessageSquare className="w-5 h-5 mr-2" />
                    Ask the documents
                  </Button>
                  <Button
                    size="lg"
                    variant="outline"
                    className="text-base px-8 py-6 border-2 border-white/40 bg-white/10 text-white hover:bg-white/20 hover:text-white backdrop-blur-sm"
                    onClick={() => navigate('/books')}
                  >
                    <FolderOpen className="w-5 h-5 mr-2" />
                    Browse knowledge bases
                  </Button>
                </>
              ) : (
                <>
                  <Button size="lg" className="text-base px-8 py-6" onClick={() => navigate('/signin')}>
                    Sign in
                    <ArrowRight className="w-5 h-5 ml-2" />
                  </Button>
                  <Button
                    size="lg"
                    variant="outline"
                    className="text-base px-8 py-6 border-2 border-white/40 bg-white/10 text-white hover:bg-white/20 hover:text-white backdrop-blur-sm"
                    onClick={() => navigate('/signup')}
                  >
                    Create an account
                  </Button>
                </>
              )}
            </div>

            <div className="flex flex-col sm:flex-row gap-3 sm:gap-8 text-sm text-white/75">
              <span className="flex items-center gap-2">
                <FileSearch className="w-4 h-4 text-primary-light" />
                Answers cite document and page
              </span>
              <span className="flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-primary-light" />
                Runs on KFH infrastructure
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
