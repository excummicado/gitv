import { Link } from "react-router";
import "./login.css";

export function Login() {
  return (
    <main className="gitv-page">
      <div className="gitv-frame">
        {/* Full-width nav matching main page */}
        <nav className="gitv-nav" aria-label="Login navigation">
          <div className="gitv-nav-content">
            <span>Matches</span><span>Players</span><span>Tournaments</span><span>Abyss</span>
            <span className="gitv-search">Search...</span><span>Sign in</span><span>Settings</span>
          </div>
        </nav>

        {/* Centered content stripe */}
        <div className="gitv-content">
          <header className="gitv-brand">
            <Link to="/"><img src="/Logo.png" alt="GITV Logo" className="gitv-mark" /><span>GITV</span></Link>
          </header>

          {/* Login form card centered */}
          <div className="login-wrapper">
            <div className="login-card">
              <div className="login-header">
                <div className="login-title">Sign in to GITV</div>
                <div className="login-subtitle">Enter your credentials to continue</div>
              </div>

              <div className="login-field">
                <label className="login-label">Username or email</label>
                <div className="login-input">username@example.com</div>
              </div>

              <div className="login-field">
                <label className="login-label">Password</label>
                <div className="login-input login-input--password">••••••••••</div>
              </div>

              <div className="login-row">
                <div className="login-checkbox">
                  <span className="login-check-box" />
                  <span className="login-check-label">Remember me</span>
                </div>
                <span className="login-link">Forgot password?</span>
              </div>

              <div className="login-btn">Sign In</div>

              <div className="login-divider"><span>or continue with</span></div>

              <div className="login-socials">
                <div className="login-social-btn">Google</div>
                <div className="login-social-btn">Discord</div>
                <div className="login-social-btn">Steam</div>
              </div>

              <div className="login-footer">
                Don't have an account? <Link to="/register" className="login-link">Create one</Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
