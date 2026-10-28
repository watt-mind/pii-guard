import { createRequester, request } from "../hosted/api";
import { createProjectFetch } from "../api/project";
import type { Requester } from "../hosted/api";

/** Hosted builds retain the cookie requester and contain no local owner credential flow. */
export const localRequest: Requester = import.meta.env.VITE_PII_GUARD_HOSTED === "true"
  ? request
  : (path, body, method) => createRequester(createProjectFetch((...args) => fetch(...args)))(path, body, method);
