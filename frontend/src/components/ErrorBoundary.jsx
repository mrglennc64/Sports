import { Component } from "react";

// Catches render errors (e.g. a malformed row: missing model_prob, null reasons)
// so one bad record shows a recoverable message instead of white-screening the app.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Surface it for debugging; don't crash the whole page.
    console.error("Render error caught by ErrorBoundary:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="error-boundary">
          <h2>Something went wrong rendering this view.</h2>
          <p>
            A data row was malformed, so this page couldn't render. The rest of the app
            is fine — reload, or try a different date.
          </p>
          <button onClick={() => this.setState({ error: null })}>Try again</button>
          <details>
            <summary>Details</summary>
            <pre>{String(this.state.error?.message || this.state.error)}</pre>
          </details>
        </div>
      );
    }
    return this.props.children;
  }
}
