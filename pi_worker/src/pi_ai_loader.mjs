const PI_AI_SPECIFIER = "@earendil-works/pi-ai";
const PI_AI_SHIM_URL = new URL("./pi_ai_shim.mjs", import.meta.url).href;

export async function resolve(specifier, context, defaultResolve) {
  if (specifier === PI_AI_SPECIFIER) {
    return {
      url: PI_AI_SHIM_URL,
      shortCircuit: true,
    };
  }
  return defaultResolve(specifier, context, defaultResolve);
}
