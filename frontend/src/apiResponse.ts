export class ApiHttpError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Decode API responses without exposing proxy HTML or JSON parser errors. */
export async function readApiResponse(response: Response): Promise<unknown> {
  if (response.status === 413)
    throw new Error("Túl nagy fájl, legfeljebb 50 MB tölthető fel.");
  if (response.status === 204) return null;
  try {
    return await response.json();
  } catch (error) {
    // Cancellation must keep its identity for callers that suppress AbortError.
    if (error instanceof Error && error.name === "AbortError") throw error;
    if (response.ok)
      throw new Error("A kiszolgáló válasza nem értelmezhető. Próbáld újra.");
    // Let the caller handle the HTTP status, including session expiry.
    return null;
  }
}

export function apiErrorMessage(status: number, data: unknown): string {
  const error =
    typeof data === "object" && data !== null && "error" in data
      ? data.error
      : null;
  const message =
    typeof error === "object" && error !== null && "message" in error
      ? error.message
      : null;
  if (typeof message === "string" && message.trim()) return message;
  switch (status) {
    case 401:
      return "Bejelentkezés szükséges.";
    case 403:
      return "Nincs jogosultság a művelethez.";
    case 502:
    case 503:
      return "A szolgáltatás átmenetileg nem érhető el. Próbáld újra később.";
    case 504:
      return "A kiszolgáló nem válaszolt időben. Próbáld újra később.";
    default:
      return "A művelet sikertelen.";
  }
}
