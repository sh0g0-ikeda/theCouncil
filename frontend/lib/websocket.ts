import { getWsBaseUrl } from "@/lib/api";

export function createThreadSocket(threadId: string, backendToken?: string) {
  const url = new URL(`${getWsBaseUrl()}/ws/${threadId}`);
  if (backendToken) {
    url.searchParams.set("token", backendToken);
  }
  return new WebSocket(url.toString());
}
