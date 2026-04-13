import { NavLink, Route, Routes } from 'react-router-dom'
import CreatePage from './pages/CreatePage.jsx'
import ModelsPage from './pages/ModelsPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'

const navLinkClass = ({ isActive }) =>
  isActive ? 'nav-link nav-link--active' : 'nav-link'

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">3D Print Factory</h1>
        <nav className="app-nav">
          <NavLink to="/" end className={navLinkClass}>Create</NavLink>
          <NavLink to="/models" className={navLinkClass}>Models</NavLink>
          <NavLink to="/settings" className={navLinkClass}>Settings</NavLink>
        </nav>
      </header>

      <main className="app-main">
        <Routes>
          <Route path="/" element={<CreatePage />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  )
}
