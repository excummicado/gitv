import { useEffect, useState } from "react";
import { getCurrentUser, onAuthChange, verifySession, type User } from "./client";

// Reads the session after mount so server and client render the same markup first.
// `ready` is false until then, so pages can wait instead of flashing a signed-out state.
export function useAuth(): { user: User | null; ready: boolean } {
  const [state, setState] = useState<{ user: User | null; ready: boolean }>({ user: null, ready: false });
  useEffect(() => {
    const sync = () => setState({ user: getCurrentUser(), ready: true });
    sync();
    verifySession();
    const unsubscribe = onAuthChange(sync);
    return () => {
      unsubscribe();
    };
  }, []);
  return state;
}

export function useCurrentUser(): User | null {
  return useAuth().user;
}
