import React from 'react';
import { NavLink } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { 
  BookOpen, 
  Home, 
  MessageSquare, 
  FileText, 
  GraduationCap,
  Presentation,
  Projector,
  BarChart3
} from 'lucide-react';

const navItems = [
  { to: '/', icon: Home, label: 'Home' },
  { to: '/dashboard', icon: BarChart3, label: 'Dashboard' },
  { to: '/books', icon: BookOpen, label: 'My Books' },
  { to: '/chat', icon: MessageSquare, label: 'Chat' },
  { to: '/exams', icon: GraduationCap, label: 'Exams' },
  { to: '/scripts', icon: FileText, label: 'Scripts' },
  { to: '/presentations', icon: Projector, label: 'Presentations' },
];

export function Navigation() {
  return (
    <nav className="flex items-center gap-1">
      {navItems.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200',
              'hover:bg-primary/10 hover:text-primary',
              isActive
                ? 'bg-primary text-primary-foreground shadow-soft'
                : 'text-muted-foreground'
            )
          }
        >
          <Icon className="w-4 h-4" />
          <span className="hidden md:inline">{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}