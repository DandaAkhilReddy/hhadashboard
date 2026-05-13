// MSW Node test server. Tests import this to override handlers per-test
// via `server.use(http.get(...))`.

import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);
