import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface State {
  error: Error | null;
}

export class StartupErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Arline UI crashed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="fatal-screen">
        <AlertTriangle size={28} />
        <h1>Arline UI failed to start</h1>
        <p>{this.state.error.message || "Unknown browser startup error"}</p>
        <button onClick={() => location.reload()}>Reload</button>
      </div>
    );
  }
}
