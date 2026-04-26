/**
 * AES-GCM encryption for the session cookie.
 *
 * The cookie holds the user's Entra access token + its expiry. We encrypt
 * because (a) httpOnly defends against XSS read but not against an attacker
 * who controls the host (cookie editor extensions, MITM in dev), and (b) we
 * never want the raw JWT visible to anyone but the server.
 *
 * Uses Web Crypto API (works in Node 20+ runtime AND Edge runtime, so the
 * same module is callable from middleware and route handlers).
 *
 * SESSION_SECRET must be a 32-byte base64-encoded value. Generate with:
 *   openssl rand -base64 32
 */

const TEXT_ENCODER = new TextEncoder();
const TEXT_DECODER = new TextDecoder();

export const SESSION_COOKIE_NAME = "hha_session";

export type Session = {
  access_token: string;
  /** Unix seconds. Matches the JWT `exp` claim. */
  expires_at: number;
};

let _keyPromise: Promise<CryptoKey> | null = null;

function getSecret(): string {
  const s = process.env.SESSION_SECRET;
  if (!s) {
    throw new Error(
      "SESSION_SECRET env var is required (32-byte base64). " +
        "Generate with: openssl rand -base64 32",
    );
  }
  return s;
}

function base64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  // Accept both standard and URL-safe base64.
  const std = b64.replace(/-/g, "+").replace(/_/g, "/");
  const padded = std + "=".repeat((4 - (std.length % 4)) % 4);
  const bin = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function bytesToBase64Url(bytes: Uint8Array<ArrayBuffer>): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function getKey(): Promise<CryptoKey> {
  if (!_keyPromise) {
    _keyPromise = (async () => {
      const raw = base64ToBytes(getSecret());
      if (raw.length !== 32) {
        throw new Error(`SESSION_SECRET must decode to 32 bytes (got ${raw.length})`);
      }
      return crypto.subtle.importKey("raw", raw, { name: "AES-GCM" }, false, [
        "encrypt",
        "decrypt",
      ]);
    })();
  }
  return _keyPromise;
}

function toAb(view: Uint8Array): Uint8Array<ArrayBuffer> {
  // Copy into a fresh ArrayBuffer-backed Uint8Array. Required because
  // TextEncoder.encode returns Uint8Array<ArrayBufferLike> which Web Crypto
  // refuses under TS 5.7's tightened typings.
  const buf = new ArrayBuffer(view.byteLength);
  const out = new Uint8Array(buf);
  out.set(view);
  return out;
}

export async function encryptSession(session: Session): Promise<string> {
  const key = await getKey();
  const iv = crypto.getRandomValues(new Uint8Array(new ArrayBuffer(12)));
  const plaintext = toAb(TEXT_ENCODER.encode(JSON.stringify(session)));
  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, plaintext),
  );
  const combined = new Uint8Array(new ArrayBuffer(iv.length + ciphertext.length));
  combined.set(iv, 0);
  combined.set(ciphertext, iv.length);
  return bytesToBase64Url(combined);
}

export async function decryptSession(blob: string): Promise<Session | null> {
  try {
    const bytes = base64ToBytes(blob);
    if (bytes.length < 13) return null;
    const iv = bytes.slice(0, 12);
    const ciphertext = bytes.slice(12);
    const key = await getKey();
    const plaintext = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ciphertext);
    const json = TEXT_DECODER.decode(plaintext);
    const parsed = JSON.parse(json) as unknown;
    if (
      parsed &&
      typeof parsed === "object" &&
      "access_token" in parsed &&
      "expires_at" in parsed &&
      typeof (parsed as Session).access_token === "string" &&
      typeof (parsed as Session).expires_at === "number"
    ) {
      return parsed as Session;
    }
    return null;
  } catch {
    return null;
  }
}

export function isSessionExpired(session: Session, nowSec?: number): boolean {
  const now = nowSec ?? Math.floor(Date.now() / 1000);
  return session.expires_at <= now;
}
