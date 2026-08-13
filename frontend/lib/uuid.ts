/**
 * Generate a v4 UUID.
 * Works across both secure contexts (HTTPS/localhost via crypto.randomUUID)
 * and insecure contexts (HTTP over EC2 IP addresses via Math.random fallback).
 */
export function generateUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try {
      return crypto.randomUUID();
    } catch {
      // Fall through to polyfill
    }
  }

  // RFC4122 v4 UUID generator fallback
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
