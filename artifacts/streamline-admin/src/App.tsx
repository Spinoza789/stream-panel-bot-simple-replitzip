import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Redirect, Route, Switch, useLocation, Router as WouterRouter } from 'wouter';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
import Welcome from '@/pages/welcome';
import DashboardPage from '@/pages/dashboard';
import { OrdersPage, TrialsPage } from '@/pages/orders';
import OrderDetailPage from '@/pages/order-detail';
import SettingsPage from '@/pages/settings';
import ResellersPage from '@/pages/resellers';
import SubscriptionsPage from '@/pages/subscriptions';
import LogsPage from '@/pages/logs';
import ReportsPage from '@/pages/reports';
import TicketsPage from '@/pages/tickets';
import { SetupPage, SignInPage, SignUpRedirect } from '@/pages/auth';
import { Bar, Logo } from '@/components/admin/bits';
import { AuthProvider, useAuth } from '@/lib/auth';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
});

const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');

function Loading({ label }: { label: string }) {
  return (
    <div className="grid min-h-[100dvh] place-items-center bg-background" data-testid="state-auth-loading">
      <div className="w-72 space-y-3">
        <Logo />
        <Bar className="h-2 w-full" />
        <Bar className="h-2 w-2/3" />
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

function HomeRedirect() {
  const { isLoading, isAuthenticated } = useAuth();
  if (isLoading) return <Loading label="Checking your session…" />;
  if (isAuthenticated) return <Redirect to="/dashboard" />;
  return <Welcome />;
}

function Protected({ children }: { children: ReactNode }) {
  const { isLoading, isAuthenticated } = useAuth();
  if (isLoading) return <Loading label="Checking your session…" />;
  if (!isAuthenticated) return <Redirect to="/sign-in" />;
  return <>{children}</>;
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

function Routes() {
  return (
    <RoutedErrorBoundary>
      <Switch>
        <Route path="/" component={HomeRedirect} />
        <Route path="/sign-in/*?" component={SignInPage} />
        <Route path="/setup" component={SetupPage} />
        <Route path="/sign-up/*?" component={SignUpRedirect} />
        <Route path="/dashboard"><Protected><DashboardPage /></Protected></Route>
        <Route path="/orders"><Protected><OrdersPage /></Protected></Route>
        <Route path="/orders/:id"><Protected><OrderDetailPage /></Protected></Route>
        <Route path="/trials"><Protected><TrialsPage /></Protected></Route>
        <Route path="/subscriptions"><Protected><SubscriptionsPage /></Protected></Route>
        <Route path="/resellers"><Protected><ResellersPage /></Protected></Route>
        <Route path="/reports"><Protected><ReportsPage /></Protected></Route>
        <Route path="/logs"><Protected><LogsPage /></Protected></Route>
        <Route path="/tickets"><Protected><TicketsPage /></Protected></Route>
        <Route path="/settings"><Protected><SettingsPage /></Protected></Route>
        <Route component={NotFound} />
      </Switch>
    </RoutedErrorBoundary>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TooltipProvider>
          <WouterRouter base={basePath}>
            <Routes />
          </WouterRouter>
          <Toaster />
        </TooltipProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
