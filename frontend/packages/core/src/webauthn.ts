// WebAuthn ceremonies with the JSON options the API returns (py_webauthn's `options_to_json`: binary fields are
// base64url strings) and credentials sent back as JSON (the shape `PublicKeyCredential.toJSON()` produces).

type Json = Record<string, unknown>;

export function base64urlToBuffer(value: string): ArrayBuffer {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes.buffer;
}

export function bufferToBase64url(value: ArrayBuffer | ArrayBufferView): string {
  const bytes =
    value instanceof ArrayBuffer
      ? new Uint8Array(value)
      : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** The browser supports security keys and passkeys. */
export function webauthnAvailable(): boolean {
  return typeof window !== "undefined" && typeof window.PublicKeyCredential === "function";
}

function credentialDescriptors(list: unknown): PublicKeyCredentialDescriptor[] | undefined {
  if (!Array.isArray(list)) return undefined;
  return list.map((item: Json) => ({
    ...(item as unknown as PublicKeyCredentialDescriptor),
    id: base64urlToBuffer(String(item.id)),
  }));
}

function creationOptions(options: Json): PublicKeyCredentialCreationOptions {
  const user = options.user as Json;
  const excludeCredentials = credentialDescriptors(options.excludeCredentials);
  return {
    ...(options as unknown as PublicKeyCredentialCreationOptions),
    challenge: base64urlToBuffer(String(options.challenge)),
    user: { ...(user as unknown as PublicKeyCredentialUserEntity), id: base64urlToBuffer(String(user.id)) },
    ...(excludeCredentials ? { excludeCredentials } : {}),
  };
}

function requestOptions(options: Json): PublicKeyCredentialRequestOptions {
  const allowCredentials = credentialDescriptors(options.allowCredentials);
  return {
    ...(options as unknown as PublicKeyCredentialRequestOptions),
    challenge: base64urlToBuffer(String(options.challenge)),
    ...(allowCredentials ? { allowCredentials } : {}),
  };
}

function credentialJson(credential: PublicKeyCredential): Json {
  const response = credential.response;
  const body: Json = {
    clientDataJSON: bufferToBase64url(response.clientDataJSON),
  };
  if ("attestationObject" in response) {
    const attestation = response as AuthenticatorAttestationResponse;
    body.attestationObject = bufferToBase64url(attestation.attestationObject);
    if (typeof attestation.getTransports === "function") body.transports = attestation.getTransports();
  } else {
    const assertion = response as AuthenticatorAssertionResponse;
    body.authenticatorData = bufferToBase64url(assertion.authenticatorData);
    body.signature = bufferToBase64url(assertion.signature);
    if (assertion.userHandle) body.userHandle = bufferToBase64url(assertion.userHandle);
  }
  return {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    response: body,
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}

/** Some servers wrap the options in `{publicKey: …}`. */
function unwrap(options: Json): Json {
  return typeof options.publicKey === "object" && options.publicKey !== null
    ? (options.publicKey as Json)
    : options;
}

/** Register a new security key with creation options from the API; returns the credential as JSON. */
export async function webauthnCreate(options: Json): Promise<Json> {
  const credential = await navigator.credentials.create({ publicKey: creationOptions(unwrap(options)) });
  if (!credential) throw new Error("The security key didn't answer.");
  return credentialJson(credential as PublicKeyCredential);
}

/** Sign a challenge with a registered security key (request options from the API); returns the assertion JSON. */
export async function webauthnGet(options: Json): Promise<Json> {
  const credential = await navigator.credentials.get({ publicKey: requestOptions(unwrap(options)) });
  if (!credential) throw new Error("The security key didn't answer.");
  return credentialJson(credential as PublicKeyCredential);
}

/** A readable reason for a failed ceremony (the user cancelled, timed out, or the key isn't registered here). */
export function webauthnError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") return "The security key request was cancelled or timed out.";
    if (error.name === "InvalidStateError") return "This security key is already registered.";
    if (error.name === "SecurityError") return "Security keys need a secure (HTTPS) origin.";
  }
  return error instanceof Error ? error.message : "The security key didn't work.";
}
