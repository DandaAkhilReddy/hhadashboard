/**
 * Typed error classes for the API client.
 *
 * Used by api-fetch / api-server / api-browser. Server pages catch
 * UnauthenticatedError to redirect to /auth/sign-in; ForbiddenError surfaces
 * as a 403 view; ApiError is the catch-all for unexpected backend failures.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly bodyText: string;

  constructor(status: number, path: string, bodyText: string) {
    super(`${path} → ${status}: ${bodyText}`);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
    this.bodyText = bodyText;
  }
}

export class UnauthenticatedError extends ApiError {
  constructor(path: string, bodyText: string) {
    super(401, path, bodyText);
    this.name = "UnauthenticatedError";
  }
}

export class ForbiddenError extends ApiError {
  constructor(path: string, bodyText: string) {
    super(403, path, bodyText);
    this.name = "ForbiddenError";
  }
}
