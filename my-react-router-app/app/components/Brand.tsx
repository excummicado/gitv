import { Link } from "react-router";
import "./brand.css";

// The site header: logo + wordmark, linking home. Shared by every page.
export function Brand() {
  return (
    <header className="gitv-brand">
      <Link to="/">
        <img src="/Logo.jpeg" alt="" className="gitv-mark" width={58} height={58} />
        <span>GITV</span>
      </Link>
    </header>
  );
}
