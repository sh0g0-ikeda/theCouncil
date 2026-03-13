import { getWsBaseUrl } from "@/lib/api";

export function createThreadSocket(threadId: string) {
  return new WebSocket(`${getWsBaseUrl()}/ws/${threadId}`);
}

