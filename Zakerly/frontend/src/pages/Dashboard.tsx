import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Header } from '@/components/ui/header';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { BooksService, ScriptsService, SessionService } from '@/lib/services';
import { useAuth } from '@/contexts/AuthContext';
import { 
  BookOpen, 
  TrendingUp, 
  Flame,
  BarChart3,
  Activity,
  Plus,
  ArrowRight,
  CheckCircle,
  MessageCircle,
  FileText,
  Loader2,
  AlertCircle,
  Clock,
  Calendar,
  Award,
  Users
} from 'lucide-react';

interface DashboardStats {
  totalBooks: number;
  totalScripts: number;
  totalSessions: number;
  totalChats: number;
  lastActivity: string;
}

interface Book {
  id: number;
  title: string;
  author?: string;
  curriculum_id: number;
  created_at: string;
}

interface Script {
  id: string;
  title: string;
  detail_level: string;
  difficulty: string;
  created_at: string;
}

interface Session {
  id: string;
  session_name?: string;
  created_at: string;
  updated_at: string;
}

interface RecentActivity {
  type: 'book' | 'script' | 'session' | 'chat';
  title: string;
  time: string;
  score?: string;
  icon: React.ComponentType<any>;
}

export default function Dashboard() {
  const { user, trackActivity } = useAuth();
  const navigate = useNavigate();
  const [selectedTab, setSelectedTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [greeting, setGreeting] = useState('');
  
  // State for real data
  const [stats, setStats] = useState<DashboardStats>({
    totalBooks: 0,
    totalScripts: 0,
    totalSessions: 0,
    totalChats: 0,
    lastActivity: 'Never'
  });
  
  const [recentBooks, setRecentBooks] = useState<Book[]>([]);
  const [recentScripts, setRecentScripts] = useState<Script[]>([]);
  const [recentSessions, setRecentSessions] = useState<Session[]>([]);
  const [recentActivity, setRecentActivity] = useState<RecentActivity[]>([]);

  // Set dynamic greeting based on time of day
  useEffect(() => {
    const hour = new Date().getHours();
    if (hour < 12) setGreeting('Good morning');
    else if (hour < 18) setGreeting('Good afternoon');
    else setGreeting('Good evening');
  }, []);

  // Fetch user data on component mount
  useEffect(() => {
    if (user?.sub) {
      fetchDashboardData();
      // Track dashboard view activity
      trackActivity('dashboard_view').catch(err => console.warn('Failed to track dashboard view:', err));
    }
  }, [user?.sub]);

  // Get user's first name for personalization
  const getUserFirstName = () => {
    if (!user?.full_name) return 'there';
    return user.full_name.split(' ')[0];
  };

  const fetchDashboardData = async () => {
    if (!user?.sub) return;
    
    try {
      setLoading(true);
      setError(null);

      // Fetch user stats from auth service
      const statsResponse = await fetch('/api/auth/stats', {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
        }
      });

      if (statsResponse.ok) {
        const userStats = await statsResponse.json();
        setStats({
          totalBooks: userStats.totalBooks,
          totalScripts: userStats.totalScripts,
          totalSessions: userStats.totalSessions,
          totalChats: userStats.totalChats,
          lastActivity: userStats.lastActivity || 'Never'
        });
      }

      // Fetch recent activity
      const activityResponse = await fetch('/api/auth/recent-activity', {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
        }
      });

      if (activityResponse.ok) {
        const recentActivityData = await activityResponse.json();
        const activities: RecentActivity[] = recentActivityData.map((activity: any) => ({
          type: activity.activityType as 'book' | 'script' | 'session' | 'chat',
          title: activity.courseName,
          time: getRelativeTime(activity.lastAccessed),
          icon: activity.activityType === 'script' ? FileText : 
                activity.activityType === 'chat' ? MessageCircle : BookOpen
        }));
        setRecentActivity(activities);
      }

      // Fetch all data in parallel (fallback to original services)
      const [booksData, scriptsData, sessionsData] = await Promise.all([
        BooksService.getBooks().catch(err => {
          console.warn('Failed to fetch books:', err);
          return [];
        }),
        ScriptsService.getUserScripts(user.sub).catch(err => {
          console.warn('Failed to fetch scripts:', err);
          return [];
        }),
        SessionService.getUserSessions(user.sub).catch(err => {
          console.warn('Failed to fetch sessions:', err);
          return [];
        })
      ]);

      // Process and set fallback data if API stats failed
      setRecentBooks(booksData.slice(0, 5) || []);
      setRecentScripts(scriptsData.slice(0, 5) || []);
      setRecentSessions(sessionsData.slice(0, 5) || []);

      // If stats API failed, calculate from local data
      if (!statsResponse.ok) {
        const fallbackStats: DashboardStats = {
          totalBooks: booksData?.length || 0,
          totalScripts: scriptsData?.length || 0,
          totalSessions: sessionsData?.length || 0,
          totalChats: sessionsData?.length || 0,
          lastActivity: getLastActivity(booksData, scriptsData, sessionsData)
        };
        setStats(fallbackStats);
      }

      // Generate recent activity if API failed
      if (!activityResponse.ok) {
        generateRecentActivity(booksData, scriptsData, sessionsData);
      }

    } catch (err) {
      console.error('Error fetching dashboard data:', err);
      setError('Failed to load dashboard data. Please try refreshing the page.');
    } finally {
      setLoading(false);
    }
  };

  const getLastActivity = (books: Book[], scripts: Script[], sessions: Session[]): string => {
    const allDates = [
      ...books.map(b => new Date(b.created_at)),
      ...scripts.map(s => new Date(s.created_at)),
      ...sessions.map(s => new Date(s.updated_at))
    ];

    if (allDates.length === 0) return 'Never';

    const latest = new Date(Math.max(...allDates.map(d => d.getTime())));
    const now = new Date();
    const diffInHours = Math.floor((now.getTime() - latest.getTime()) / (1000 * 60 * 60));

    if (diffInHours < 1) return 'Just now';
    if (diffInHours < 24) return `${diffInHours} hours ago`;
    const diffInDays = Math.floor(diffInHours / 24);
    if (diffInDays === 1) return 'Yesterday';
    if (diffInDays < 7) return `${diffInDays} days ago`;
    return latest.toLocaleDateString();
  };

  const generateRecentActivity = (books: Book[], scripts: Script[], sessions: Session[]) => {
    const activities: RecentActivity[] = [];

    // Add recent books
    books.slice(0, 3).forEach(book => {
      activities.push({
        type: 'book',
        title: `Added "${book.title}"`,
        time: getRelativeTime(book.created_at),
        icon: BookOpen
      });
    });

    // Add recent scripts
    scripts.slice(0, 3).forEach(script => {
      activities.push({
        type: 'script',
        title: `Created "${script.title}"`,
        time: getRelativeTime(script.created_at),
        icon: FileText
      });
    });

    // Add recent sessions
    sessions.slice(0, 3).forEach(session => {
      activities.push({
        type: 'session',
        title: `Chat session: ${session.session_name || 'Unnamed'}`,
        time: getRelativeTime(session.updated_at),
        icon: MessageCircle
      });
    });

    // Sort by time and take the most recent 10
    activities.sort((a, b) => {
      const timeA = new Date(a.time.includes('ago') ? Date.now() : a.time).getTime();
      const timeB = new Date(b.time.includes('ago') ? Date.now() : b.time).getTime();
      return timeB - timeA;
    });

    setRecentActivity(activities.slice(0, 10));
  };

  const getRelativeTime = (dateString: string): string => {
    const date = new Date(dateString);
    const now = new Date();
    const diffInMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60));

    if (diffInMinutes < 1) return 'Just now';
    if (diffInMinutes < 60) return `${diffInMinutes} minutes ago`;
    
    const diffInHours = Math.floor(diffInMinutes / 60);
    if (diffInHours < 24) return `${diffInHours} hours ago`;
    
    const diffInDays = Math.floor(diffInHours / 24);
    if (diffInDays === 1) return 'Yesterday';
    if (diffInDays < 7) return `${diffInDays} days ago`;
    
    return date.toLocaleDateString();
  };

  // Enhanced motivational message with user personalization
  const getMotivationalMessage = () => {
    const recentBooksCount = recentBooks.length;
    const recentScriptsCount = recentScripts.length;
    const userName = getUserFirstName();

    if (stats.totalBooks === 0) {
      return `Welcome to Zakerly, ${userName}! Start by adding your first book to begin your learning journey.`;
    }
    
    if (recentBooksCount > 0 && recentScriptsCount === 0) {
      return `Great start, ${userName}! You've added ${recentBooksCount} book${recentBooksCount > 1 ? 's' : ''}. Now try creating your first lecture script.`;
    }
    
    if (stats.totalSessions === 0) {
      return `Ready to dive deeper, ${userName}? Start a chat session with your books to unlock AI-powered insights.`;
    }
    
    if (stats.totalBooks > 5 && stats.totalScripts > 3) {
      return `Impressive progress, ${userName}! You're building a comprehensive learning library. Keep it up! 🌟`;
    }
    
    if (stats.totalSessions > 10) {
      return `You're on fire, ${userName}! ${stats.totalSessions} chat sessions completed. Your dedication is inspiring! 🔥`;
    }
    
    return `Keep up the excellent work with your learning journey, ${userName}! 📚`;
  };

  const statCards = [
    { 
      label: "Books in Library", 
      value: stats.totalBooks, 
      icon: BookOpen, 
      color: "text-primary", 
      bgColor: "bg-primary/10",
      action: () => navigate('/books'),
      description: "Total books added"
    },
    { 
      label: "Lecture Scripts", 
      value: stats.totalScripts, 
      icon: FileText, 
      color: "text-accent", 
      bgColor: "bg-accent/10",
      action: () => navigate('/scripts'),
      description: "Scripts created"
    },
    { 
      label: "Chat Sessions", 
      value: stats.totalSessions, 
      icon: MessageCircle, 
      color: "text-green-600", 
      bgColor: "bg-green-100",
      action: () => navigate('/chat'),
      description: "AI conversations"
    },
    {
      label: "Learning Hours",
      value: Math.round(stats.totalSessions * 0.5), // Estimate 30 min per session
      icon: Clock,
      color: "text-orange-600",
      bgColor: "bg-orange-100",
      action: () => setSelectedTab("overview"),
      description: "Time invested"
    }
  ];

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-accent/5">
        <Header />
        <div className="container mx-auto px-4 py-8">
          <div className="flex items-center justify-center min-h-[400px]">
            <div className="text-center">
              <Loader2 className="w-8 h-8 animate-spin mx-auto mb-4 text-primary" />
              <p className="text-muted-foreground">Loading your dashboard...</p>
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
        <div className="max-w-7xl mx-auto">
          {/* Personalized Welcome Section */}
          <div className="mb-8">
            <div className="bg-white shadow-sm border border-gray-100 rounded-xl p-6 mb-6">
              <div className="flex items-center justify-between">
                <div>
                  <h1 className="text-3xl font-bold text-gray-900 mb-2">
                    {greeting}, {getUserFirstName()}! 👋
                  </h1>
                  <p className="text-gray-600">
                    Ready to continue your learning journey?
                  </p>
                </div>
                <div className="flex items-center space-x-6">
                  <div className="text-right">
                    <p className="text-sm text-gray-500">Current Streak</p>
                    <div className="flex items-center gap-1">
                      <p className="text-2xl font-bold text-orange-500">
                        {stats.totalSessions > 0 ? Math.min(stats.totalSessions, 30) : 0}
                      </p>
                      <span className="text-lg">🔥</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-gray-500">Last Active</p>
                    <div className="flex items-center gap-1">
                      <Clock className="w-4 h-4 text-gray-500" />
                      <p className="text-sm font-medium text-gray-700">{stats.lastActivity}</p>
                    </div>
                  </div>
                </div>
              </div>
              
              {/* Today's Date and Motivational Message */}
              <div className="mt-4 pt-4 border-t border-gray-100">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-gray-600">
                    <Calendar className="w-5 h-5" />
                    <span className="text-sm">
                      {new Date().toLocaleDateString('en-US', { 
                        weekday: 'long', 
                        year: 'numeric', 
                        month: 'long', 
                        day: 'numeric' 
                      })}
                    </span>
                  </div>
                  <div className="text-sm text-gray-600">
                    {getMotivationalMessage()}
                  </div>
                </div>
              </div>
            </div>

            {/* Error Display */}
            {error && (
              <Alert className="mb-6">
                <AlertCircle className="w-4 h-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </div>

          {/* Enhanced Stats Overview */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            {statCards.map((stat, index) => (
              <Card 
                key={index} 
                className="hover:shadow-lg transition-all duration-200 cursor-pointer group border border-gray-100"
                onClick={stat.action}
              >
                <CardContent className="pt-6">
                  <div className="flex items-center justify-between mb-3">
                    <div className={`w-12 h-12 rounded-lg ${stat.bgColor} flex items-center justify-center group-hover:scale-110 transition-transform`}>
                      <stat.icon className={`w-6 h-6 ${stat.color}`} />
                    </div>
                    <ArrowRight className="w-4 h-4 text-gray-400 group-hover:text-gray-600 group-hover:translate-x-1 transition-all" />
                  </div>
                  <div>
                    <p className="text-2xl font-bold text-gray-900 mb-1">{stat.value}</p>
                    <p className="text-sm font-medium text-gray-700">{stat.label}</p>
                    <p className="text-xs text-gray-500">{stat.description}</p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Quick Actions */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <Card className="hover:shadow-lg transition-all duration-200 cursor-pointer group" onClick={() => navigate('/books/add')}>
              <CardContent className="pt-6">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center group-hover:scale-110 transition-transform">
                    <Plus className="w-6 h-6 text-primary" />
                  </div>
                  <div>
                    <h3 className="font-semibold">Add New Book</h3>
                    <p className="text-sm text-muted-foreground">Expand your library</p>
                  </div>
                  <ArrowRight className="w-5 h-5 text-muted-foreground ml-auto group-hover:translate-x-1 transition-transform" />
                </div>
              </CardContent>
            </Card>

            <Card className="hover:shadow-lg transition-all duration-200 cursor-pointer group" onClick={() => navigate('/scripts')}>
              <CardContent className="pt-6">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-lg bg-accent/10 flex items-center justify-center group-hover:scale-110 transition-transform">
                    <FileText className="w-6 h-6 text-accent" />
                  </div>
                  <div>
                    <h3 className="font-semibold">Create Script</h3>
                    <p className="text-sm text-muted-foreground">Generate lecture content</p>
                  </div>
                  <ArrowRight className="w-5 h-5 text-muted-foreground ml-auto group-hover:translate-x-1 transition-transform" />
                </div>
              </CardContent>
            </Card>

            <Card className="hover:shadow-lg transition-all duration-200 cursor-pointer group" onClick={() => navigate('/chat')}>
              <CardContent className="pt-6">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-lg bg-green-100 flex items-center justify-center group-hover:scale-110 transition-transform">
                    <MessageCircle className="w-6 h-6 text-green-600" />
                  </div>
                  <div>
                    <h3 className="font-semibold">Start Chat</h3>
                    <p className="text-sm text-muted-foreground">AI-powered learning</p>
                  </div>
                  <ArrowRight className="w-5 h-5 text-muted-foreground ml-auto group-hover:translate-x-1 transition-transform" />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Main Content Tabs */}
          <Tabs value={selectedTab} onValueChange={setSelectedTab} className="w-full">
            <TabsList className="grid w-full grid-cols-3 mb-8">
              <TabsTrigger value="overview" className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4" />
                Overview
              </TabsTrigger>
              <TabsTrigger value="activity" className="flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Recent Activity
              </TabsTrigger>
              <TabsTrigger value="library" className="flex items-center gap-2">
                <BookOpen className="w-4 h-4" />
                My Library
              </TabsTrigger>
            </TabsList>

            <TabsContent value="overview">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Learning Streak */}
                <Card>
                  <CardHeader className="pb-4">
                    <CardTitle className="flex items-center gap-2">
                      <Flame className="w-5 h-5 text-orange-500" />
                      Learning Momentum
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-4">
                      <div className="text-center">
                        <div className="text-3xl font-bold text-orange-500 mb-2">
                          {stats.totalSessions > 0 ? Math.min(stats.totalSessions, 30) : 0} days
                        </div>
                        <p className="text-muted-foreground">Current streak</p>
                      </div>
                      <div className="grid grid-cols-7 gap-1">
                        {Array.from({ length: 7 }, (_, i) => (
                          <div
                            key={i}
                            className={`h-8 rounded flex items-center justify-center text-xs font-medium ${
                              i < Math.min(stats.totalSessions, 7)
                                ? 'bg-orange-100 text-orange-600'
                                : 'bg-gray-100 text-gray-400'
                            }`}
                          >
                            {i < Math.min(stats.totalSessions, 7) ? '🔥' : '💤'}
                          </div>
                        ))}
                      </div>
                      <p className="text-sm text-center text-muted-foreground">
                        Keep learning daily to maintain your streak!
                      </p>
                    </div>
                  </CardContent>
                </Card>

                {/* Performance Overview */}
                <Card>
                  <CardHeader className="pb-4">
                    <CardTitle className="flex items-center gap-2">
                      <TrendingUp className="w-5 h-5 text-green-500" />
                      This Week's Activity
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-4">
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-muted-foreground">Books Added</span>
                        <span className="font-semibold">{recentBooks.length}</span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-muted-foreground">Scripts Created</span>
                        <span className="font-semibold">{recentScripts.length}</span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-muted-foreground">Chat Sessions</span>
                        <span className="font-semibold">{recentSessions.length}</span>
                      </div>
                      <div className="pt-4 border-t">
                        <div className="flex items-center gap-2">
                          <CheckCircle className="w-4 h-4 text-green-500" />
                          <span className="text-sm">
                            {stats.totalBooks + stats.totalScripts + stats.totalSessions > 0 
                              ? "Great progress this week!" 
                              : "Start your learning journey today!"}
                          </span>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            <TabsContent value="activity">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Activity className="w-5 h-5" />
                    Recent Activity
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {recentActivity.length > 0 ? (
                    <div className="space-y-4">
                      {recentActivity.map((activity, index) => {
                        const IconComponent = activity.icon;
                        return (
                          <div key={index} className="flex items-center gap-4 p-3 rounded-lg hover:bg-accent/50 transition-colors">
                            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                              <IconComponent className="w-5 h-5 text-primary" />
                            </div>
                            <div className="flex-1">
                              <p className="font-medium">{activity.title}</p>
                              <p className="text-sm text-muted-foreground">{activity.time}</p>
                            </div>
                            {activity.score && (
                              <Badge variant="secondary" className="bg-green-100 text-green-700">
                                {activity.score}
                              </Badge>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-center py-8">
                      <Activity className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
                      <p className="text-muted-foreground">No recent activity</p>
                      <p className="text-sm text-muted-foreground mt-2">
                        Start by adding a book or creating your first script!
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="library">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Recent Books */}
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between">
                    <CardTitle className="flex items-center gap-2">
                      <BookOpen className="w-5 h-5" />
                      Recent Books
                    </CardTitle>
                    <Button variant="outline" size="sm" onClick={() => navigate('/books')}>
                      View All
                    </Button>
                  </CardHeader>
                  <CardContent>
                    {recentBooks.length > 0 ? (
                      <div className="space-y-3">
                        {recentBooks.map((book) => (
                          <div key={book.id} className="flex items-center gap-3 p-3 rounded-lg hover:bg-accent/50 transition-colors">
                            <div className="w-10 h-10 rounded bg-primary/10 flex items-center justify-center">
                              <BookOpen className="w-5 h-5 text-primary" />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="font-medium truncate">{book.title}</p>
                              {book.author && (
                                <p className="text-sm text-muted-foreground truncate">{book.author}</p>
                              )}
                              <p className="text-xs text-muted-foreground">
                                Added {getRelativeTime(book.created_at)}
                              </p>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-6">
                        <BookOpen className="w-8 h-8 mx-auto text-muted-foreground mb-2" />
                        <p className="text-muted-foreground">No books yet</p>
                        <Button size="sm" className="mt-3" onClick={() => navigate('/books/add')}>
                          Add Your First Book
                        </Button>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Recent Scripts */}
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between">
                    <CardTitle className="flex items-center gap-2">
                      <FileText className="w-5 h-5" />
                      Recent Scripts
                    </CardTitle>
                    <Button variant="outline" size="sm" onClick={() => navigate('/scripts')}>
                      View All
                    </Button>
                  </CardHeader>
                  <CardContent>
                    {recentScripts.length > 0 ? (
                      <div className="space-y-3">
                        {recentScripts.map((script) => (
                          <div key={script.id} className="flex items-center gap-3 p-3 rounded-lg hover:bg-accent/50 transition-colors">
                            <div className="w-10 h-10 rounded bg-accent/10 flex items-center justify-center">
                              <FileText className="w-5 h-5 text-accent" />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="font-medium truncate">{script.title}</p>
                              <div className="flex gap-2 mt-1">
                                <Badge variant="outline" className="text-xs">
                                  {script.detail_level}
                                </Badge>
                                <Badge variant="outline" className="text-xs">
                                  {script.difficulty}
                                </Badge>
                              </div>
                              <p className="text-xs text-muted-foreground">
                                Created {getRelativeTime(script.created_at)}
                              </p>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-6">
                        <FileText className="w-8 h-8 mx-auto text-muted-foreground mb-2" />
                        <p className="text-muted-foreground">No scripts yet</p>
                        <Button size="sm" className="mt-3" onClick={() => navigate('/scripts')}>
                          Create Your First Script
                        </Button>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
