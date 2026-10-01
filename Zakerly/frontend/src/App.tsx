import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "@/contexts/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import Index from "./pages/Index";
import Dashboard from "./pages/Dashboard";
import ExamSetup from "./pages/ExamSetup";
import Exam from "./pages/Exam";
import ExamView from "./pages/ExamView";
import Chat from "./pages/Chat";
import Books from "./pages/Books";
import AddBook from "./pages/AddBook";
import Scripts from './pages/Scripts_New';
import ScriptSetup from './pages/Scripts';
import Presentations from './pages/Presentations';
import PresentationView from './pages/PresentationView';
import Features from "./pages/Features";
import SignIn from "./pages/SignIn";
import SignUp from "./pages/SignUp";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Public routes */}
            <Route path="/" element={<Index />} />
            <Route path="/signin" element={<SignIn />} />
            <Route path="/signup" element={<SignUp />} />
            <Route path="/features" element={<Features />} />
            
            {/* Protected routes - require authentication */}
            <Route path="/home" element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            } />
            <Route path="/dashboard" element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            } />
            <Route path="/books" element={
              <ProtectedRoute>
                <Books />
              </ProtectedRoute>
            } />
            <Route path="/books/add" element={
              <ProtectedRoute>
                <AddBook />
              </ProtectedRoute>
            } />
            <Route path="/chat" element={
              <ProtectedRoute>
                <Chat />
              </ProtectedRoute>
            } />
            <Route path="/exams" element={
              <ProtectedRoute>
                <ExamSetup />
              </ProtectedRoute>
            } />
            <Route path="/exam-setup/:bookTitle" element={
              <ProtectedRoute>
                <ExamSetup />
              </ProtectedRoute>
            } />
            <Route path="/exam" element={
              <ProtectedRoute>
                <Exam />
              </ProtectedRoute>
            } />
            <Route path="/exam-view" element={
              <ProtectedRoute>
                <ExamView />
              </ProtectedRoute>
            } />
            <Route path="/scripts" element={
              <ProtectedRoute>
                <Scripts />
              </ProtectedRoute>
            } />
            <Route path="/scripts/create" element={
              <ProtectedRoute>
                <ScriptSetup />
              </ProtectedRoute>
            } />
            <Route path="/presentations" element={
              <ProtectedRoute>
                <Presentations />
              </ProtectedRoute>
            } />
            <Route path="/presentations/:id" element={
              <ProtectedRoute>
                <PresentationView />
              </ProtectedRoute>
            } />
            
            {/* Catch-all route */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
