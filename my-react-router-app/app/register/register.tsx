import { Link } from "react-router";
import "./register.css";

export function Register() {
  return (
    <main className="gitv-page">
      <div className="gitv-frame">
        <nav className="gitv-nav" aria-label="Register navigation">
          <div className="gitv-nav-content">
            <span>Matches</span><span>Players</span><span>Tournaments</span><span>Abyss</span>
            <span className="gitv-search">Search...</span><Link to="/login"><span>Sign in</span></Link><span>Settings</span>
          </div>
        </nav>

        <div className="gitv-content">
          <header className="gitv-brand">
            <Link to="/"><img src="/Logo.png" alt="GITV Logo" className="gitv-mark" /><span>GITV</span></Link>
          </header>

          <div className="reg-wrapper">
            <div className="reg-card">

              <div className="reg-header">
                <div className="reg-title">Create an Account</div>
                <div className="reg-subtitle">Join GITV and start tracking your matches</div>
              </div>

              <div className="reg-field">
                <label className="reg-label">Email</label>
                <div className="reg-input">username@example.com</div>
              </div>

              <div className="reg-field">
                <label className="reg-label">Nickname</label>
                <div className="reg-input">YourNickname</div>
              </div>

              <div className="reg-field">
                <label className="reg-label">Password</label>
                <div className="reg-input reg-input--password">••••••••••</div>
              </div>

              <div className="reg-field">
                <label className="reg-label">Confirm Password</label>
                <div className="reg-input reg-input--password">••••••••••</div>
              </div>

              <div className="reg-terms">
                <span className="reg-check-box" />
                <span className="reg-check-label">
                  I agree to the <span className="reg-link">Terms of Service</span> and <span className="reg-link">Privacy Policy</span>
                </span>
              </div>

              <div className="reg-btn">Create Account</div>

              <div className="reg-footer">
                Already have an account? <Link to="/login" className="reg-link">Sign in</Link>
              </div>

            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
