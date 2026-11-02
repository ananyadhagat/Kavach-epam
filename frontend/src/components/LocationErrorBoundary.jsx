import { Component } from "react";
import Button from "./Button.jsx";
import ErrorMessage from "./ErrorMessage.jsx";

export default class LocationErrorBoundary extends Component {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    console.error("Location interface rendering failed.", error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="location-render-error" role="alert">
        <ErrorMessage title="Location display could not be loaded">
          GPS capture or the map encountered a display error. Your task details
          and other task actions are still available. Retry the location view.
        </ErrorMessage>
        <Button
          onClick={() => this.setState({ hasError: false })}
          type="button"
          variant="secondary"
        >
          Retry location view
        </Button>
      </div>
    );
  }
}
