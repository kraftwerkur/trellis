"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="card-dark p-6 text-center space-y-3">
          <AlertTriangle className="w-8 h-8 text-status-warning mx-auto" />
          <div className="text-sm text-[hsl(var(--foreground))] font-medium">
            {this.props.fallbackTitle ?? "Something went wrong"}
          </div>
          <div className="text-xs text-[hsl(var(--muted-foreground))]/60 font-data max-w-md mx-auto truncate">
            {this.state.error?.message}
          </div>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs text-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 rounded hover:bg-[hsl(var(--primary))]/20 transition-colors"
          >
            <RefreshCw className="w-3 h-3" /> Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
