import type { Route } from "./+types/login";
import { Login } from "../login/login";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "GITV · Sign In" },
    { name: "description", content: "Sign in to your GITV account." },
  ];
}

export default function LoginPage() {
  return <Login />;
}
