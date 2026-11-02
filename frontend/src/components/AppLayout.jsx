import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import Button from "./Button.jsx";
import { getDevelopmentToken, setDevelopmentToken } from "../auth/session.js";

export default function AppLayout() {
  const [token, setToken] = useState(getDevelopmentToken);
  const [tokenMessage, setTokenMessage] = useState("");

  function saveToken(event) {
    event.preventDefault();
    try {
      setDevelopmentToken(token);
      setToken("");
      setTokenMessage("Development token saved for this browser tab.");
    } catch (error) {
      setTokenMessage(error.message);
    }
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="site-header__inner">
          <Link
            className="brand"
            to="/tasks"
            aria-label="KAVACH Field Worker home"
          >
            <span className="brand__mark" aria-hidden="true">
              K
            </span>
            <span>
              <strong>KAVACH</strong>
              <small>Field Worker</small>
            </span>
          </Link>
          <nav className="primary-nav" aria-label="Main navigation">
            <NavLink
              to="/tasks"
              className={({ isActive }) =>
                isActive ? "primary-nav__link is-active" : "primary-nav__link"
              }
              end
            >
              My tasks
            </NavLink>
          </nav>
          <span className="environment-tag">Development</span>
        </div>
      </header>

      <main className="main-content">
        <section className="development-notice" aria-labelledby="auth-heading">
          <div>
            <h2 id="auth-heading">Local development authentication</h2>
            <p>
              This backend uses a development-only bearer token. Production
              authentication is not integrated.
            </p>
          </div>
          <form className="token-form" onSubmit={saveToken}>
            <label htmlFor="development-token">Worker token for this tab</label>
            <div className="token-form__controls">
              <input
                autoComplete="off"
                id="development-token"
                name="development-token"
                onChange={(event) => setToken(event.target.value)}
                type="password"
                value={token}
              />
              <Button type="submit" variant="secondary">
                Save token
              </Button>
            </div>
            {tokenMessage && (
              <p className="token-form__message" role="status">
                {tokenMessage}
              </p>
            )}
          </form>
        </section>
        <Outlet />
      </main>

      <footer className="site-footer">
        <p>Field Worker task execution workspace.</p>
      </footer>
    </div>
  );
}
