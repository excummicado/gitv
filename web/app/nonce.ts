// The per-request nonce the page's own inline scripts carry, allowed by the Content-Security-Policy that
// entry.server.tsx sends. Only set on the server; the browser never needs it again.
import { createContext } from "react";

export const NonceContext = createContext<string | undefined>(undefined);
