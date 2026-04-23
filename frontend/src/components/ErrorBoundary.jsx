import { Component } from 'react'

// Barrière simple autour d'un sous-arbre React. Utilisé principalement pour
// isoler le viewer Three.js (useGLTF peut lever si le .glb est corrompu ou
// si WebGL n'est pas dispo), afin qu'une erreur de rendu ne crashe pas la
// page entière.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('ErrorBoundary caught:', error, info?.componentStack)
  }

  reset = () => {
    this.setState({ error: null })
  }

  render() {
    if (this.state.error) {
      if (typeof this.props.fallback === 'function') {
        return this.props.fallback(this.state.error, this.reset)
      }
      return (
        this.props.fallback ?? (
          <div className="error">
            Erreur de rendu : {String(this.state.error?.message || this.state.error)}
          </div>
        )
      )
    }
    return this.props.children
  }
}
