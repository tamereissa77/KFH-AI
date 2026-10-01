import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from './button';
import { Card } from './card';
import { MessageSquare, FolderOpen, ShieldCheck, FileSearch, ArrowRight } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';

export function HeroSection() {
  const navigate = useNavigate();
  const { user } = useAuth();

  return (
    <section className="relative py-16 lg:py-20 overflow-hidden">
      <div className="absolute inset-0 bg-gradient-hero opacity-5" />

      <div className="container mx-auto px-4 relative">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          {/* Hero Content */}
          <div className="space-y-8 animate-fade-in">
            <div className="space-y-4">
              <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 text-primary text-sm font-medium">
                <ShieldCheck className="w-4 h-4" />
                Internal tool for KFH employees
              </span>
              <h1 className="text-4xl lg:text-5xl font-bold leading-tight">
                Get answers from
                <span className="block text-primary">KFH documents</span>
              </h1>
              <p className="text-lg text-muted-foreground leading-relaxed">
                Ask about policies, procedures, product terms and circulars in plain language.
                Every answer comes only from approved internal documents, with the exact
                document and page cited.
              </p>
            </div>

            <div className="flex flex-col sm:flex-row gap-4">
              {user ? (
                <>
                  <Button size="lg" className="text-base px-8 py-6" onClick={() => navigate('/chat')}>
                    <MessageSquare className="w-5 h-5 mr-2" />
                    Ask the documents
                  </Button>
                  <Button size="lg" variant="outline" className="text-base px-8 py-6 border-2" onClick={() => navigate('/books')}>
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
                  <Button size="lg" variant="outline" className="text-base px-8 py-6 border-2" onClick={() => navigate('/signup')}>
                    Create an account
                  </Button>
                </>
              )}
            </div>

            <div className="grid sm:grid-cols-2 gap-4 pt-4">
              <div className="flex items-center gap-3 text-sm">
                <div className="w-8 h-8 rounded-full bg-accent/10 flex items-center justify-center">
                  <FileSearch className="w-4 h-4 text-accent" />
                </div>
                <span className="text-muted-foreground">Answers cite document and page</span>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                  <ShieldCheck className="w-4 h-4 text-primary" />
                </div>
                <span className="text-muted-foreground">Runs on KFH infrastructure</span>
              </div>
            </div>
          </div>

          {/* Example exchange */}
          <Card className="p-6 shadow-strong space-y-4" aria-label="Example question and answer">
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-lg px-4 py-3 bg-primary text-primary-foreground text-sm">
                What documents are required to open a corporate current account?
              </div>
            </div>
            <div className="max-w-[90%] rounded-lg px-4 py-3 bg-muted border text-sm space-y-2">
              <p>The account opening policy requires the following for corporate customers [1]:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Valid commercial register and tax card [1]</li>
                <li>Articles of association and authorised signatories list [1]</li>
                <li>IDs of the signatories and beneficial owners [2]</li>
              </ul>
              <div className="pt-2 border-t text-xs text-muted-foreground space-y-1">
                <div>[1] Account Opening Policy, p. 12</div>
                <div>[2] KYC Procedures, p. 4</div>
              </div>
            </div>
            <p className="text-xs text-muted-foreground text-center">Illustrative example</p>
          </Card>
        </div>
      </div>
    </section>
  );
}
