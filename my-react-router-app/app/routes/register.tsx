import type { Route } from "./+types/register";
import { Register } from "../register/register";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "GITV · Create Account" },
    { name: "description", content: "Create your GITV account." },
  ];
}

export default function RegisterPage() {
  return <Register />;
}
